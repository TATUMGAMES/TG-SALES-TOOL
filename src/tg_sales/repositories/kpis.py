# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Read-only queries feeding the KPI calculations (column-wise for speed)."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

from tg_sales.db.models import (
    Activity,
    Actor,
    Contact,
    Game,
    GameOrganization,
    Opportunity,
    Organization,
    PipelineStage,
    Task,
)
from tg_sales.domain.enums import ActivityType, StageOutcome
from tg_sales.domain.kpi import (
    STAGE_TYPES,
    ContactRow,
    Correction,
    LedgerEvent,
    OpportunityRow,
    OrganizationRow,
    StageRow,
)
from tg_sales.domain.time import parse_utc

ACTIVITY_KPI_TYPES = frozenset(
    {
        ActivityType.CONTACTED,
        ActivityType.EMAIL,
        ActivityType.LINKEDIN_INVITE,
        ActivityType.LINKEDIN_MESSAGE,
        ActivityType.PHONE_CALL,
        ActivityType.REPLY,
        ActivityType.TECHNICAL_HANDOFF,
        ActivityType.PROPOSAL,
    }
)


def _outcome(value: object) -> StageOutcome | None:
    try:
        return StageOutcome(str(value)) if value else None
    except ValueError:
        return None


class KpiRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def version_token(self) -> tuple[object, ...]:
        """Changes whenever data that KPIs depend on changes (cheap indexed queries)."""
        token: list[object] = []
        for model in (Organization, Contact, Opportunity, PipelineStage, Task, Game):
            token.append(self._session.scalar(select(func.max(model.updated_at_utc))))
            token.append(self._session.scalar(select(func.count()).select_from(model)))
        token.append(self._session.scalar(select(func.max(Activity.created_at_utc))))
        token.append(self._session.scalar(select(func.count()).select_from(Activity)))
        return tuple(token)

    def has_data(self) -> bool:
        return bool(
            self._session.scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.deleted_at_utc.is_(None))
            )
        )

    def organizations_created(self, start: datetime, end: datetime) -> list[OrganizationRow]:
        rows = list(
            self._session.execute(
                select(
                    Organization.id,
                    Organization.name,
                    Organization.source,
                    Organization.created_at_utc,
                    Organization.deleted_at_utc,
                ).where(Organization.created_at_utc >= start, Organization.created_at_utc < end)
            )
        )
        creators: dict[str, str | None] = {}
        ids = [row[0] for row in rows]
        for offset in range(0, len(ids), 900):  # stay under SQLite's variable limit
            chunk = ids[offset : offset + 900]
            for org_id, actor_id in self._session.execute(
                select(Activity.organization_id, Activity.actor_id)
                .where(
                    Activity.type == ActivityType.ORGANIZATION_CREATED,
                    Activity.organization_id.in_(chunk),
                )
                .order_by(Activity.created_at_utc.desc())
            ):
                creators[str(org_id)] = actor_id  # the earliest event wins (read last)
        return [OrganizationRow(*row, creators.get(row[0])) for row in rows]

    def contacts_created(self, start: datetime, end: datetime) -> list[ContactRow]:
        rows = self._session.execute(
            select(
                Contact.id,
                Contact.organization_id,
                func.coalesce(Contact.name, Contact.business_email, "Contact"),
                Contact.created_at_utc,
                Contact.deleted_at_utc,
            ).where(Contact.created_at_utc >= start, Contact.created_at_utc < end)
        )
        return [ContactRow(*row) for row in rows]

    def opportunities(self) -> dict[str, OpportunityRow]:
        rows = self._session.execute(
            select(
                Opportunity.id,
                Opportunity.organization_id,
                Opportunity.title,
                Opportunity.product_lane,
                Opportunity.owner_actor_id,
                Opportunity.deleted_at_utc,
                Opportunity.next_action_at_utc,
                Opportunity.next_action_note,
                PipelineStage.outcome == StageOutcome.OPEN,
                Opportunity.outcome_reason,
            ).join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
        )
        return {row[0]: OpportunityRow(*row[:8], bool(row[8]), row[9]) for row in rows}

    def stages(self) -> dict[str, StageRow]:
        rows = self._session.execute(
            select(
                PipelineStage.id,
                PipelineStage.name,
                PipelineStage.sort_order,
                PipelineStage.outcome,
            ).where(PipelineStage.deleted_at_utc.is_(None))
        )
        return {row[0]: StageRow(*row) for row in rows}

    def corrections(self) -> list[Correction]:
        rows = self._session.execute(
            select(
                Activity.corrects_event_id,
                Activity.created_at_utc,
                Activity.id,
                Activity.payload["void"].as_boolean(),
                Activity.payload["occurred_at_utc"].as_string(),
            ).where(
                Activity.type == ActivityType.CORRECTION, Activity.corrects_event_id.is_not(None)
            )
        )
        return [
            Correction(
                str(target),
                recorded,
                event_id,
                bool(void),
                parse_utc(moved) if isinstance(moved, str) else None,
            )
            for target, recorded, event_id, void, moved in rows
        ]

    def _events(
        self,
        types: Collection[ActivityType],
        start: datetime | None,
        end: datetime,
        also_include: Collection[str],
        *,
        with_stages: bool,
    ) -> list[LedgerEvent]:
        stage_id: Any = (
            case(
                (
                    Activity.type == ActivityType.STAGE_CHANGE,
                    Activity.payload["to_stage_id"].as_string(),
                ),
                else_=Activity.payload["stage_id"].as_string(),
            )
            if with_stages
            else literal(None)
        )
        outcome: Any = Activity.payload["to_outcome"].as_string() if with_stages else literal(None)
        window = Activity.occurred_at_utc < end
        if start is not None:
            window = window & (Activity.occurred_at_utc >= start)
        query = select(
            Activity.id,
            Activity.type,
            Activity.occurred_at_utc,
            Activity.created_at_utc,
            Activity.actor_id,
            Activity.organization_id,
            Activity.contact_id,
            Activity.opportunity_id,
            stage_id,
            outcome,
        ).where(Activity.type.in_(list(types)), or_(window, Activity.id.in_(list(also_include))))
        return [
            LedgerEvent(
                event_id,
                kind,
                occurred,
                recorded,
                actor,
                organization,
                contact,
                opportunity,
                stage if isinstance(stage, str) else None,
                _outcome(outcome),
            )
            for (
                event_id,
                kind,
                occurred,
                recorded,
                actor,
                organization,
                contact,
                opportunity,
                stage,
                outcome,
            ) in self._session.execute(query)
        ]

    def stage_events(self, end: datetime, also_include: Collection[str]) -> list[LedgerEvent]:
        """Stage-placing events that happened before ``end`` (plus re-timed ones)."""
        return self._events(STAGE_TYPES, None, end, also_include, with_stages=True)

    def activity_events(
        self, start: datetime, end: datetime, also_include: Collection[str]
    ) -> list[LedgerEvent]:
        """Outreach, reply, handoff and proposal events in ``[start, end)`` (plus re-timed ones)."""
        return self._events(ACTIVITY_KPI_TYPES, start, end, also_include, with_stages=False)

    def organization_names(self, ids: Collection[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        id_list = list(ids)
        for offset in range(0, len(id_list), 900):  # stay under SQLite's variable limit
            chunk = id_list[offset : offset + 900]
            for org_id, name in self._session.execute(
                select(Organization.id, Organization.name).where(Organization.id.in_(chunk))
            ):
                result[org_id] = name
        return result

    def contact_names(self, ids: Collection[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        id_list = list(ids)
        for offset in range(0, len(id_list), 900):
            chunk = id_list[offset : offset + 900]
            for contact_id, name in self._session.execute(
                select(
                    Contact.id, func.coalesce(Contact.name, Contact.business_email, "Contact")
                ).where(Contact.id.in_(chunk))
            ):
                result[contact_id] = name
        return result

    def actors(self) -> list[tuple[str, str]]:
        return [
            (actor_id, name)
            for actor_id, name in self._session.execute(
                select(Actor.id, Actor.display_name)
                .where(Actor.deleted_at_utc.is_(None))
                .order_by(func.lower(Actor.display_name))
            )
        ]

    def recent_activities(self, start: datetime, end: datetime, limit: int) -> list[Activity]:
        return list(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.occurred_at_utc >= start,
                    Activity.occurred_at_utc < end,
                    Activity.type.not_in([ActivityType.CORRECTION, ActivityType.FIELD_CHANGE]),
                )
                .order_by(
                    Activity.occurred_at_utc.desc(),
                    Activity.created_at_utc.desc(),
                    Activity.id.desc(),
                )
                .limit(limit)
            )
        )

    def release_dates(self, first: date, last: date) -> list[tuple[date, str, str]]:
        """(release date, game title, organization name) for prospects' games in a range."""
        rows = self._session.execute(
            select(Game.release_date, Game.title, Organization.name)
            .join(GameOrganization, GameOrganization.game_id == Game.id)
            .join(Organization, Organization.id == GameOrganization.organization_id)
            .where(
                Game.deleted_at_utc.is_(None),
                GameOrganization.deleted_at_utc.is_(None),
                Organization.deleted_at_utc.is_(None),
                Game.release_date >= first,
                Game.release_date <= last,
            )
            .distinct()
            .order_by(Game.release_date)
        )
        return [(day, title, org) for day, title, org in rows if day is not None]
