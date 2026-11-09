# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Prospect management: organizations with their contacts, games and history.

Every change is written in one transaction together with an activity event,
so the organization timeline shows who changed what and when. Records are
archived rather than deleted; archiving is reversible.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tg_sales.db.database import Database
from tg_sales.db.models import Contact, Game, GameOrganization, Organization
from tg_sales.domain.custom_fields import (
    CustomFieldInfo,
    InvalidValueError,
    RecordType,
    clean_values,
    display_value,
    merged,
)
from tg_sales.domain.enums import ActivityType, ContactStatus, RecordSource
from tg_sales.domain.normalization import (
    core_name,
    domain_from_url,
    exact_url,
    identifying_domain,
    normalize_email,
    normalize_name,
    normalize_url,
)
from tg_sales.domain.prospects import (
    ContactDraft,
    ContactInfo,
    CustomValue,
    DuplicateCandidate,
    GameDraft,
    GameInfo,
    LinkInfo,
    OpportunityInfo,
    OrganizationDetail,
    OrganizationDraft,
    OrganizationIndex,
    OrganizationKey,
    OrganizationSummary,
    ProspectQuery,
    SearchResult,
    TimelineEntry,
    merge_tags,
    significant_words,
)
from tg_sales.domain.time import format_utc
from tg_sales.errors import TgSalesError
from tg_sales.repositories.imports import ImportRepository
from tg_sales.repositories.prospects import (
    ContactRepository,
    GameRepository,
    OrganizationRepository,
)
from tg_sales.services.csv_export import write_csv
from tg_sales.services.custom_fields import fields_in
from tg_sales.services.ledger import ActivityLedger
from tg_sales.services.timeline import summarize

MAX_NAME_LENGTH = 200
MAX_NOTE_LENGTH = 20_000

EXPORT_HEADERS = (
    "Name",
    "Website",
    "Type",
    "Location",
    "Country",
    "Tags",
    "Contacts",
    "Contact emails",
    "Games",
    "Notes",
    "Review date",
    "Qualification source URL",
    "Archived",
    "Created (UTC)",
    "Updated (UTC)",
)

_STATUS_LABELS = {
    ContactStatus.UNKNOWN: "unknown",
    ContactStatus.NOT_CONTACTED: "not contacted",
    ContactStatus.ATTEMPTED: "contacted",
    ContactStatus.RESPONDED: "responded",
}


class ProspectValidationError(TgSalesError):
    """Entered values cannot be saved."""


class ProspectNotFoundError(TgSalesError):
    """The record no longer exists (for example, it was removed on another computer)."""


def _not_found() -> ProspectNotFoundError:
    return ProspectNotFoundError(
        "This record no longer exists.", action="Refresh the prospect list and try again."
    )


def _clean(text: str | None, *, limit: int = MAX_NOTE_LENGTH) -> str | None:
    if text is None:
        return None
    cleaned = text.replace("\x00", "").strip()
    return cleaned[:limit] if cleaned else None


def _validated_website(website: str | None) -> tuple[str | None, str | None]:
    text = _clean(website)
    if text is None:
        return None, None
    url = normalize_url(text)
    if url is None:
        raise ProspectValidationError(
            f"“{text}” is not a valid website address.",
            action="Enter a web address such as https://studio.example, or leave it empty.",
        )
    return url, domain_from_url(url)


def _validated_source_url(url: str | None) -> str | None:
    text = _clean(url)
    if text is None:
        return None
    exact = exact_url(text)
    if exact is None:
        raise ProspectValidationError(
            f"“{text}” is not a valid web address.",
            action="Enter the page where this prospect was found or qualified "
            "(https://…), or leave it empty.",
        )
    return exact


def _custom_changes(
    session: Session, record_type: RecordType, values: Mapping[str, object]
) -> tuple[dict[str, object | None], dict[str, CustomFieldInfo]]:
    """Validated custom-field changes for a form, and the active fields by key."""
    fields = {f.key: f for f in fields_in(session, record_type, include_archived=False)}
    if not values:
        return {}, fields
    try:
        return clean_values(fields, values), fields
    except InvalidValueError as exc:
        raise ProspectValidationError(
            str(exc), action="Correct the value or leave it empty."
        ) from exc


