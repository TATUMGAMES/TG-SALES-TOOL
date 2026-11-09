# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Pipeline history reconstructed from immutable stage events.

The stage an opportunity was in at any past moment is derived from its
``opportunity_created`` and ``stage_change`` events, never from its current
state. Events are ordered deterministically by when they happened, then when
they were recorded, then by event id.

Corrections never modify an event. A correction event can void an earlier event
or move it to a different time; when several corrections target the same event,
the most recently recorded one wins.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True)
class StageEvent:
    """An event placing an opportunity in a stage."""

    event_id: str
    opportunity_id: str
    stage_id: str
    occurred_at: datetime
    recorded_at: datetime


@dataclass(frozen=True)
class EventCorrection:
    """A correction to an earlier event."""

    event_id: str
    corrects_event_id: str
    recorded_at: datetime
    void: bool = False
    occurred_at: datetime | None = None


def apply_corrections(
    events: Iterable[StageEvent], corrections: Iterable[EventCorrection]
) -> list[StageEvent]:
    """Return events with the latest correction for each one applied."""
    latest: dict[str, EventCorrection] = {}
    for correction in sorted(corrections, key=lambda c: (c.recorded_at, c.event_id)):
        latest[correction.corrects_event_id] = correction
    result = []
    for event in events:
        fix = latest.get(event.event_id)
        if fix is None:
            result.append(event)
        elif fix.void:
            continue
        elif fix.occurred_at is not None:
            result.append(replace(event, occurred_at=fix.occurred_at))
        else:
            result.append(event)
    return result


def _order(event: StageEvent) -> tuple[datetime, datetime, str]:
    return (event.occurred_at, event.recorded_at, event.event_id)


def stages_as_of(events: Iterable[StageEvent], as_of: datetime) -> dict[str, str]:
    """Map each opportunity to its stage at ``as_of`` (inclusive).

    Opportunities with no stage event at or before ``as_of`` did not exist yet
    and are omitted.
    """
    current: dict[str, StageEvent] = {}
    for event in events:
        if event.occurred_at > as_of:
            continue
        previous = current.get(event.opportunity_id)
        if previous is None or _order(event) > _order(previous):
            current[event.opportunity_id] = event
    return {opportunity: event.stage_id for opportunity, event in current.items()}


def stage_counts(stage_by_opportunity: dict[str, str]) -> Counter[str]:
    """Count opportunities per stage."""
    return Counter(stage_by_opportunity.values())
