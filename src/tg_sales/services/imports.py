"""Importing prospect lists: preview, match review, atomic commit and undo.

Workflow:

1. :func:`~tg_sales.services.import_files.inspect_file` and
   :func:`~tg_sales.services.import_files.read_table` read the file.
2. :meth:`ImportService.plan` interprets rows with the chosen column mapping,
   groups rows that describe the same organization, and matches each group
   against existing prospects. Groups whose match is uncertain are marked for
   review; the user decides (create new, add to an existing prospect, skip).
3. :meth:`ImportService.preview` runs the whole import inside a transaction
   that is rolled back, so the summary shows exact created/updated/skipped
   counts before anything is saved.
4. :meth:`ImportService.commit` applies the import in one transaction. Rows
   with errors are skipped and reported; any failure or cancellation rolls
   back everything.
5. :meth:`ImportService.undo` reverses an import using its change log, keeping
   records that were edited after the import.

Existing values are never overwritten: imports only fill empty fields and add
contacts, games and tags. Conflicting values are reported as warnings.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tg_sales.cancellation import CancelToken, OperationCancelledError
from tg_sales.db.database import Database
from tg_sales.db.models import (
    Activity,
    Contact,
    EntityMixin,
    Game,
    GameOrganization,
    ImportChange,
    ImportJob,
    Opportunity,
    Organization,
)
from tg_sales.domain.enums import (
    ActivityType,
    ContactStatus,
    GameRole,
    OrganizationType,
    RecordSource,
    ReleasePrecision,
)
from tg_sales.domain.ids import new_id
from tg_sales.domain.importing import (
    SPEC_BY_FIELD,
    ColumnMapping,
    ContactRecord,
    GameRecord,
    ImportField,
    ImportRecord,
    IssueSeverity,
    RecordOptions,
    RowIssue,
    RowResult,
    build_records,
)
from tg_sales.domain.normalization import (
    core_name,
    domain_from_url,
    identifying_domain,
    normalize_name,
)
from tg_sales.domain.prospects import (
    DuplicateCandidate,
    MatchStrength,
    OrganizationIndex,
    merge_tags,
    name_conflicts_with_domain,
)
from tg_sales.domain.time import format_utc
from tg_sales.errors import TgSalesError
from tg_sales.repositories.imports import (
    ACTION_CREATED,
    ACTION_UPDATED,
    STATUS_COMMITTED,
    STATUS_UNDONE,
    ImportRepository,
)
from tg_sales.repositories.prospects import (
    ContactRepository,
    GameRepository,
    OrganizationRepository,
)
from tg_sales.services.csv_export import write_csv
from tg_sales.services.import_files import RawTable, SourceFile
from tg_sales.services.ledger import ActivityLedger

logger = logging.getLogger(__name__)

ACTION_ROW = "row"  # change-log entry recording a source row's fingerprint

ProgressCallback = Callable[[int, str], None]

_MODELS: dict[str, type[EntityMixin]] = {
    "organizations": Organization,
    "contacts": Contact,
    "games": Game,
    "game_organizations": GameOrganization,
}
_ENUM_FIELDS: dict[str, type[StrEnum]] = {
    "company_type": OrganizationType,
    "contact_status": ContactStatus,
    "release_precision": ReleasePrecision,
}


class ImportFailedError(TgSalesError):
    """An import could not be completed; nothing was saved."""


class PlanAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    REVIEW = "review"


class Decision(StrEnum):
    CREATE_NEW = "create"
    MERGE = "merge"
    SKIP = "skip"


@dataclass
class ImportGroup:
    """Rows describing one organization, and what the import will do with them."""

    key: str
    records: list[ImportRecord]
    action: PlanAction
    reason: str
    target_id: str | None = None
    target_name: str | None = None
    candidates: tuple[DuplicateCandidate, ...] = ()
    decision: Decision | None = None
    decision_target_id: str | None = None

    @property
    def name(self) -> str:
        return self.records[0].organization_name

    @property
    def row_numbers(self) -> list[int]:
        return [r.row_number for r in self.records]

    @property
    def needs_decision(self) -> bool:
        return self.action is PlanAction.REVIEW and self.decision is None

    def decide(self, decision: Decision, target_id: str | None = None) -> None:
        if decision is Decision.MERGE:
            allowed = {c.id for c in self.candidates} | ({self.target_id} - {None})
            if target_id not in allowed:
                raise ValueError("merge target must be one of the group's candidates")
        self.decision = decision
        self.decision_target_id = target_id if decision is Decision.MERGE else None

    def effective(self) -> tuple[PlanAction, str | None]:
        """The action to perform and its target organization id."""
        if self.decision is Decision.CREATE_NEW:
            return PlanAction.CREATE, None
        if self.decision is Decision.SKIP:
            return PlanAction.SKIP, None
        if self.decision is Decision.MERGE:
            return PlanAction.UPDATE, self.decision_target_id
        return self.action, self.target_id


@dataclass
class ImportPlan:
    job_id: str
    source: SourceFile
    sheet_name: str | None
    mappings: list[ColumnMapping]
    options: RecordOptions
    table: RawTable
    results: list[RowResult]
    groups: list[ImportGroup]
    previous_imports: list[tuple[datetime, str]] = field(default_factory=list)

    @property
    def issues(self) -> list[RowIssue]:
        return [issue for result in self.results for issue in result.issues]

    @property
    def error_rows(self) -> list[RowResult]:
        return [r for r in self.results if r.has_errors]

    @property
    def blank_rows(self) -> int:
        return sum(1 for r in self.results if r.blank)

    @property
    def unresolved(self) -> list[ImportGroup]:
        return [g for g in self.groups if g.needs_decision]

    def decide_all_unresolved(self, decision: Decision) -> None:
        if decision is Decision.MERGE:
            raise ValueError("choose a target for each merge individually")
        for group in self.unresolved:
            group.decide(decision)


@dataclass
class ImportCounts:
    organizations_created: int = 0
    organizations_updated: int = 0
    organizations_skipped: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0
    games_created: int = 0
    error_rows: int = 0
    warnings: int = 0

    @property
    def created(self) -> int:
        return self.organizations_created

    @property
    def updated(self) -> int:
        return self.organizations_updated

    @property
    def skipped(self) -> int:
        return self.organizations_skipped


@dataclass
class ImportOutcome:
    job_id: str
    counts: ImportCounts
    issues: list[RowIssue]
    committed: bool


@dataclass(frozen=True)
class ImportHistoryEntry:
    id: str
    file_name: str
    file_type: str
    sheet_name: str | None
    started_at: datetime
    status: str
    created: int
    updated: int
    skipped: int
    errors: int
    warnings: int
    undone_at: datetime | None

    @property
    def can_undo(self) -> bool:
        return self.status == STATUS_COMMITTED


@dataclass(frozen=True)
class UndoOutcome:
    reverted: int
    kept: int


# -- planning -------------------------------------------------------------------------


def _group_key(record: ImportRecord) -> tuple[str | None, str]:
    domain = identifying_domain(record.domain)
    return (f"d:{domain}" if domain else None), (
        core_name(record.organization_name) or normalize_name(record.organization_name)
    )


def group_records(records: Iterable[ImportRecord]) -> list[list[ImportRecord]]:
    """Group rows that describe the same organization within the file.

    Rows with the same identifying website domain belong together; rows without
    a website join the group with the same name (or form one). Rows with the
    same name but different websites stay separate: they may be different
    studios.
    """
    groups: dict[str, list[ImportRecord]] = {}
    by_name: dict[str, str] = {}
    for record in records:
        domain_key, name = _group_key(record)
        if domain_key is not None:
            key = domain_key
            by_name.setdefault(name, key)
        else:
            key = by_name.setdefault(name, f"n:{name}")
        groups.setdefault(key, []).append(record)
    return list(groups.values())


def _match(
    index: OrganizationIndex,
    email_index: dict[str, str],
    records: list[ImportRecord],
) -> tuple[PlanAction, str, str | None, tuple[DuplicateCandidate, ...]]:
    first = records[0]
    domain = next((r.domain for r in records if identifying_domain(r.domain)), None)
    emails = {c.email for r in records for c in r.contacts if c.email}
    email_matches: dict[str, str] = {}
    for email in sorted(emails):
        org_id = email_index.get(email)
        if org_id is not None:
            email_matches.setdefault(org_id, email)
    candidates = tuple(index.find(first.organization_name, domain, email_matches=email_matches))
    strong = [c for c in candidates if c.strength is MatchStrength.STRONG]
    same_name = [c for c in candidates if c.strength is MatchStrength.NAME]
    if len(strong) == 1:
        return PlanAction.UPDATE, strong[0].reason, strong[0].id, candidates
    if len(strong) > 1:
        return PlanAction.REVIEW, "Matches several existing prospects", None, candidates
    if len(same_name) == 1 and not name_conflicts_with_domain(same_name[0], domain):
        return PlanAction.UPDATE, "Same name as an existing prospect", same_name[0].id, candidates
    if same_name:
        reason = (
            "Same name as an existing prospect with a different website"
            if len(same_name) == 1
            else "Same name as several existing prospects"
        )
        return PlanAction.REVIEW, reason, None, candidates
    if candidates:
        return PlanAction.REVIEW, "Similar name to an existing prospect", None, candidates
    return PlanAction.CREATE, "New prospect", None, candidates


# -- applying -------------------------------------------------------------------------


@dataclass
class _Context:
    session: Session
    job: ImportJob
    ledger: ActivityLedger
    counts: ImportCounts
    issues: list[RowIssue]
    file_name: str

    def change(
        self,
        table: str,
        entity_id: str,
        action: str,
        *,
        row_number: int | None = None,
        fingerprint: str | None = None,
        previous: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            ImportChange(
                import_job_id=self.job.id,
                entity_table=table,
                entity_id=entity_id,
                action=action,
                row_number=row_number,
                row_fingerprint=fingerprint,
                previous_values=previous or {},
            )
        )

    def warn(self, row_number: int, column: str, message: str) -> None:
        self.issues.append(RowIssue(row_number, IssueSeverity.WARNING, column, message))


def _stored(value: object) -> object:
    """Value in JSON form for the undo log."""
    if isinstance(value, datetime):
        return format_utc(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def _equivalent(name: str, old: object, new: object) -> bool:
    """Whether an existing value and an imported value mean the same thing."""
    if name in {"website", "store_url"} and isinstance(old, str) and isinstance(new, str):
        return domain_from_url(old) == domain_from_url(new) and (
            name == "website" or old.rstrip("/") == new.rstrip("/")
        )
    if isinstance(old, str) and isinstance(new, str):
        return normalize_name(old) == normalize_name(new)
    return old == new


def _fill(
    ctx: _Context,
    entity: Any,
    values: dict[str, Any],
    row_number: int,
    labels: dict[str, str],
) -> dict[str, Any]:
    """Fill empty attributes; warn about differing values. Returns previous values."""
    previous: dict[str, Any] = {}
    for name, new in values.items():
        if new is None or new == "":
            continue
        old = getattr(entity, name)
        empty = old is None or old == "" or old == OrganizationType.UNKNOWN
        if name == "contact_status":
            empty = old is ContactStatus.UNKNOWN
            if new is ContactStatus.UNKNOWN:
                continue
        if empty:
            previous[name] = _stored(old)
            setattr(entity, name, new)
        elif name in labels and not _equivalent(name, old, new):
            ctx.warn(
                row_number,
                labels[name],
                f"Kept the existing {labels[name].lower()}; the file has a different value.",
            )
    return previous


def _merged_contacts(records: Sequence[ImportRecord]) -> list[tuple[int, str, ContactRecord]]:
    """Contacts of all rows, without repeats (same email, or same name without email)."""
    seen: set[str] = set()
    result = []
    for record in records:
        for contact in record.contacts:
            key = (
                f"e:{contact.email}"
                if contact.email
                else f"n:{normalize_name(contact.name or '')}|{sorted(contact.social_urls.items())}"
            )
            if key in seen:
                continue
            seen.add(key)
            result.append((record.row_number, record.fingerprint, contact))
    return result


def _merged_games(records: Sequence[ImportRecord]) -> list[tuple[int, GameRecord]]:
    seen: set[str] = set()
    result = []
    for record in records:
        if record.game is None:
            continue
        key = normalize_name(record.game.title)
        if key not in seen:
            seen.add(key)
            result.append((record.row_number, record.game))
    return result


def _organization_values(records: Sequence[ImportRecord], ctx: _Context) -> dict[str, Any]:
    labels = {
        "website": "Website",
        "company_type": "Company type",
        "location": "Location",
        "country": "Country",
    }
    values: dict[str, Any] = {}
    origin: dict[str, int] = {}
    for record in records:
        for name, value in (
            ("website", record.website),
            ("domain", record.domain),
            ("company_type", record.company_type),
            ("location", record.location),
            ("country", record.country),
        ):
            if value is None:
                continue
            if name not in values:
                values[name] = value
                origin[name] = record.row_number
            elif name in labels and not _equivalent(name, values[name], value):
                ctx.warn(
                    record.row_number,
                    labels[name],
                    f"Row {origin[name]} gives a different {labels[name].lower()} for this "
                    "prospect; the first value was used.",
                )
    notes = [r.notes for r in records if r.notes]
    values["notes"] = "\n".join(dict.fromkeys(notes)) if notes else None
    values["tags"] = merge_tags((), (t for r in records for t in r.tags))
    return values


def _contact_values(contact: ContactRecord) -> dict[str, Any]:
    return {
        "name": contact.name,
        "role_title": contact.role_title,
        "business_email": contact.email,
        "email_normalized": contact.email,
        "contact_status": contact.status,
        "notes": contact.notes,
    }


def _apply_contacts(
    ctx: _Context, organization_id: str, records: Sequence[ImportRecord], existing: list[Contact]
) -> None:
    labels = {"role_title": "Contact role / title", "name": "Contact name"}
    for row_number, _, contact in _merged_contacts(records):
        match = None
        if contact.email:
            match = next((c for c in existing if c.email_normalized == contact.email), None)
        if match is None and contact.name:
            name_key = normalize_name(contact.name)
            match = next(
                (
                    c
                    for c in existing
                    if c.name
                    and normalize_name(c.name) == name_key
                    and (c.email_normalized is None or contact.email is None)
                ),
                None,
            )
        values = _contact_values(contact)
        if match is None:
            # Ids are assigned up front so rows are inserted in one batch at the end.
            created = Contact(
                id=new_id(),
                organization_id=organization_id,
                social_urls=dict(contact.social_urls),
                source=RecordSource.IMPORT,
                provenance=f"Imported from {ctx.file_name}",
                **values,
            )
            ctx.session.add(created)
            existing.append(created)
            ctx.change("contacts", created.id, ACTION_CREATED, row_number=row_number)
            ctx.counts.contacts_created += 1
            continue
        previous = _fill(ctx, match, values, row_number, labels)
        socials = dict(match.social_urls)
        added = {k: v for k, v in contact.social_urls.items() if v not in socials.values()}
        for key, url in added.items():
            new_key = key
            suffix = 2
            while new_key in socials:
                new_key = f"{key} {suffix}"
                suffix += 1
            socials[new_key] = url
        if added:
            previous["social_urls"] = dict(match.social_urls)
            match.social_urls = socials
        if previous:
            ctx.change(
                "contacts", match.id, ACTION_UPDATED, row_number=row_number, previous=previous
            )
            ctx.counts.contacts_updated += 1


def _apply_games(
    ctx: _Context, organization_id: str, records: Sequence[ImportRecord], *, new_organization: bool
) -> None:
    games = GameRepository(ctx.session)
    linked: dict[str, Game] = (
        {}
        if new_organization
        else {normalize_name(g.title): g for g, _ in games.for_organization(organization_id)}
    )
    for row_number, record in _merged_games(records):
        game = linked.get(normalize_name(record.title))
        created_game = False
        if game is None and record.store_url:
            game = games.find_by_store_url(record.store_url)
        if game is None:
            game = Game(
                id=new_id(),
                title=record.title,
                platform=record.platform,
                store_url=record.store_url,
                release_date=record.release_date,
                release_precision=record.release_precision,
                source=RecordSource.IMPORT,
                discovered_at_utc=None,
            )
            ctx.session.add(game)
            created_game = True
            ctx.change("games", game.id, ACTION_CREATED, row_number=row_number)
            ctx.counts.games_created += 1
        else:
            previous = _fill(
                ctx,
                game,
                {
                    "platform": record.platform,
                    "store_url": record.store_url,
                    "release_date": record.release_date,
                },
                row_number,
                {"release_date": "Release date"},
            )
            if "release_date" in previous:
                previous["release_precision"] = game.release_precision.value
                game.release_precision = record.release_precision
            if previous:
                ctx.change(
                    "games", game.id, ACTION_UPDATED, row_number=row_number, previous=previous
                )
        already_linked = not (new_organization or created_game) and (
            games.find_link(game.id, organization_id) is not None
        )
        if not already_linked:
            link = GameOrganization(
                id=new_id(),
                game_id=game.id,
                organization_id=organization_id,
                role=GameRole.DEVELOPER,
            )
            ctx.session.add(link)
            ctx.change("game_organizations", link.id, ACTION_CREATED, row_number=row_number)
        linked[normalize_name(record.title)] = game


def _apply_group(ctx: _Context, group: ImportGroup) -> None:
    action, target_id = group.effective()
    records = group.records
    first = records[0]
    if action is PlanAction.SKIP:
        ctx.counts.organizations_skipped += 1
        return
    if action is PlanAction.REVIEW:
        raise ValueError("every group needing review must be decided before importing")
    values = _organization_values(records, ctx)
    organizations = OrganizationRepository(ctx.session)
    if action is PlanAction.CREATE:
        organization = Organization(
            id=new_id(),
            name=first.organization_name,
            normalized_name=normalize_name(first.organization_name),
            website=values.get("website"),
            domain=values.get("domain"),
            company_type=values.get("company_type") or OrganizationType.UNKNOWN,
            location=values.get("location"),
            country=values.get("country"),
            tags=list(values["tags"]),
            notes=values["notes"],
            source=RecordSource.IMPORT,
        )
        ctx.session.add(organization)
        ctx.change(
            "organizations",
            organization.id,
            ACTION_CREATED,
            row_number=first.row_number,
            fingerprint=first.fingerprint,
        )
        ctx.ledger.record(
            ActivityType.ORGANIZATION_CREATED,
            organization_id=organization.id,
            payload={"name": organization.name, "import_job_id": ctx.job.id},
            source=RecordSource.IMPORT,
            flush=False,
        )
        ctx.counts.organizations_created += 1
        existing_contacts: list[Contact] = []
    else:
        if target_id is None:
            raise ValueError("an update needs a target organization")
        found = organizations.get(target_id)
        if found is None:
            for record in records:
                ctx.issues.append(
                    RowIssue(
                        record.row_number,
                        IssueSeverity.ERROR,
                        SPEC_BY_FIELD[ImportField.ORGANIZATION_NAME].label,
                        "The matching prospect no longer exists; the row was not imported.",
                    )
                )
            ctx.counts.error_rows += len(records)
            return
        organization = found
        before_contacts = ctx.counts.contacts_created + ctx.counts.contacts_updated
        before_games = ctx.counts.games_created
        previous = _fill(
            ctx,
            organization,
            {k: v for k, v in values.items() if k not in {"tags"}},
            first.row_number,
            {
                "website": "Website",
                "company_type": "Company type",
                "location": "Location",
                "country": "Country",
            },
        )
        merged = merge_tags(organization.tags, values["tags"])
        if tuple(organization.tags) != merged:
            previous["tags"] = list(organization.tags)
            organization.tags = list(merged)
        existing_contacts = ContactRepository(ctx.session).for_organization(organization.id)
        _apply_contacts(ctx, organization.id, records, existing_contacts)
        _apply_games(ctx, organization.id, records, new_organization=False)
        changed_children = (
            ctx.counts.contacts_created + ctx.counts.contacts_updated != before_contacts
            or ctx.counts.games_created != before_games
        )
        if previous:
            ctx.change(
                "organizations",
                organization.id,
                ACTION_UPDATED,
                row_number=first.row_number,
                previous=previous,
            )
            ctx.ledger.record(
                ActivityType.FIELD_CHANGE,
                organization_id=organization.id,
                payload={
                    "entity": "organizations",
                    "entity_id": organization.id,
                    "import_job_id": ctx.job.id,
                    "changes": {
                        name: {"old": old, "new": _stored(getattr(organization, name))}
                        for name, old in previous.items()
                    },
                },
                source=RecordSource.IMPORT,
            )
        if previous or changed_children:
            ctx.counts.organizations_updated += 1
        else:
            ctx.counts.organizations_skipped += 1
        for record in records:
            ctx.change(
                "organizations",
                organization.id,
                ACTION_ROW,
                row_number=record.row_number,
                fingerprint=record.fingerprint,
            )
        return
    _apply_contacts(ctx, organization.id, records, existing_contacts)
    _apply_games(ctx, organization.id, records, new_organization=True)
    for record in records[1:]:
        ctx.change(
            "organizations",
            organization.id,
            ACTION_ROW,
            row_number=record.row_number,
            fingerprint=record.fingerprint,
        )


def _error_summary(issues: Sequence[RowIssue]) -> str | None:
    errors = Counter(i.message for i in issues if i.severity is IssueSeverity.ERROR)
    if not errors:
        return None
    return "; ".join(f"{message} ({count})" for message, count in errors.most_common(10))


class _DryRun(Exception):  # noqa: N818 - control-flow signal, not an error
    """Raised to roll back a preview transaction."""


class ImportService:
    def __init__(self, database: Database, actor_id: str | None) -> None:
        self._database = database
        self._actor_id = actor_id

    def plan(
        self,
        source: SourceFile,
        table: RawTable,
        mappings: Sequence[ColumnMapping],
        options: RecordOptions = RecordOptions(),  # noqa: B008 - immutable default
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ImportPlan:
        """Interpret rows and match them against existing prospects (nothing is saved)."""
        if progress:
            progress(10, "Checking rows…")
        results = build_records(table.rows, mappings, options, row_numbers=table.row_numbers)
        if token:
            token.raise_if_cancelled()
        records = [r.record for r in results if r.record is not None and not r.has_errors]
        if progress:
            progress(40, "Looking for existing prospects…")
        with self._database.session() as session:
            index = OrganizationIndex(OrganizationRepository(session).keys())
            email_index = ContactRepository(session).email_index()
            imports = ImportRepository(session)
            known = imports.known_fingerprints({r.fingerprint for r in records})
            previous = [
                (job.started_at_utc, job.file_name)
                for job in imports.committed_with_hash(source.sha256)
            ]
            job_files = {
                job_id: job.file_name
                for job_id in {job for _, job in known.values()}
                if (job := imports.get(job_id)) is not None
            }
        groups = []
        grouped = group_records(records)
        for number, group_rows in enumerate(grouped):
            if token and number % 200 == 0:
                token.raise_if_cancelled()
            action, reason, target, candidates = _match(index, email_index, group_rows)
            known_targets = {known.get(r.fingerprint, (None, None))[0] for r in group_rows}
            if action is PlanAction.UPDATE and known_targets == {target}:
                job_id = known[group_rows[0].fingerprint][1]
                action = PlanAction.SKIP
                reason = f"Already imported from {job_files.get(job_id, 'an earlier file')}"
            target_key = index.get(target) if target else None
            target_name = target_key.name if target_key else None
            key = f"{number}"
            groups.append(
                ImportGroup(key, group_rows, action, reason, target, target_name, candidates)
            )
        if progress:
            progress(100, "Ready to review.")
        return ImportPlan(
            job_id=new_id(),
            source=source,
            sheet_name=table.sheet_name,
            mappings=list(mappings),
            options=options,
            table=table,
            results=results,
            groups=groups,
            previous_imports=previous,
        )

    def _run(
        self,
        plan: ImportPlan,
        *,
        dry_run: bool,
        token: CancelToken | None,
        progress: ProgressCallback | None,
    ) -> ImportOutcome:
        if plan.unresolved:
            raise ImportFailedError(
                f"{len(plan.unresolved)} prospect(s) still need a decision.",
                action="Choose Create new, Add to existing or Skip for each highlighted row.",
            )
        counts = ImportCounts(error_rows=len(plan.error_rows))
        issues: list[RowIssue] = []
        now = self._database.clock.now()
        try:
            with self._database.session() as session:
                imports = ImportRepository(session)
                imports.defer_foreign_keys()
                if imports.get(plan.job_id) is not None:
                    raise ImportFailedError(
                        "This import has already been saved.",
                        action="Open Import history to review or undo it.",
                    )
                job = imports.add(
                    ImportJob(
                        id=plan.job_id,
                        file_name=plan.source.name,
                        file_sha256=plan.source.sha256,
                        file_size_bytes=plan.source.size_bytes,
                        file_type=plan.source.kind.value,
                        sheet_name=plan.sheet_name,
                        status=STATUS_COMMITTED,
                        started_at_utc=now,
                        mapping={
                            "columns": [
                                {"header": m.header, "field": m.field.value if m.field else None}
                                for m in plan.mappings
                            ],
                            "date_order": plan.options.date_order.value,
                        },
                    )
                )
                ledger = ActivityLedger(session, self._actor_id, self._database.clock)
                ctx = _Context(session, job, ledger, counts, issues, plan.source.name)
                total = max(1, len(plan.groups))
                for number, group in enumerate(plan.groups, start=1):
                    if token is not None:
                        token.raise_if_cancelled()
                    _apply_group(ctx, group)
                    if progress is not None and (number % 25 == 0 or number == total):
                        progress(int(number * 100 / total), f"Saving {number:,} of {total:,}…")
                if token is not None:  # a cancel up to the moment of saving is honored
                    token.raise_if_cancelled()
                all_issues = plan.issues + issues
                counts.warnings = sum(1 for i in all_issues if i.severity is IssueSeverity.WARNING)
                job.created_count = counts.organizations_created
                job.updated_count = counts.organizations_updated
                job.skipped_count = counts.organizations_skipped
                job.error_count = counts.error_rows
                job.warning_count = counts.warnings
                job.error_summary = _error_summary(all_issues)
                # Flush first so every imported row's timestamp precedes the finish time,
                # which undo uses to recognize records edited after the import.
                session.flush()
                job.finished_at_utc = self._database.clock.now()
                ledger.record(
                    ActivityType.IMPORT_COMMITTED,
                    payload={
                        "import_job_id": job.id,
                        "file_name": job.file_name,
                        "created": counts.organizations_created,
                        "updated": counts.organizations_updated,
                        "skipped": counts.organizations_skipped,
                        "errors": counts.error_rows,
                    },
                    source=RecordSource.IMPORT,
                )
                if dry_run:
                    raise _DryRun
        except _DryRun:
            return ImportOutcome(plan.job_id, counts, plan.issues + issues, committed=False)
        except OperationCancelledError:
            logger.info("Import cancelled; nothing was saved")
            raise
        except TgSalesError:
            raise
        except Exception as exc:
            logger.exception("Import failed and was rolled back")
            raise ImportFailedError(
                "The import could not be saved. Nothing was changed.",
                action="Try again. If the problem continues, send the tg_sales log file to "
                "your support contact.",
                detail=repr(exc),
            ) from exc
        logger.info(
            "Import committed",
            extra={
                "context": {
                    "import_job_id": plan.job_id,
                    "created": counts.organizations_created,
                    "updated": counts.organizations_updated,
                    "skipped": counts.organizations_skipped,
                    "errors": counts.error_rows,
                }
            },
        )
        return ImportOutcome(plan.job_id, counts, plan.issues + issues, committed=True)

    def preview(
        self,
        plan: ImportPlan,
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ImportOutcome:
        """Exact result of importing ``plan``, computed in a rolled-back transaction."""
        return self._run(plan, dry_run=True, token=token, progress=progress)

    def commit(
        self,
        plan: ImportPlan,
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ImportOutcome:
        """Save the import atomically. Cancelling or any failure saves nothing."""
        return self._run(plan, dry_run=False, token=token, progress=progress)

    # -- history and undo -----------------------------------------------------------

    def history(self, limit: int = 100) -> list[ImportHistoryEntry]:
        with self._database.session() as session:
            return [
                ImportHistoryEntry(
                    id=job.id,
                    file_name=job.file_name,
                    file_type=job.file_type,
                    sheet_name=job.sheet_name,
                    started_at=job.started_at_utc,
                    status=job.status,
                    created=job.created_count,
                    updated=job.updated_count,
                    skipped=job.skipped_count,
                    errors=job.error_count,
                    warnings=job.warning_count,
                    undone_at=job.undone_at_utc,
                )
                for job in ImportRepository(session).recent(limit)
            ]

    def undo(self, job_id: str) -> UndoOutcome:
        """Reverse an import in one transaction.

        Records edited after the import, and prospects that gained other
        information since (opportunities, manual contacts, notes), are kept.
        """
        with self._database.session() as session:
            imports = ImportRepository(session)
            job = imports.get(job_id)
            if job is None or job.status != STATUS_COMMITTED:
                raise ImportFailedError(
                    "This import cannot be undone.",
                    action="It may already have been undone. Refresh Import history.",
                )
            finished = job.finished_at_utc or job.started_at_utc
            changes = imports.changes(job_id)
            created = {(c.entity_table, c.entity_id) for c in changes if c.action == ACTION_CREATED}
            kept_orgs = {
                c.entity_id
                for c in changes
                if c.entity_table == "organizations"
                and c.action == ACTION_CREATED
                and self._has_outside_dependents(session, c.entity_id, created, finished)
            }
            now = self._database.clock.now()
            reverted = kept = 0
            for change in reversed(changes):
                if change.action not in (ACTION_CREATED, ACTION_UPDATED):
                    continue
                model = _MODELS[change.entity_table]
                entity = session.get(model, change.entity_id)
                if entity is None or entity.deleted_at_utc is not None:
                    continue
                owner = getattr(entity, "organization_id", None)
                if (
                    change.entity_id in kept_orgs
                    or (change.action == ACTION_CREATED and owner in kept_orgs)
                    or entity.updated_at_utc > finished
                ):
                    kept += 1
                    continue
                if change.action == ACTION_CREATED:
                    entity.deleted_at_utc = now
                else:
                    for name, old in change.previous_values.items():
                        setattr(entity, name, self._restore_value(name, old))
                reverted += 1
            job.status = STATUS_UNDONE
            job.undone_at_utc = now
            ActivityLedger(session, self._actor_id, self._database.clock).record(
                ActivityType.IMPORT_UNDONE,
                payload={
                    "import_job_id": job.id,
                    "file_name": job.file_name,
                    "reverted": reverted,
                    "kept": kept,
                },
                source=RecordSource.IMPORT,
            )
        logger.info(
            "Import undone",
            extra={"context": {"import_job_id": job_id, "reverted": reverted, "kept": kept}},
        )
        return UndoOutcome(reverted, kept)

    @staticmethod
    def _has_outside_dependents(
        session: Session,
        organization_id: str,
        created: set[tuple[str, str]],
        finished: datetime,
    ) -> bool:
        opportunities = session.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(
                Opportunity.organization_id == organization_id,
                Opportunity.deleted_at_utc.is_(None),
            )
        )
        if opportunities:
            return True
        contacts = session.scalars(
            select(Contact.id).where(
                Contact.organization_id == organization_id, Contact.deleted_at_utc.is_(None)
            )
        )
        if any(("contacts", contact_id) not in created for contact_id in contacts):
            return True
        later_events = session.scalar(
            select(func.count())
            .select_from(Activity)
            .where(
                Activity.organization_id == organization_id,
                Activity.created_at_utc > finished,
            )
        )
        return bool(later_events)

    @staticmethod
    def _restore_value(name: str, value: object) -> object:
        if value is None:
            return None
        if name in _ENUM_FIELDS:
            return _ENUM_FIELDS[name](str(value))
        if name == "release_date" and isinstance(value, str):
            return date.fromisoformat(value)
        return value


def export_issues_csv(path: Path, plan: ImportPlan, issues: Sequence[RowIssue]) -> int:
    """Write row issues, with the original row values, to a spreadsheet-safe CSV."""
    cells_by_row = dict(zip(plan.table.row_numbers, plan.table.rows, strict=True))
    headers = ["Row", "Severity", "Column", "Problem", *plan.table.headers]
    order = {IssueSeverity.ERROR: 0, IssueSeverity.WARNING: 1}
    rows = [
        [
            issue.row_number,
            issue.severity.value,
            issue.column,
            issue.message,
            *(cells_by_row.get(issue.row_number) or []),
        ]
        for issue in sorted(issues, key=lambda i: (i.row_number, order[i.severity]))
    ]
    return write_csv(path, headers, rows)