def _custom_view(
    fields: Sequence[CustomFieldInfo], values: Mapping[str, object]
) -> tuple[CustomValue, ...]:
    return tuple(
        CustomValue(f.key, f.label, f.field_type.value, values.get(f.key))
        for f in fields
        if not f.archived
    )


def _validated_name(name: str) -> str:
    cleaned = _clean(name, limit=MAX_NAME_LENGTH)
    if cleaned is None or not normalize_name(cleaned):
        raise ProspectValidationError(
            "A prospect needs a name.", action="Enter the studio or company name."
        )
    return cleaned


def _validated_contact(draft: ContactDraft) -> dict[str, Any]:
    email_text = _clean(draft.email)
    email = normalize_email(email_text) if email_text else None
    if email_text and email is None:
        raise ProspectValidationError(
            f"“{email_text}” is not a valid email address.",
            action="Correct the email address or leave it empty.",
        )
    socials: dict[str, str] = {}
    for network, raw in draft.social_urls.items():
        text = _clean(raw)
        if not text:
            continue
        url = normalize_url(text)
        if url is None:
            raise ProspectValidationError(
                f"“{text}” is not a valid web address.",
                action="Enter a full profile link such as https://www.linkedin.com/in/…",
            )
        socials[network] = url
    source_url_text = _clean(draft.source_url)
    source_url = normalize_url(source_url_text) if source_url_text else None
    if source_url_text and source_url is None:
        raise ProspectValidationError(
            f"“{source_url_text}” is not a valid web address.",
            action="Enter the page where this contact's details were published, or leave it empty.",
        )
    name = _clean(draft.name, limit=MAX_NAME_LENGTH)
    if name is None and email is None and not socials:
        raise ProspectValidationError(
            "A contact needs a name, an email address or a social profile link.",
            action="Fill in at least one of them.",
        )
    return {
        "name": name,
        "role_title": _clean(draft.role_title, limit=MAX_NAME_LENGTH),
        "business_email": email,
        "email_normalized": email,
        "social_urls": socials,
        "contact_status": draft.status,
        "notes": _clean(draft.notes),
        "provenance": _clean(draft.provenance),
        "source_url": source_url,
    }


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "value") and not isinstance(value, str | int | float | bool):
        return value.value
    return value


def _apply_changes(entity: Any, values: dict[str, Any]) -> dict[str, dict[str, object]]:
    """Set changed attributes; return ``{field: {"old", "new"}}`` for the ledger."""
    changes: dict[str, dict[str, object]] = {}
    for name, new in values.items():
        old = getattr(entity, name)
        if isinstance(old, list):
            old = tuple(old)
        compare_new = tuple(new) if isinstance(new, list | tuple) else new
        if old != compare_new:
            changes[name] = {"old": _json_value(old), "new": _json_value(compare_new)}
            setattr(entity, name, list(new) if isinstance(new, tuple) else new)
    return changes


