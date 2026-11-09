# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Append-only activity ledger.

Every event records who did what, when it happened (``occurred_at_utc``, which
may be in the past for backdated or imported events) and when it was recorded
(``created_at_utc``). Events are never edited: a correction is a new event that
references the original and keeps a copy of the original values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from tg_sales.db.models import Activity
from tg_sales.domain.enums import ActivityType, RecordSource
from tg_sales.domain.time import Clock, ensure_utc, format_utc
from tg_sales.repositories.activities import ActivityRepository


class ActivityLedger:
    def __init__(self, session: Session, actor_id: str | None, clock: Clock) -> None:
        self._activities = ActivityRepository(session)
        self._actor_id = actor_id
        self._clock = clock

    def record(
        self,
        activity_type: ActivityType,
        *,
        occurred_at: datetime | None = None,
        organization_id: str | None = None,
        contact_id: str | None = None,
        opportunity_id: str | None = None,
        game_id: str | None = None,
        payload: dict[str, Any] | None = None,
        source: RecordSource = RecordSource.MANUAL,
        corrects_event_id: str | None = None,
        flush: bool = True,
    ) -> Activity:
        """Append one event and return it.

        ``flush=False`` defers the insert to the end of the transaction, which
        is much faster when recording many events at once (imports).
        """
        occurred = ensure_utc(occurred_at) if occurred_at is not None else self._clock.now()
        return self._activities.add(
            Activity(
                type=activity_type,
                occurred_at_utc=occurred,
                actor_id=self._actor_id,
                organization_id=organization_id,
                contact_id=contact_id,
                opportunity_id=opportunity_id,
                game_id=game_id,
                payload=dict(payload or {}),
                source=source,
                corrects_event_id=corrects_event_id,
            ),
            flush=flush,
        )

    def correct(
        self,
        event_id: str,
        *,
        reason: str,
        void: bool = False,
        occurred_at: datetime | None = None,
    ) -> Activity:
        """Void an event, or move it to a different time, without modifying it."""
        original = self._activities.get(event_id)
        if original is None:
            raise ValueError(f"event {event_id} does not exist")
        if original.type is ActivityType.CORRECTION:
            raise ValueError("a correction cannot itself be corrected; correct the original")
        if not void and occurred_at is None:
            raise ValueError("a correction must void the event or give a new time")
        return self.record(
            ActivityType.CORRECTION,
            organization_id=original.organization_id,
            contact_id=original.contact_id,
            opportunity_id=original.opportunity_id,
            game_id=original.game_id,
            corrects_event_id=original.id,
            payload={
                "void": void,
                "occurred_at_utc": None if occurred_at is None else format_utc(occurred_at),
                "reason": reason,
                "original": {
                    "type": original.type.value,
                    "occurred_at_utc": format_utc(original.occurred_at_utc),
                    "payload": original.payload,
                },
            },
        )
