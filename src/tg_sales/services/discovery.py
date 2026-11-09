# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Discovery use cases: run a source, keep a review queue, save leads as prospects.

Results are stored in ``discovery_leads`` so the review queue survives
restarts. Each lead remembers when it was last checked; entries not refreshed
within the cache period (or served from cache because the source was
unreachable) are marked as outdated rather than shown as current. Saving a
lead to Prospects is always a manual action and checks for duplicates first.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from sqlalchemy.orm import Session

from tg_sales.cancellation import CancelToken
from tg_sales.db.database import Database
from tg_sales.db.models import (
    Contact,
    DiscoveryLead,
    DiscoveryRun,
    Game,
    GameOrganization,
    Organization,
)
from tg_sales.domain.discovery import (
    BusinessContact,
    ContactStatus,
    CrmState,
    DiscoveryFilters,
    DiscoveryParams,
    GameCandidate,
    GameType,
    LeadStatus,
    LeadView,
    SourceResult,
    contact_from_store,
    matches_filters,
    score,
)
from tg_sales.domain.enums import (
    ActivityType,
    GameRole,
    OrganizationType,
    RecordSource,
    ReleasePrecision,
)
from tg_sales.domain.enums import (
    ContactStatus as OutreachStatus,
)
from tg_sales.domain.normalization import normalize_email, normalize_name
from tg_sales.domain.prospects import DuplicateCandidate, MatchStrength, OrganizationIndex
from tg_sales.domain.time import format_utc, parse_utc, to_local
from tg_sales.errors import TgSalesError
from tg_sales.integrations.http import SourceError
from tg_sales.integrations.sources import GameSourceAdapter
from tg_sales.integrations.website_contacts import ContactSearch, WebsiteContactFinder
from tg_sales.repositories.discovery import DiscoveryRepository
from tg_sales.repositories.prospects import (
    ContactRepository,
    GameRepository,
    OrganizationRepository,
)
from tg_sales.services.ledger import ActivityLedger

logger = logging.getLogger(__name__)

OUTDATED_AFTER = timedelta(hours=24)
ProgressCallback = Callable[[int, str], None]


class DiscoveryError(TgSalesError):
    """A discovery action could not be completed."""


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    found: int
    new: int
    notes: tuple[str, ...]
    error: str | None = None  # user-facing message when the source failed

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class RunInfo:
    started_at: datetime
    finished_at: datetime | None
    status: str
    found: int
    error: str | None


# -- candidate (de)serialization for the stored review queue ----------------------------


def candidate_to_json(candidate: GameCandidate) -> dict[str, Any]:
    data = dataclasses.asdict(candidate)
    data["game_type"] = candidate.game_type.value
    data["release_precision"] = candidate.release_precision.value
    data["release_date"] = candidate.release_date.isoformat() if candidate.release_date else None
    data["fetched_at"] = format_utc(candidate.fetched_at)
    for key in ("developers", "publishers", "genres", "categories", "platforms", "languages"):
        data[key] = list(data[key])
    return data


def candidate_from_json(data: Mapping[str, Any]) -> GameCandidate:
    values = dict(data)
    values["game_type"] = GameType(values["game_type"])
    values["release_precision"] = ReleasePrecision(values["release_precision"])
    values["release_date"] = (
        date.fromisoformat(values["release_date"]) if values.get("release_date") else None
    )
    values["fetched_at"] = parse_utc(values["fetched_at"])
    for key in ("developers", "publishers", "genres", "categories", "platforms", "languages"):
        values[key] = tuple(values.get(key) or ())
    fields = {f.name for f in dataclasses.fields(GameCandidate)}
    return GameCandidate(**{k: v for k, v in values.items() if k in fields})