class ProspectService:
    """Use cases for the Prospects section. Each call is one transaction."""

    def __init__(
        self,
        database: Database,
        actor_id: str | None,
        stage_names: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self._database = database
        self._actor_id = actor_id
        self._stage_names = stage_names

    def _ledger(self, session: Session) -> ActivityLedger:
        return ActivityLedger(session, self._actor_id, self._database.clock)

    # -- queries ------------------------------------------------------------

    def search(self, query: ProspectQuery) -> SearchResult:
        with self._database.session() as session:
            repo = OrganizationRepository(session)
            organizations, total = repo.search(query)
            ids = [o.id for o in organizations]
            contacts = repo.contact_counts(ids)
            games = repo.game_counts(ids)
            opportunities = repo.open_opportunity_stats(ids)
            rows = tuple(
                OrganizationSummary(
                    id=o.id,
                    name=o.name,
                    domain=o.domain,
                    website=o.website,
                    company_type=o.company_type,
                    location=o.location,
                    country=o.country,
                    tags=tuple(o.tags),
                    contact_count=contacts.get(o.id, 0),
                    game_count=games.get(o.id, 0),
                    open_opportunity_count=opportunities.get(o.id, (0, None))[0],
                    next_follow_up=opportunities.get(o.id, (0, None))[1],
                    updated_at=o.updated_at_utc,
                    archived=o.archived_at_utc is not None,
                )
                for o in organizations
            )
            return SearchResult(rows, total)

    def count(self, *, include_archived: bool = True) -> int:
        query = ProspectQuery(include_archived=include_archived, limit=0)
        with self._database.session() as session:
            return OrganizationRepository(session).search(query)[1]

    def all_tags(self) -> list[str]:
        with self._database.session() as session:
            return OrganizationRepository(session).all_tags()

    def find_duplicates(
        self,
        draft: OrganizationDraft,
        emails: Iterable[str] = (),
        *,
        exclude_id: str | None = None,
    ) -> list[DuplicateCandidate]:
        """Existing organizations that may be the same as ``draft``."""
        website = normalize_url(draft.website) if draft.website else None
        domain = domain_from_url(website)
        normalized_emails = {e for e in (normalize_email(x) for x in emails) if e}
        with self._database.session() as session:
            repo = OrganizationRepository(session)
            email_matches = ContactRepository(session).organizations_by_email(normalized_emails)
            keys = repo.candidate_keys(
                core_name(draft.name) or normalize_name(draft.name),
                identifying_domain(domain),
                significant_words(draft.name),
            )
            known = {k.id for k in keys}
            keys += [
                OrganizationKey(o.id, o.name, o.domain, o.archived_at_utc is not None)
                for o in repo.get_many([i for i in email_matches if i not in known])
            ]
        return OrganizationIndex(keys).find(
            draft.name, domain, email_matches=email_matches, exclude_id=exclude_id
        )

    def get_detail(self, organization_id: str) -> OrganizationDetail | None:
        with self._database.session() as session:
            repo = OrganizationRepository(session)
            organization = repo.get(organization_id)
            if organization is None:
                return None
            contacts = ContactRepository(session).for_organization(organization_id)
            games = GameRepository(session).for_organization(organization_id)
            opportunities = repo.opportunities(organization_id)
            activities = repo.timeline(organization_id)
            corrections = repo.corrected_event_ids([a.id for a in activities])
            created_by = ImportRepository(session).created_by(organization_id)
            stage_names = {stage.id: stage.name for _, stage in opportunities}
            if self._stage_names is not None:
                stage_names = self._stage_names() | stage_names

            prospect_fields = fields_in(session, RecordType.PROSPECT, include_archived=False)
            contact_fields = fields_in(session, RecordType.CONTACT, include_archived=False)
            links: list[LinkInfo] = []
            if organization.website:
                links.append(LinkInfo("Website", organization.website))
            if organization.qualification_source_url:
                links.append(
                    LinkInfo("Qualification source", organization.qualification_source_url)
                )
            for contact in contacts:
                who = contact.name or contact.business_email or "Contact"
                for network, url in sorted(contact.social_urls.items()):
                    links.append(LinkInfo(f"{who} · {network.capitalize()}", str(url)))
            for game, _ in games:
                if game.store_url:
                    links.append(LinkInfo(f"{game.title} · store page", game.store_url))

            source_detail = None
            if created_by is not None:
                source_detail = f"Imported from {created_by.file_name}"
            timeline = []
            for activity in activities:
                if activity.type is ActivityType.CORRECTION:
                    continue
                correction = corrections.get(activity.id)
                voided = bool(correction and correction.get("void"))
                timeline.append(
                    TimelineEntry(
                        activity.id,
                        activity.type,
                        activity.occurred_at_utc,
                        summarize(activity, stage_names),
                        voided,
                    )
                )
            return OrganizationDetail(
                id=organization.id,
                name=organization.name,
                website=organization.website,
                domain=organization.domain,
                company_type=organization.company_type,
                location=organization.location,
                country=organization.country,
                tags=tuple(organization.tags),
                notes=organization.notes,
                source=organization.source,
                source_detail=source_detail,
                created_at=organization.created_at_utc,
                updated_at=organization.updated_at_utc,
                archived=organization.archived_at_utc is not None,
                contacts=tuple(
                    ContactInfo(
                        id=c.id,
                        name=c.name,
                        role_title=c.role_title,
                        email=c.business_email,
                        social_urls=dict(c.social_urls),
                        status=c.contact_status,
                        notes=c.notes,
                        provenance=c.provenance,
                        source_url=c.source_url,
                        source=c.source,
                        archived=c.archived_at_utc is not None,
                        custom_fields=dict(c.custom_fields or {}),
                    )
                    for c in contacts
                ),
                games=tuple(
                    GameInfo(
                        id=game.id,
                        title=game.title,
                        role=link.role,
                        platform=game.platform,
                        store_url=game.store_url,
                        release_date=game.release_date,
                        release_precision=game.release_precision,
                    )
                    for game, link in games
                ),
                opportunities=tuple(
                    OpportunityInfo(
                        id=o.id,
                        title=o.title,
                        product_lane=o.product_lane,
                        stage_name=stage.name,
                        next_action_at=o.next_action_at_utc,
                        next_action_note=o.next_action_note,
                        closed=stage.is_terminal,
                    )
                    for o, stage in opportunities
                ),
                timeline=tuple(timeline),
                links=tuple(links),
                reviewed_on=organization.reviewed_on,
                qualification_source_url=organization.qualification_source_url,
                custom_fields=_custom_view(prospect_fields, organization.custom_fields or {}),
                contact_fields=_custom_view(contact_fields, {}),
            )

    # -- organizations ------------------------------------------------------

    def create(self, draft: OrganizationDraft, contacts: Sequence[ContactDraft] = ()) -> str:
        """Create an organization (and optional contacts); return its id.

        Callers check :meth:`find_duplicates` first and let the user decide;
        similarly named organizations are allowed.
        """
        name = _validated_name(draft.name)
        website, domain = _validated_website(draft.website)
        source_url = _validated_source_url(draft.qualification_source_url)
        contact_values = [_validated_contact(c) for c in contacts]
        with self._database.session() as session:
            custom, _ = _custom_changes(session, RecordType.PROSPECT, draft.custom_fields)
            contact_custom = [
                _custom_changes(session, RecordType.CONTACT, c.custom_fields)[0] for c in contacts
            ]
            organization = OrganizationRepository(session).add(
                Organization(
                    name=name,
                    normalized_name=normalize_name(name),
                    website=website,
                    domain=domain,
                    location=_clean(draft.location, limit=MAX_NAME_LENGTH),
                    country=_clean(draft.country, limit=MAX_NAME_LENGTH),
                    company_type=draft.company_type,
                    source=RecordSource.MANUAL,
                    tags=list(merge_tags((), draft.tags)),
                    notes=_clean(draft.notes),
                    reviewed_on=draft.reviewed_on,
                    qualification_source_url=source_url,
                    custom_fields=merged({}, custom),
                )
            )
            self._ledger(session).record(
                ActivityType.ORGANIZATION_CREATED,
                organization_id=organization.id,
                payload={"name": name},
            )
            repo = ContactRepository(session)
            for values, extra in zip(contact_values, contact_custom, strict=True):
                repo.add(
                    Contact(
                        organization_id=organization.id, custom_fields=merged({}, extra), **values
                    )
                )
            return organization.id

    def update(self, organization_id: str, draft: OrganizationDraft) -> bool:
        """Save edited values; return True if anything changed."""
        name = _validated_name(draft.name)
        website, domain = _validated_website(draft.website)
        source_url = _validated_source_url(draft.qualification_source_url)
        with self._database.session() as session:
            organization = OrganizationRepository(session).get(organization_id)
            if organization is None:
                raise _not_found()
            custom, _ = _custom_changes(session, RecordType.PROSPECT, draft.custom_fields)
            values: dict[str, Any] = {
                "name": name,
                "normalized_name": normalize_name(name),
                "website": website,
                "domain": domain,
                "location": _clean(draft.location, limit=MAX_NAME_LENGTH),
                "country": _clean(draft.country, limit=MAX_NAME_LENGTH),
                "company_type": draft.company_type,
                "tags": merge_tags((), draft.tags),
                "notes": _clean(draft.notes),
                "reviewed_on": draft.reviewed_on,
                "qualification_source_url": source_url,
            }
            for kept in draft.keep:
                values.pop(kept, None)
            if custom:
                values["custom_fields"] = merged(organization.custom_fields or {}, custom)
            changes = _apply_changes(organization, values)
            changes.pop("normalized_name", None)
            changes.pop("domain", None)
            if changes:
                self._record_change(
                    session, "organizations", organization.id, organization.id, changes
                )
            return bool(changes)

    def _record_change(
        self,
        session: Session,
        entity: str,
        entity_id: str,
        organization_id: str,
        changes: dict[str, dict[str, object]],
        contact_id: str | None = None,
    ) -> None:
        self._ledger(session).record(
            ActivityType.FIELD_CHANGE,
            organization_id=organization_id,
            contact_id=contact_id,
            payload={"entity": entity, "entity_id": entity_id, "changes": changes},
        )

    def set_archived(self, organization_ids: Iterable[str], archived: bool) -> int:
        """Archive or restore organizations; return how many changed."""
        changed = 0
        with self._database.session() as session:
            now = self._database.clock.now()
            for organization in OrganizationRepository(session).get_many(set(organization_ids)):
                if (organization.archived_at_utc is not None) == archived:
                    continue
                changes = _apply_changes(
                    organization, {"archived_at_utc": now if archived else None}
                )
                self._record_change(
                    session, "organizations", organization.id, organization.id, changes
                )
                changed += 1
        return changed

    def add_tag(self, organization_ids: Iterable[str], tag: str) -> int:
        cleaned = _clean(tag, limit=60)
        if cleaned is None:
            raise ProspectValidationError("Enter a tag name.", action="Type a short label.")
        return self._edit_tags(organization_ids, lambda tags: merge_tags(tags, [cleaned]))

    def remove_tag(self, organization_ids: Iterable[str], tag: str) -> int:
        folded = tag.strip().casefold()
        return self._edit_tags(
            organization_ids, lambda tags: tuple(t for t in tags if t.casefold() != folded)
        )

    def _edit_tags(
        self, organization_ids: Iterable[str], edit: Callable[[tuple[str, ...]], tuple[str, ...]]
    ) -> int:
        changed = 0
        with self._database.session() as session:
            for organization in OrganizationRepository(session).get_many(set(organization_ids)):
                changes = _apply_changes(organization, {"tags": edit(tuple(organization.tags))})
                if changes:
                    self._record_change(
                        session, "organizations", organization.id, organization.id, changes
                    )
                    changed += 1
        return changed

    def add_note(self, organization_id: str, text: str) -> None:
        cleaned = _clean(text)
        if cleaned is None:
            raise ProspectValidationError("The note is empty.", action="Type a note first.")
        with self._database.session() as session:
            if OrganizationRepository(session).get(organization_id) is None:
                raise _not_found()
            self._ledger(session).record(
                ActivityType.NOTE, organization_id=organization_id, payload={"text": cleaned}
            )

    # -- contacts -----------------------------------------------------------

    def add_contact(self, organization_id: str, draft: ContactDraft) -> str:
        values = _validated_contact(draft)
        with self._database.session() as session:
            if OrganizationRepository(session).get(organization_id) is None:
                raise _not_found()
            custom, _ = _custom_changes(session, RecordType.CONTACT, draft.custom_fields)
            contact = ContactRepository(session).add(
                Contact(
                    organization_id=organization_id,
                    source=RecordSource.MANUAL,
                    custom_fields=merged({}, custom),
                    **values,
                )
            )
            self._record_change(
                session,
                "contacts",
                contact.id,
                organization_id,
                {"created": {"old": None, "new": values["name"] or values["business_email"]}},
                contact_id=contact.id,
            )
            return contact.id

    def update_contact(self, contact_id: str, draft: ContactDraft) -> bool:
        values = _validated_contact(draft)
        for kept in draft.keep:  # not sent by the form: keep the stored values
            values.pop(kept, None)
        with self._database.session() as session:
            contact = ContactRepository(session).get(contact_id)
            if contact is None:
                raise _not_found()
            custom, _ = _custom_changes(session, RecordType.CONTACT, draft.custom_fields)
            if custom:
                values["custom_fields"] = merged(contact.custom_fields or {}, custom)
            changes = _apply_changes(contact, values)
            changes.pop("email_normalized", None)
            if changes:
                self._record_change(
                    session, "contacts", contact.id, contact.organization_id, changes, contact.id
                )
            return bool(changes)

    def set_contact_archived(self, contact_id: str, archived: bool) -> bool:
        with self._database.session() as session:
            contact = ContactRepository(session).get(contact_id)
            if contact is None:
                raise _not_found()
            if (contact.archived_at_utc is not None) == archived:
                return False
            now = self._database.clock.now()
            changes = _apply_changes(contact, {"archived_at_utc": now if archived else None})
            self._record_change(
                session, "contacts", contact.id, contact.organization_id, changes, contact.id
            )
            return True

    def contact_email_in_use(
        self, email: str, *, exclude_contact_id: str | None = None
    ) -> list[str]:
        """Names of organizations that already have a contact with ``email``."""
        normalized = normalize_email(email)
        if normalized is None:
            return []
        with self._database.session() as session:
            matches = ContactRepository(session).organizations_by_email([normalized])
            if exclude_contact_id is not None:
                excluded = ContactRepository(session).get(exclude_contact_id)
                if excluded is not None and excluded.email_normalized == normalized:
                    matches.pop(excluded.organization_id, None)
            organizations = OrganizationRepository(session).get_many(matches.keys())
            return sorted(o.name for o in organizations)

    # -- games --------------------------------------------------------------

    def add_game(self, organization_id: str, draft: GameDraft) -> str:
        title = _clean(draft.title, limit=MAX_NAME_LENGTH)
        if title is None:
            raise ProspectValidationError("A game needs a title.", action="Enter the game title.")
        store_text = _clean(draft.store_url)
        store_url = normalize_url(store_text) if store_text else None
        if store_text and store_url is None:
            raise ProspectValidationError(
                f"“{store_text}” is not a valid web address.",
                action="Enter the store page link (https://…) or leave it empty.",
            )
        with self._database.session() as session:
            if OrganizationRepository(session).get(organization_id) is None:
                raise _not_found()
            games = GameRepository(session)
            game = games.find_by_store_url(store_url) if store_url else None
            if game is None:
                game = games.add(
                    Game(
                        title=title,
                        platform=_clean(draft.platform, limit=MAX_NAME_LENGTH),
                        store_url=store_url,
                        release_date=draft.release_date,
                        release_precision=draft.release_precision,
                        source=RecordSource.MANUAL,
                    )
                )
            existing = games.find_link(game.id, organization_id)
            if existing is None or existing.role is not draft.role:
                games.link(
                    GameOrganization(
                        game_id=game.id, organization_id=organization_id, role=draft.role
                    )
                )
            self._record_change(
                session,
                "games",
                game.id,
                organization_id,
                {"game": {"old": None, "new": title}},
            )
            return game.id

    # -- export -------------------------------------------------------------

    def export_csv(self, path: Path, organization_ids: Sequence[str]) -> int:
        """Export organizations (in the given order) to a spreadsheet-safe CSV file."""
        with self._database.session() as session:
            by_id = {o.id: o for o in OrganizationRepository(session).get_many(organization_ids)}
            contacts: dict[str, list[Contact]] = {}
            for contact in ContactRepository(session).for_organizations(list(by_id)):
                contacts.setdefault(contact.organization_id, []).append(contact)
            games = GameRepository(session).titles_for_organizations(list(by_id))
            prospect_fields = fields_in(session, RecordType.PROSPECT, include_archived=False)
            rows = []
            for org_id in organization_ids:
                o = by_id.get(org_id)
                if o is None:
                    continue
                people = contacts.get(o.id, [])
                rows.append(
                    [
                        o.name,
                        o.website,
                        o.company_type.value,
                        o.location,
                        o.country,
                        "; ".join(o.tags),
                        "; ".join(
                            f"{c.name or '(no name)'}"
                            + (f" ({c.role_title})" if c.role_title else "")
                            + f" [{_STATUS_LABELS[c.contact_status]}]"
                            for c in people
                        ),
                        "; ".join(c.business_email for c in people if c.business_email),
                        "; ".join(games.get(o.id, [])),
                        o.notes,
                        o.reviewed_on.isoformat() if o.reviewed_on else None,
                        o.qualification_source_url,
                        "yes" if o.archived_at_utc else "no",
                        format_utc(o.created_at_utc),
                        format_utc(o.updated_at_utc),
                        *(
                            display_value(f.field_type, (o.custom_fields or {}).get(f.key))
                            for f in prospect_fields
                        ),
                    ]
                )
        headers = (*EXPORT_HEADERS, *(f.label for f in prospect_fields))
        return write_csv(path, headers, rows)

    def ids_for_query(self, query: ProspectQuery) -> list[str]:
        with self._database.session() as session:
            return OrganizationRepository(session).ids_matching(replace(query, limit=0))
