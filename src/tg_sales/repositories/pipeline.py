# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Queries for the pipeline board, opportunity details, tasks and reminders."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, datetime

from sqlalchemy import Row, func, select
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

# Events that do not count as "activity" on a card (bookkeeping only).
_NOT_ACTIVITY = (ActivityType.CORRECTION, ActivityType.FIELD_CHANGE)


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def stage_counts(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Opportunity.stage_id, func.count())
            .join(Organization, Organization.id == Opportunity.organization_id)
            .where(Opportunity.deleted_at_utc.is_(None), Organization.deleted_at_utc.is_(None))
            .group_by(Opportunity.stage_id)
        )
        return {stage_id: int(count) for stage_id, count in rows}

    def opportunities_in_stage(self, stage_id: str) -> list[Opportunity]:
        return list(
            self._session.scalars(
                select(Opportunity).where(
                    Opportunity.stage_id == stage_id, Opportunity.deleted_at_utc.is_(None)
                )
            )
        )

    def board_rows(
        self, lane: str | None, opportunity_id: str | None = None
    ) -> Sequence[Row[Opportunity, str, str | None, bool]]:
        """Live opportunities with organization name, owner name and closed flag."""
        query = (
            select(
                Opportunity,
                Organization.name,
                Actor.display_name,
                PipelineStage.outcome != StageOutcome.OPEN,
            )
            .join(Organization, Organization.id == Opportunity.organization_id)
            .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
            .outerjoin(Actor, Actor.id == Opportunity.owner_actor_id)
            .where(Opportunity.deleted_at_utc.is_(None), Organization.deleted_at_utc.is_(None))
            .order_by(
                Opportunity.next_action_at_utc.is_(None),
                Opportunity.next_action_at_utc,
                Organization.normalized_name,
                Opportunity.id,
            )
        )
        if lane is not None:
            query = query.where(Opportunity.product_lane == lane)
        if opportunity_id is not None:
            query = query.where(Opportunity.id == opportunity_id)
        return self._session.execute(query).all()

    def last_activity(self, opportunity_ids: Collection[str]) -> dict[str, datetime]:
        if not opportunity_ids:
            return {}
        rows = self._session.execute(
            select(Activity.opportunity_id, func.max(Activity.occurred_at_utc))
            .where(
                Activity.opportunity_id.in_(list(opportunity_ids)),
                Activity.type.not_in(_NOT_ACTIVITY),
            )
            .group_by(Activity.opportunity_id)
        )
        return {str(opp_id): when for opp_id, when in rows if when is not None}

    def release_dates(self, organization_ids: Collection[str], today: date) -> dict[str, date]:
        """Next upcoming game release per organization (or the latest past one)."""
        if not organization_ids:
            return {}
        rows = self._session.execute(
            select(GameOrganization.organization_id, Game.release_date)
            .join(Game, Game.id == GameOrganization.game_id)
            .where(
                GameOrganization.organization_id.in_(list(organization_ids)),
                GameOrganization.deleted_at_utc.is_(None),
                Game.deleted_at_utc.is_(None),
                Game.release_date.is_not(None),
            )
        )
        upcoming: dict[str, date] = {}
        past: dict[str, date] = {}
        for org_id, released in rows:
            if released is None:
                continue
            if released >= today:
                if org_id not in upcoming or released < upcoming[org_id]:
                    upcoming[org_id] = released
            elif org_id not in past or released > past[org_id]:
                past[org_id] = released
        return past | upcoming

    def actors(self) -> list[Actor]:
        return list(
            self._session.scalars(
                select(Actor)
                .where(Actor.deleted_at_utc.is_(None))
                .order_by(func.lower(Actor.display_name), Actor.id)
            )
        )

    def contacts(self, organization_id: str) -> list[Contact]:
        return list(
            self._session.scalars(
                select(Contact)
                .where(
                    Contact.organization_id == organization_id,
                    Contact.deleted_at_utc.is_(None),
                    Contact.archived_at_utc.is_(None),
                )
                .order_by(Contact.created_at_utc, Contact.id)
            )
        )

    def opportunity_activities(self, opportunity_id: str, limit: int = 300) -> list[Activity]:
        return list(
            self._session.scalars(
                select(Activity)
                .where(Activity.opportunity_id == opportunity_id)
                .order_by(
                    Activity.occurred_at_utc.desc(),
                    Activity.created_at_utc.desc(),
                    Activity.id.desc(),
                )
                .limit(limit)
            )
        )

    def voided_event_ids(self, event_ids: Collection[str]) -> set[str]:
        if not event_ids:
            return set()
        rows = self._session.execute(
            select(Activity.corrects_event_id, Activity.payload)
            .where(Activity.corrects_event_id.in_(list(event_ids)))
            .order_by(Activity.created_at_utc, Activity.id)
        )
        latest: dict[str, bool] = {}
        for event_id, payload in rows:
            latest[str(event_id)] = bool(payload.get("void"))
        return {event_id for event_id, void in latest.items() if void}

    # -- tasks --------------------------------------------------------------

    def add_task(self, task: Task) -> Task:
        self._session.add(task)
        self._session.flush()
        return task

    def get_task(self, task_id: str) -> Task | None:
        task = self._session.get(Task, task_id)
        return None if task is None or task.is_deleted else task

    def tasks_for(self, opportunity_id: str) -> list[Task]:
        return list(
            self._session.scalars(
                select(Task)
                .where(Task.opportunity_id == opportunity_id, Task.deleted_at_utc.is_(None))
                .order_by(
                    Task.completed_at_utc.is_not(None),
                    Task.due_at_utc.is_(None),
                    Task.due_at_utc,
                    Task.created_at_utc,
                    Task.id,
                )
            )
        )

    def open_tasks_due(self, until: datetime) -> Sequence[Row[Task, str | None, str | None]]:
        """Open tasks due at or before ``until`` with organization name and opportunity title."""
        return self._session.execute(
            select(Task, Organization.name, Opportunity.title)
            .outerjoin(Opportunity, Opportunity.id == Task.opportunity_id)
            .outerjoin(Organization, Organization.id == Task.organization_id)
            .where(
                Task.deleted_at_utc.is_(None),
                Task.completed_at_utc.is_(None),
                Task.due_at_utc.is_not(None),
                Task.due_at_utc <= until,
            )
            .order_by(Task.due_at_utc, Task.id)
        ).all()

    def next_actions_due(self, until: datetime) -> Sequence[Row[Opportunity, str]]:
        """Open opportunities whose next action is due at or before ``until``."""
        return self._session.execute(
            select(Opportunity, Organization.name)
            .join(Organization, Organization.id == Opportunity.organization_id)
            .join(PipelineStage, PipelineStage.id == Opportunity.stage_id)
            .where(
                Opportunity.deleted_at_utc.is_(None),
                Organization.deleted_at_utc.is_(None),
                PipelineStage.outcome == StageOutcome.OPEN,
                Opportunity.next_action_at_utc.is_not(None),
                Opportunity.next_action_at_utc <= until,
            )
            .order_by(Opportunity.next_action_at_utc, Opportunity.id)
        ).all()

    def organization_choices(self, text: str, limit: int = 50) -> list[tuple[str, str]]:
        """(id, name) of active organizations whose name contains ``text``."""
        query = (
            select(Organization.id, Organization.name)
            .where(Organization.deleted_at_utc.is_(None), Organization.archived_at_utc.is_(None))
            .order_by(Organization.normalized_name, Organization.id)
            .limit(limit)
        )
        cleaned = text.strip().lower()
        if cleaned:
            escaped = cleaned.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            query = query.where(func.lower(Organization.name).like(f"%{escaped}%", escape="\\"))
        return [(org_id, name) for org_id, name in self._session.execute(query)]