class DiscoveryService:
    def __init__(
        self,
        database: Database,
        actor_id: str | None,
        sources: Mapping[str, GameSourceAdapter],
        contact_finder: WebsiteContactFinder | None,
        *,
        zone: tzinfo | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._database = database
        self._actor_id = actor_id
        self._sources = dict(sources)
        self._finder = contact_finder
        self._zone = zone
        self._on_close = on_close

    def close(self) -> None:
        """Release network resources (call once the window has closed)."""
        if self._on_close is not None:
            self._on_close()
            self._on_close = None

    def source(self, name: str = "steam") -> GameSourceAdapter:
        try:
            return self._sources[name]
        except KeyError as exc:
            raise DiscoveryError(
                "This discovery source is not available.", action="Choose another source."
            ) from exc

    @property
    def source_names(self) -> list[str]:
        return list(self._sources)

    def today(self) -> date:
        return to_local(self._database.clock.now(), self._zone).date()

    # -- running ------------------------------------------------------------

    def run(
        self,
        params: DiscoveryParams,
        source: str = "steam",
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> RunOutcome:
        adapter = self.source(source)
        parameters = {
            "upcoming_days": params.window.upcoming_days,
            "recent_days": params.window.recent_days,
            "max_candidates": params.max_candidates,
        }
        return self._execute(source, parameters, lambda: adapter.discover(params, token, progress))

    def lookup(
        self,
        references: Sequence[str],
        source: str = "steam",
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> RunOutcome:
        adapter = self.source(source)
        recognized = [r for r in references if adapter.parse_reference(r)]
        if not recognized:
            raise DiscoveryError(
                "None of the entries are Steam store links or app ids.",
                action="Paste links like https://store.steampowered.com/app/413150/ or "
                "numbers like 413150.",
            )
        return self._execute(
            source,
            {"references": len(recognized)},
            lambda: adapter.lookup(recognized, token, progress),
        )

    def _execute(
        self, source: str, parameters: dict[str, Any], fetch: Callable[[], SourceResult]
    ) -> RunOutcome:
        clock = self._database.clock
        with self._database.session() as session:
            run = DiscoveryRepository(session).add_run(
                DiscoveryRun(
                    source=source,
                    parameters=parameters,
                    status="running",
                    started_at_utc=clock.now(),
                )
            )
            run_id = run.id
        try:
            result = fetch()
        except SourceError as exc:
            self._finish(run_id, "failed", 0, f"{exc.user_message} {exc.suggested_action}")
            logger.warning(
                "Discovery source failed",
                extra={"context": {"source": source, "detail": exc.detail}},
            )
            return RunOutcome(run_id, 0, 0, (), f"{exc.user_message} {exc.suggested_action}")
        except BaseException:
            self._finish(run_id, "cancelled", 0, "Stopped before finishing.")
            raise
        new = self._store(run_id, result.candidates)
        self._finish(run_id, "completed", len(result.candidates), "; ".join(result.notes) or None)
        return RunOutcome(run_id, len(result.candidates), new, tuple(result.notes))

    def _finish(self, run_id: str, status: str, count: int, error: str | None) -> None:
        with self._database.session() as session:
            run = DiscoveryRepository(session).get_run(run_id)
            if run is not None:
                run.status = status
                run.result_count = count
                run.error = error
                run.finished_at_utc = self._database.clock.now()

    def _store(self, run_id: str, candidates: Sequence[GameCandidate]) -> int:
        new = 0
        with self._database.session() as session:
            repo = DiscoveryRepository(session)
            for candidate in candidates:
                lead = repo.lead_by_external(candidate.source, candidate.external_id)
                store_contact = contact_from_store(candidate)
                if lead is None:
                    new += 1
                    repo.add_lead(
                        DiscoveryLead(
                            run_id=run_id,
                            source=candidate.source,
                            external_id=candidate.external_id,
                            title=candidate.title,
                            data=candidate_to_json(candidate),
                            release_date=candidate.release_date,
                            release_precision=candidate.release_precision,
                            status=LeadStatus.NEW.value,
                            contact_status=store_contact.status.value,
                            contact_email=store_contact.email,
                            contact_source_url=store_contact.source_url,
                            provenance_url=candidate.provenance_url,
                            last_checked_at_utc=candidate.fetched_at,
                        )
                    )
                    continue
                lead.run_id = run_id
                lead.title = candidate.title
                lead.data = candidate_to_json(candidate)
                lead.release_date = candidate.release_date
                lead.release_precision = candidate.release_precision
                lead.provenance_url = candidate.provenance_url
                lead.last_checked_at_utc = max(lead.last_checked_at_utc, candidate.fetched_at)
                # A contact the user found or verified is kept; otherwise follow the store page.
                if lead.contact_status == ContactStatus.NOT_FOUND.value or (
                    lead.contact_source_url == candidate.provenance_url
                    and lead.contact_status != ContactStatus.VERIFIED_SOURCE.value
                ):
                    lead.contact_status = store_contact.status.value
                    lead.contact_email = store_contact.email
                    lead.contact_source_url = store_contact.source_url
        return new

    def last_run(self, source: str = "steam") -> RunInfo | None:
        with self._database.session() as session:
            run = DiscoveryRepository(session).latest_run(source)
            if run is None:
                return None
            return RunInfo(
                run.started_at_utc, run.finished_at_utc, run.status, run.result_count, run.error
            )

    # -- review queue ---------------------------------------------------------

    def leads(
        self, params: DiscoveryParams, filters: DiscoveryFilters | None = None
    ) -> list[LeadView]:
        now = self._database.clock.now()
        today = self.today()
        with self._database.session() as session:
            repo = DiscoveryRepository(session)
            rows = repo.leads()
            in_crm = repo.games_in_crm(
                "steam", [r.external_id for r in rows if r.source == "steam"]
            )
            index = OrganizationIndex(OrganizationRepository(session).keys())
            views = [self._view(row, params, today, now, in_crm, index) for row in rows]
        if filters is not None:
            views = [v for v in views if matches_filters(v, filters)]
        return sorted(views, key=lambda v: (-v.score.total, v.candidate.title.casefold(), v.id))

    def _view(
        self,
        row: DiscoveryLead,
        params: DiscoveryParams,
        today: date,
        now: datetime,
        in_crm: Mapping[str, tuple[str, str]],
        index: OrganizationIndex,
    ) -> LeadView:
        candidate = candidate_from_json(row.data)
        contact = BusinessContact(
            row.contact_email,
            row.contact_source_url,
            _contact_label(row),
            ContactStatus(row.contact_status),
        )
        timing = params.window.classify(candidate, today)
        lead_score = score(candidate, timing, params.rules, contact.status)
        crm_state, org_id, org_name = CrmState.NOT_IN_CRM, None, None
        if row.external_id in in_crm and row.source == "steam":
            crm_state = CrmState.GAME_IN_CRM
            org_id, org_name = in_crm[row.external_id]
        elif candidate.primary_developer:
            matches = index.find(candidate.primary_developer, candidate.domain)
            strong = [m for m in matches if m.strength is MatchStrength.STRONG]
            if strong:
                crm_state, org_id, org_name = CrmState.STUDIO_IN_CRM, strong[0].id, strong[0].name
            elif matches:
                crm_state, org_id, org_name = (
                    CrmState.POSSIBLE_MATCH,
                    matches[0].id,
                    matches[0].name,
                )
        outdated = candidate.stale or now - row.last_checked_at_utc > OUTDATED_AFTER
        return LeadView(
            id=row.id,
            candidate=candidate,
            timing=timing,
            score=lead_score,
            contact=contact,
            status=LeadStatus(row.status),
            crm_state=crm_state,
            crm_organization_id=org_id,
            crm_organization_name=org_name,
            last_checked=row.last_checked_at_utc,
            outdated=outdated,
            organization_id=row.organization_id,
        )

    def _lead(self, session: Session, lead_id: str) -> DiscoveryLead:
        lead = DiscoveryRepository(session).lead(lead_id)
        if lead is None:
            raise DiscoveryError(
                "This discovery result no longer exists.", action="Refresh the list."
            )
        return lead

    def set_status(self, lead_id: str, status: LeadStatus) -> None:
        with self._database.session() as session:
            self._lead(session, lead_id).status = status.value

    # -- contacts -------------------------------------------------------------

    def find_website_contacts(
        self, lead_id: str, token: CancelToken | None = None
    ) -> ContactSearch:
        if self._finder is None:
            raise DiscoveryError("Website checks are not available.", action="Try again later.")
        with self._database.session() as session:
            candidate = candidate_from_json(self._lead(session, lead_id).data)
        if not candidate.website:
            raise DiscoveryError(
                "No official website is listed for this game.",
                action="Look up the studio yourself and add a contact after checking its source.",
            )
        return self._finder.find(candidate.website, token)

    def set_contact(self, lead_id: str, email: str, source_url: str) -> None:
        normalized = normalize_email(email)
        if normalized is None:
            raise DiscoveryError(
                f"“{email}” is not a valid email address.", action="Check the address."
            )
        with self._database.session() as session:
            lead = self._lead(session, lead_id)
            lead.contact_email = normalized
            lead.contact_source_url = source_url
            lead.contact_status = ContactStatus.NEEDS_VERIFICATION.value

    def mark_contact_verified(self, lead_id: str) -> None:
        with self._database.session() as session:
            lead = self._lead(session, lead_id)
            if lead.contact_email is None:
                raise DiscoveryError(
                    "There is no contact to verify.", action="Find a contact first."
                )
            lead.contact_status = ContactStatus.VERIFIED_SOURCE.value

    # -- saving ---------------------------------------------------------------

    def duplicates_for(self, lead_id: str) -> list[DuplicateCandidate]:
        with self._database.session() as session:
            candidate = candidate_from_json(self._lead(session, lead_id).data)
            index = OrganizationIndex(OrganizationRepository(session).keys())
        name = candidate.primary_developer or candidate.title
        return index.find(name, candidate.domain)

    def save_to_prospects(
        self,
        lead_id: str,
        *,
        existing_organization_id: str | None = None,
        include_contact: bool = True,
    ) -> str:
        """Create a prospect (or add the game to an existing one); return its id."""
        clock = self._database.clock
        with self._database.session() as session:
            lead = self._lead(session, lead_id)
            candidate = candidate_from_json(lead.data)
            organizations = OrganizationRepository(session)
            ledger = ActivityLedger(session, self._actor_id, clock)
            if existing_organization_id is not None:
                organization = organizations.get(existing_organization_id)
                if organization is None:
                    raise DiscoveryError(
                        "That prospect no longer exists.", action="Choose another one."
                    )
            else:
                name = candidate.primary_developer or candidate.title
                publishers = ", ".join(candidate.publishers) or "not listed"
                organization = organizations.add(
                    Organization(
                        name=name,
                        normalized_name=normalize_name(name),
                        website=candidate.website,
                        domain=candidate.domain,
                        company_type=OrganizationType.STUDIO,
                        source=RecordSource.DISCOVERY,
                        tags=[],
                        notes=(
                            f"Found by discovery ({candidate.source}): {candidate.title} "
                            f"({candidate.store_url}). Publisher(s): {publishers}."
                        ),
                    )
                )
                ledger.record(
                    ActivityType.ORGANIZATION_CREATED,
                    organization_id=organization.id,
                    payload={"name": name, "discovery_lead_id": lead.id},
                    source=RecordSource.DISCOVERY,
                )
            self._attach_game(session, organization.id, candidate)
            if include_contact and lead.contact_email:
                existing = ContactRepository(session).organizations_by_email([lead.contact_email])
                if organization.id not in existing:
                    ContactRepository(session).add(
                        Contact(
                            organization_id=organization.id,
                            business_email=lead.contact_email,
                            email_normalized=lead.contact_email,
                            social_urls={},
                            contact_status=OutreachStatus.UNKNOWN,
                            provenance=_contact_label(lead),
                            source_url=lead.contact_source_url,
                            source=RecordSource.DISCOVERY,
                        )
                    )
            lead.status = LeadStatus.SAVED.value
            lead.organization_id = organization.id
            return organization.id

    def _attach_game(
        self, session: Session, organization_id: str, candidate: GameCandidate
    ) -> None:
        games = GameRepository(session)
        game = DiscoveryRepository(session).game_by_store_id(
            candidate.source, candidate.external_id
        )
        if game is None:
            game = games.add(
                Game(
                    title=candidate.title,
                    platform=", ".join(p.capitalize() for p in candidate.platforms) or None,
                    store=candidate.source,
                    store_id=candidate.external_id,
                    store_url=candidate.store_url,
                    release_date=candidate.release_date,
                    release_precision=candidate.release_precision,
                    source=RecordSource.DISCOVERY,
                    discovered_at_utc=candidate.fetched_at,
                )
            )
        if games.find_link(game.id, organization_id) is None:
            games.link(
                GameOrganization(
                    game_id=game.id, organization_id=organization_id, role=GameRole.DEVELOPER
                )
            )


def _contact_label(lead: DiscoveryLead) -> str:
    if lead.contact_email is None:
        return "No public business contact found"
    if lead.contact_source_url and lead.contact_source_url == lead.provenance_url:
        return "Support email listed on the store page"
    return (
        f"Published on {lead.contact_source_url}" if lead.contact_source_url else "Entered manually"
    )
