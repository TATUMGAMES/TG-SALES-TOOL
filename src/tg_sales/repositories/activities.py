# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Immutable activity events.

Payload conventions:

* ``opportunity_created``: ``{"stage_id", "product_lane"}``
* ``stage_change``: ``{"from_stage_id", "to_stage_id", "to_outcome", "reason"}``
* ``correction``: ``{"void", "occurred_at_utc", "reason", "original"}``
* ``field_change``: ``{"entity": table, "entity_id", "changes": {field: {"old", "new"}}}``
  (``entity``/``entity_id`` are present for changes to prospects and contacts)
* ``note``: ``{"text"}``
* ``organization_created``: ``{"name"}``
* ``import_committed``: ``{"import_job_id", "file_name", "created", "updated",
  "skipped", "errors"}``
* ``import_undone``: ``{"import_job_id", "file_name", "reverted", "kept"}``
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from tg_sales.db.models import Activity, Opportunity
from tg_sales.domain.enums import STAGE_ACTIVITY_TYPES, ActivityType
from tg_sales.domain.ids import new_id
from tg_sales.domain.pipeline import EventCorrection, StageEvent
from tg_sales.domain.time import parse_utc


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, event_id: str) -> Activity | None:
        return self._session.get(Activity, event_id)

    def add(self, activity: Activity, *, flush: bool = True) -> Activity:
        if not flush and not activity.id:
            activity.id = new_id()
        self._session.add(activity)
        if flush:
            self._session.flush()
        return activity

    def for_opportunity(self, opportunity_id: str) -> Sequence[Activity]:
        """Timeline for an opportunity in deterministic chronological order."""
        return self._session.scalars(
            select(Activity)
            .where(Activity.opportunity_id == opportunity_id)
            .order_by(Activity.occurred_at_utc, Activity.created_at_utc, Activity.id)
        ).all()

    def stage_events(
        self,
        lane: str | None = None,
        *,
        occurred_until: datetime | None = None,
        also_include: Collection[str] = (),
    ) -> list[StageEvent]:
        """Stage-placing events, read column-wise for speed on large ledgers.

        ``occurred_until`` limits events to those that happened at or before a
        moment; ``also_include`` adds specific events regardless of time (used
        for events whose time a correction may have moved).
        """
        stage_id = case(
            (
                Activity.type == ActivityType.STAGE_CHANGE,
                Activity.payload["to_stage_id"].as_string(),
            ),
            else_=Activity.payload["stage_id"].as_string(),
        )
        query = select(
            Activity.id,
            Activity.opportunity_id,
            stage_id,
            Activity.occurred_at_utc,
            Activity.created_at_utc,
        ).where(Activity.type.in_(STAGE_ACTIVITY_TYPES), Activity.opportunity_id.is_not(None))
        if occurred_until is not None:
            window = Activity.occurred_at_utc <= occurred_until
            query = query.where(or_(window, Activity.id.in_(list(also_include))))
        if lane is not None:
            query = query.join(Opportunity, Opportunity.id == Activity.opportunity_id).where(
                Opportunity.product_lane == lane
            )
        return [
            StageEvent(
                event_id=event_id,
                opportunity_id=opportunity_id,
                stage_id=stage,
                occurred_at=occurred,
                recorded_at=recorded,
            )
            for event_id, opportunity_id, stage, occurred, recorded in self._session.execute(query)
            if isinstance(stage, str)
        ]

    def corrections(self) -> list[EventCorrection]:
        query = select(Activity).where(
            Activity.type == ActivityType.CORRECTION, Activity.corrects_event_id.is_not(None)
        )
        result = []
        for activity in self._session.scalars(query):
            occurred = activity.payload.get("occurred_at_utc")
            result.append(
                EventCorrection(
                    event_id=activity.id,
                    corrects_event_id=str(activity.corrects_event_id),
                    recorded_at=activity.created_at_utc,
                    void=bool(activity.payload.get("void", False)),
                    occurred_at=parse_utc(occurred) if isinstance(occurred, str) else None,
                )
            )
        return result
