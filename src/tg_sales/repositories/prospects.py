# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Organizations, contacts and games (prospect data)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Text, and_, cast, exists, func, literal, or_, select
from sqlalchemy.orm import Session

from tg_sales.db.models import (
    Activity,
    Contact,
    Game,
    GameOrganization,
    Opportunity,
    Organization,
    PipelineStage,
)
from tg_sales.domain.enums import StageOutcome
from tg_sales.domain.normalization import normalize_name
from tg_sales.domain.prospects import OrganizationKey, ProspectQuery

LIKE_ESCAPE = "\\"


def like_pattern(text: str) -> str:
    """``%text%`` with LIKE wildcards in ``text`` escaped."""
    escaped = text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _tag_filter(tag: str) -> ColumnElement[bool]:
    values = func.jsonb_array_elements_text(Organization.tags).table_valued("value")
    values = values.alias("tag_values")
    return exists(
        select(literal(1))
        .select_from(values)
        .where(func.lower(values.c.value) == tag.strip().lower())
    )


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, organization_id: str) -> Organization | None:
        organization = self._session.get(Organization, organization_id)
        return None if organization is None or organization.is_deleted else organization

    def get_many(self, ids: Collection[str]) -> list[Organization]:
        if not ids:
            return []
        return list(
            self._session.scalars(
                select(Organization).where(
                    Organization.id.in_(list(ids)), Organization.deleted_at_utc.is_(None)
                )
            )
        )

    def add(self, organization: Organization) -> Organization:
        self._session.add(organization)
        self._session.flush()
        return organization

    def candidate_keys(
        self, normalized_name: str, domain: str | None, words: list[str], limit: int = 300
    ) -> list[OrganizationKey]:
        """Organizations that could match a name/domain: same domain, or sharing a word."""
        matches: list[ColumnElement[bool]] = [
            Organization.normalized_name.like(like_pattern(normalized_name), escape=LIKE_ESCAPE)
        ]
        if domain:
            matches.append(Organization.domain == domain)
        matches += [
            Organization.normalized_name.like(like_pattern(word), escape=LIKE_ESCAPE)
            for word in words
        ]
        rows = self._session.execute(
            select(
                Organization.id,
                Organization.name,
                Organization.domain,
                Organization.archived_at_utc,
            )
            .where(Organization.deleted_at_utc.is_(None), or_(*matches))
            .limit(limit * max(1, len(words)))
        )
        return [
            OrganizationKey(org_id, name, found_domain, archived is not None)
            for org_id, name, found_domain, archived in rows
        ]

    def keys(self) -> list[OrganizationKey]:
        """Name and domain of every organization (archived included) for duplicate checks."""
        rows = self._session.execute(
            select(
                Organization.id,
                Organization.name,
                Organization.domain,
                Organization.archived_at_utc,
            ).where(Organization.deleted_at_utc.is_(None))
        )
        return [
            OrganizationKey(org_id, name, domain, archived is not None)
            for org_id, name, domain, archived in rows
        ]

    def _search_conditions(self, query: ProspectQuery) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [Organization.deleted_at_utc.is_(None)]
        if not query.include_archived:
            conditions.append(Organization.archived_at_utc.is_(None))
        if query.company_type is not None:
            conditions.append(Organization.company_type == query.company_type)
        if query.tag:
            conditions.append(_tag_filter(query.tag))
        text = query.text.strip()
        if text:
            normalized_text = normalize_name(text)
            raw = like_pattern(text.lower())
            contact_match = exists(
                select(literal(1)).where(
                    Contact.organization_id == Organization.id,
                    Contact.deleted_at_utc.is_(None),
                    or_(
                        func.lower(Contact.name).like(raw, escape=LIKE_ESCAPE),
                        Contact.email_normalized.like(raw, escape=LIKE_ESCAPE),
                        func.lower(Contact.role_title).like(raw, escape=LIKE_ESCAPE),
                    ),
                )
            )
            game_match = exists(
                select(literal(1))
                .select_from(GameOrganization)
                .join(Game, Game.id == GameOrganization.game_id)
                .where(
                    GameOrganization.organization_id == Organization.id,
                    GameOrganization.deleted_at_utc.is_(None),
                    Game.deleted_at_utc.is_(None),
                    func.lower(Game.title).like(raw, escape=LIKE_ESCAPE),
                )
            )
            matches: list[ColumnElement[bool]] = [
                func.lower(Organization.name).like(raw, escape=LIKE_ESCAPE),
                Organization.domain.like(raw, escape=LIKE_ESCAPE),
                func.lower(Organization.location).like(raw, escape=LIKE_ESCAPE),
                func.lower(Organization.country).like(raw, escape=LIKE_ESCAPE),
                func.lower(cast(Organization.tags, Text)).like(raw, escape=LIKE_ESCAPE),
                contact_match,
                game_match,
            ]
            if normalized_text:  # punctuation-only searches have no normalized form
                pattern = like_pattern(normalized_text)
                matches.append(Organization.normalized_name.like(pattern, escape=LIKE_ESCAPE))
            conditions.append(or_(*matches))
        return conditions

    def search(self, query: ProspectQuery) -> tuple[list[Organization], int]:
        """Matching organizations (a page of ``query.limit`` by name) and the total count."""
        conditions = self._search_conditions(query)
        total = self._session.scalar(
            select(func.count()).select_from(Organization).where(*conditions)
        )
        rows = self._session.scalars(
            select(Organization)
            .where(*conditions)
            .order_by(Organization.normalized_name, Organization.id)
            .limit(query.limit)
            .offset(query.offset)
        ).all()
        return list(rows), int(total or 0)

    def ids_matching(self, query: ProspectQuery) -> list[str]:
        conditions = self._search_conditions(query)
        return list(
            self._session.scalars(
                select(Organization.id)
                .where(*conditions)
                .order_by(Organization.normalized_name, Organization.id)
            )
        )

    def all_tags(self) -> list[str]:
        values = func.jsonb_array_elements_text(Organization.tags).table_valued("value")
        values = values.alias("tag_values")
        rows = self._session.scalars(
            select(values.c.value)
            .select_from(Organization)
            .join(values, literal(True))
            .where(Organization.deleted_at_utc.is_(None))
            .distinct()
        )
        unique: dict[str, str] = {}
        for tag in rows:
            if isinstance(tag, str) and tag.strip():
                unique.setdefault(tag.casefold(), tag)
        return sorted(unique.values(), key=str.casefold)

    def contact_counts(self, ids: Collection[str]) -> dict[str, int]:
        rows = self._session.execute(
            select(Contact.organization_id, func.count())
            .where(
                Contact.organization_id.in_(list(ids)),
                Contact.deleted_at_utc.is_(None),
                Contact.archived_at_utc.is_(None),
            )
            .group_by(Contact.organization_id)
        )
        return {org_id: int(count) for org_id, count in rows}

    def game_counts(self, ids: Collection[str]) -> dict[str, int]:
        rows = self._session.execute(
            select(GameOrganization.organization_id, func.count(func.distinct(Game.id)))
            .join(Game, Game.id == GameOrganization.game_id)
            .where(
                GameOrganization.organization_id.in_(list(ids)),
                GameOrganization.deleted_at_utc.is_(None),
                Game.deleted_at_utc.is_(None),
            )
            .group_by(GameOrganization.organization_id)
        )
        return {org_id: int(count) for org_id, count in rows}

    def open_opportunity_stats(
        self, ids: Collection[str]
    ) -> dict[str, tuple[int, datetime | None]]:
        rows = self._session.execute(
            select(
                Opportunity.organization_id,
                func.count(),
                func.min(Opportunity.next_action_at_utc),
            )
            .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
            .where(
                Opportunity.organization_id.in_(list(ids)),
                Opportunity.deleted_at_utc.is_(None),
                PipelineStage.outcome == StageOutcome.OPEN,
            )
            .group_by(Opportunity.organization_id)
        )
        # MIN() keeps the column type, so values arrive as aware datetimes.
        return {org_id: (int(count), next_action) for org_id, count, next_action in rows}

    def opportunities(self, organization_id: str) -> list[tuple[Opportunity, PipelineStage]]:
        rows = self._session.execute(
            select(Opportunity, PipelineStage)
            .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
            .where(
                Opportunity.organization_id == organization_id,
                Opportunity.deleted_at_utc.is_(None),
            )
            .order_by(Opportunity.created_at_utc, Opportunity.id)
        )
        return [(opportunity, stage) for opportunity, stage in rows]

    def timeline(self, organization_id: str, limit: int = 200) -> list[Activity]:
        """Most recent events for an organization, newest first."""
        return list(
            self._session.scalars(
                select(Activity)
                .where(Activity.organization_id == organization_id)
                .order_by(
                    Activity.occurred_at_utc.desc(),
                    Activity.created_at_utc.desc(),
                    Activity.id.desc(),
                )
                .limit(limit)
            )
        )

    def corrected_event_ids(self, event_ids: Collection[str]) -> dict[str, dict[str, object]]:
        """Latest correction payload for each of ``event_ids`` that has one."""
        if not event_ids:
            return {}
        rows = self._session.execute(
            select(Activity.corrects_event_id, Activity.payload)
            .where(
                Activity.corrects_event_id.in_(list(event_ids)),
                Activity.deleted_at_utc.is_(None),
            )
            .order_by(Activity.created_at_utc, Activity.id)
        )
        return {str(event_id): dict(payload) for event_id, payload in rows}


class ContactRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, contact_id: str) -> Contact | None:
        contact = self._session.get(Contact, contact_id)
        return None if contact is None or contact.is_deleted else contact

    def add(self, contact: Contact) -> Contact:
        self._session.add(contact)
        self._session.flush()
        return contact

    def for_organization(
        self, organization_id: str, *, include_archived: bool = True
    ) -> list[Contact]:
        conditions = [Contact.organization_id == organization_id, Contact.deleted_at_utc.is_(None)]
        if not include_archived:
            conditions.append(Contact.archived_at_utc.is_(None))
        return list(
            self._session.scalars(
                select(Contact)
                .where(*conditions)
                .order_by(Contact.archived_at_utc.is_not(None), Contact.created_at_utc, Contact.id)
            )
        )

    def for_organizations(self, ids: Collection[str]) -> list[Contact]:
        if not ids:
            return []
        return list(
            self._session.scalars(
                select(Contact)
                .where(
                    Contact.organization_id.in_(list(ids)),
                    Contact.deleted_at_utc.is_(None),
                    Contact.archived_at_utc.is_(None),
                )
                .order_by(Contact.created_at_utc, Contact.id)
            )
        )

    def organizations_by_email(self, emails: Collection[str]) -> dict[str, str]:
        """Map each organization id to one of ``emails`` held by its contacts."""
        if not emails:
            return {}
        rows = self._session.execute(
            select(Contact.organization_id, Contact.email_normalized).where(
                Contact.email_normalized.in_(list(emails)), Contact.deleted_at_utc.is_(None)
            )
        )
        return {org_id: str(email) for org_id, email in rows}

    def email_index(self) -> dict[str, str]:
        """Map every known normalized email to its organization id."""
        rows = self._session.execute(
            select(Contact.email_normalized, Contact.organization_id).where(
                Contact.email_normalized.is_not(None), Contact.deleted_at_utc.is_(None)
            )
        )
        return {str(email): org_id for email, org_id in rows}


class GameRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, game_id: str) -> Game | None:
        game = self._session.get(Game, game_id)
        return None if game is None or game.is_deleted else game

    def add(self, game: Game) -> Game:
        self._session.add(game)
        self._session.flush()
        return game

    def link(self, link: GameOrganization) -> GameOrganization:
        self._session.add(link)
        self._session.flush()
        return link

    def find_link(self, game_id: str, organization_id: str) -> GameOrganization | None:
        return self._session.scalar(
            select(GameOrganization).where(
                GameOrganization.game_id == game_id,
                GameOrganization.organization_id == organization_id,
                GameOrganization.deleted_at_utc.is_(None),
            )
        )

    def find_by_store_url(self, store_url: str) -> Game | None:
        return self._session.scalar(
            select(Game)
            .where(Game.store_url == store_url, Game.deleted_at_utc.is_(None))
            .order_by(Game.created_at_utc, Game.id)
            .limit(1)
        )

    def for_organization(self, organization_id: str) -> list[tuple[Game, GameOrganization]]:
        rows = self._session.execute(
            select(Game, GameOrganization)
            .join(GameOrganization, GameOrganization.game_id == Game.id)
            .where(
                GameOrganization.organization_id == organization_id,
                GameOrganization.deleted_at_utc.is_(None),
                Game.deleted_at_utc.is_(None),
            )
            .order_by(Game.release_date.is_(None), Game.release_date, Game.title, Game.id)
        )
        return [(game, link) for game, link in rows]

    def titles_for_organizations(self, ids: Sequence[str]) -> dict[str, list[str]]:
        if not ids:
            return {}
        rows = self._session.execute(
            select(GameOrganization.organization_id, Game.title)
            .join(Game, Game.id == GameOrganization.game_id)
            .where(
                and_(
                    GameOrganization.organization_id.in_(list(ids)),
                    GameOrganization.deleted_at_utc.is_(None),
                    Game.deleted_at_utc.is_(None),
                )
            )
            .order_by(Game.title)
        )
        result: dict[str, list[str]] = {}
        for org_id, title in rows:
            result.setdefault(org_id, []).append(title)
        return result
