# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Managing sales lanes: create, rename, recolor, reorder, archive, move records, delete.

Records are never lost because of a lane change:

* Renaming changes only the display name; records refer to the permanent key.
* Archiving hides a lane from new opportunities and filters' defaults, but its
  opportunities, stages and history stay exactly as they are (and stay
  visible on the board and in reports).
* Moving records reassigns every opportunity (and every stage limited to the
  lane) to another lane in one transaction, with an activity event per
  opportunity so the timeline shows what happened.
* Deleting is only possible for a lane that no opportunity or stage uses. It
  is a soft delete (a tombstone, like every record), so it syncs and can be
  undone by creating a lane with the same name again.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tg_sales.db.database import Database
from tg_sales.db.models import Opportunity, PipelineStage, SalesLane
from tg_sales.domain.enums import ActivityType
from tg_sales.domain.ids import SHARED_RECORD_CREATED_AT, SYSTEM_DEVICE_ID
from tg_sales.domain.lanes import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    PRESETS,
    LaneInfo,
    key_from_name,
    label_for_key,
    lane_id,
    normalize_color,
)
from tg_sales.errors import TgSalesError
from tg_sales.services.ledger import ActivityLedger


class LaneError(TgSalesError):
    """A lane change cannot be made."""


@dataclass(frozen=True)
class LaneDraft:
    name: str
    description: str | None = None
    color: str | None = None
    technical_handoff: bool = False


@dataclass(frozen=True)
class MoveOutcome:
    opportunities: int
    stages: int


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
        raise LaneError(
            f"A lane needs a name of 1 to {MAX_NAME_LENGTH} characters.",
            action="Enter a short name such as “Consulting”.",
        )
    return cleaned


def _clean_draft(draft: LaneDraft) -> LaneDraft:
    description = (draft.description or "").strip() or None
    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        raise LaneError(
            "The description is too long.",
            action=f"Keep it under {MAX_DESCRIPTION_LENGTH} characters.",
        )
    try:
        color = normalize_color(draft.color)
    except ValueError as exc:
        raise LaneError(
            "That color is not valid.", action="Choose one of the colors, or enter #rrggbb."
        ) from exc
    return LaneDraft(_clean_name(draft.name), description, color, draft.technical_handoff)


class LaneService:
    def __init__(self, database: Database, actor_id: str | None) -> None:
        self._database = database
        self._actor_id = actor_id

    # -- reading ----------------------------------------------------------------

    def list(self, *, include_archived: bool = True) -> list[LaneInfo]:
        with self._database.session() as session:
            return lanes_in(session, include_archived=include_archived)

    def names(self) -> dict[str, str]:
        """Display name of every lane key, including archived lanes."""
        with self._database.session() as session:
            return lane_names(session)

    def get(self, key: str) -> LaneInfo | None:
        return next((lane for lane in self.list() if lane.key == key), None)

    # -- changing ---------------------------------------------------------------

    def create(self, draft: LaneDraft) -> LaneInfo:
        clean = _clean_draft(draft)
        with self._database.session() as session:
            _ensure_unique_name(session, clean.name, exclude_key=None)
            base = key_from_name(clean.name)
            key, suffix = base, 2
            while True:
                existing = session.get(SalesLane, lane_id(key))
                if existing is None or existing.deleted_at_utc is not None:
                    break
                key = f"{base[: 32 - len(str(suffix)) - 1]}_{suffix}"
                suffix += 1
            order = (_max_sort_order(session) or 0) + 10
            if existing is not None:  # a deleted lane with this key: bring it back
                existing.deleted_at_utc = None
                existing.archived_at_utc = None
                lane = existing
            else:
                lane = SalesLane(id=lane_id(key), key=key, **shared_bookkeeping())
                session.add(lane)
            lane.name, lane.description = clean.name, clean.description
            lane.color, lane.technical_handoff = clean.color, clean.technical_handoff
            lane.sort_order = order
            session.flush()
            return _info(session, lane)

    def update(self, key: str, draft: LaneDraft) -> LaneInfo:
        clean = _clean_draft(draft)
        with self._database.session() as session:
            lane = _get(session, key)
            _ensure_unique_name(session, clean.name, exclude_key=key)
            lane.name, lane.description = clean.name, clean.description
            lane.color, lane.technical_handoff = clean.color, clean.technical_handoff
            session.flush()
            return _info(session, lane)

    def reorder(self, keys: Sequence[str]) -> None:
        with self._database.session() as session:
            lanes = {lane.key: lane for lane in _active_rows(session, include_archived=True)}
            if len(set(keys)) != len(keys) or not set(keys) <= set(lanes):
                raise LaneError("The lane list has changed.", action="Refresh the page.")
            ordered = [lanes[k] for k in keys] + [
                lane for k, lane in sorted(lanes.items()) if k not in set(keys)
            ]
            for index, lane in enumerate(ordered, start=1):
                lane.sort_order = index * 10

    def set_archived(self, key: str, archived: bool) -> LaneInfo:
        with self._database.session() as session:
            lane = _get(session, key)
            if archived and lane.archived_at_utc is None:
                others = [
                    row for row in _active_rows(session, include_archived=False) if row.key != key
                ]
                if not others:
                    raise LaneError(
                        "At least one lane must stay active.",
                        action="Add another lane before archiving this one.",
                    )
                lane.archived_at_utc = self._database.clock.now()
            elif not archived:
                lane.archived_at_utc = None
            session.flush()
            return _info(session, lane)

    def move_records(self, key: str, target_key: str) -> MoveOutcome:
        """Move every opportunity and lane-specific stage of ``key`` to ``target_key``."""
        if key == target_key:
            raise LaneError("Choose a different lane to move the records to.", action="")
        with self._database.session() as session:
            source = _get(session, key)
            target = _get(session, target_key)
            if target.archived_at_utc is not None:
                raise LaneError(
                    f"“{target.name}” is archived.",
                    action="Restore it first, or choose an active lane.",
                )
            ledger = ActivityLedger(session, self._actor_id, self._database.clock)
            opportunities = session.scalars(
                select(Opportunity).where(
                    Opportunity.product_lane == source.key,
                    Opportunity.deleted_at_utc.is_(None),
                )
            ).all()
            for opportunity in opportunities:
                opportunity.product_lane = target.key
                ledger.record(
                    ActivityType.FIELD_CHANGE,
                    organization_id=opportunity.organization_id,
                    opportunity_id=opportunity.id,
                    payload={
                        "entity": "opportunities",
                        "entity_id": opportunity.id,
                        "changes": {
                            "product_lane": {"old": source.key, "new": target.key},
                        },
                        "lane_names": {"old": source.name, "new": target.name},
                    },
                    flush=False,
                )
            stages = session.scalars(
                select(PipelineStage).where(
                    PipelineStage.product_lane == source.key,
                    PipelineStage.deleted_at_utc.is_(None),
                )
            ).all()
            for stage in stages:
                stage.product_lane = target.key
            return MoveOutcome(len(opportunities), len(stages))

    def delete(self, key: str) -> None:
        """Delete an unused lane (refused while any opportunity or stage uses it)."""
        with self._database.session() as session:
            lane = _get(session, key)
            info = _info(session, lane)
            if info.in_use:
                raise LaneError(
                    f"“{lane.name}” still has {info.opportunity_count} opportunities and "
                    f"{info.stage_count} stages.",
                    action="Move its records to another lane first, or archive the lane "
                    "instead: archiving keeps everything.",
                )
            remaining = [
                row for row in _active_rows(session, include_archived=False) if row.key != key
            ]
            if not remaining:
                raise LaneError(
                    "The last active lane cannot be deleted.",
                    action="Add another lane first.",
                )
            lane.deleted_at_utc = self._database.clock.now()

    def apply_preset(self, preset: str) -> builtins.list[LaneInfo]:
        """Add the lanes of a preset that do not exist yet (existing lanes are untouched)."""
        lanes = PRESETS.get(preset)
        if lanes is None:
            raise LaneError("That lane preset does not exist.", action="Choose a preset.")
        with self._database.session() as session:
            order = _max_sort_order(session) or 0
            for preset_lane in lanes:
                row = session.get(SalesLane, preset_lane.id)
                if row is not None and row.deleted_at_utc is None:
                    continue
                order += 10
                if row is None:
                    row = SalesLane(id=preset_lane.id, key=preset_lane.key, **shared_bookkeeping())
                    session.add(row)
                row.deleted_at_utc = None
                row.archived_at_utc = None
                row.name = preset_lane.name
                row.description = preset_lane.description
                row.color = preset_lane.color
                row.technical_handoff = preset_lane.technical_handoff
                row.sort_order = order
            session.flush()
            return lanes_in(session, include_archived=True)


# -- helpers shared with other services ------------------------------------------


def shared_bookkeeping() -> dict[str, object]:
    """Bookkeeping for a record whose id is derived from its content (see domain.ids)."""
    return {
        "created_at_utc": SHARED_RECORD_CREATED_AT,
        "updated_at_utc": SHARED_RECORD_CREATED_AT,
        "created_by_device_id": SYSTEM_DEVICE_ID,
    }


def _active_rows(session: Session, *, include_archived: bool) -> list[SalesLane]:
    query = select(SalesLane).where(SalesLane.deleted_at_utc.is_(None))
    if not include_archived:
        query = query.where(SalesLane.archived_at_utc.is_(None))
    return list(session.scalars(query.order_by(SalesLane.sort_order, SalesLane.name)))


def _max_sort_order(session: Session) -> int | None:
    return session.scalar(
        select(func.max(SalesLane.sort_order)).where(SalesLane.deleted_at_utc.is_(None))
    )


def _get(session: Session, key: str) -> SalesLane:
    lane = session.scalar(select(SalesLane).where(SalesLane.key == key))
    if lane is None or lane.deleted_at_utc is not None:
        raise LaneError("That lane no longer exists.", action="Refresh the page.")
    return lane


def _ensure_unique_name(session: Session, name: str, *, exclude_key: str | None) -> None:
    folded = name.casefold()
    for lane in _active_rows(session, include_archived=True):
        if lane.key != exclude_key and lane.name.casefold() == folded:
            raise LaneError(
                f"There is already a lane called “{lane.name}”.",
                action="Choose a different name"
                + (", or restore the archived lane." if lane.archived_at_utc else "."),
            )


def _counts(session: Session) -> tuple[dict[str, int], dict[str, int]]:
    opportunities: dict[str, int] = {
        str(key): int(count)
        for key, count in session.execute(
            select(Opportunity.product_lane, func.count())
            .where(Opportunity.deleted_at_utc.is_(None))
            .group_by(Opportunity.product_lane)
        )
    }
    stages: dict[str, int] = {
        str(key): int(count)
        for key, count in session.execute(
            select(PipelineStage.product_lane, func.count())
            .where(PipelineStage.deleted_at_utc.is_(None), PipelineStage.product_lane.is_not(None))
            .group_by(PipelineStage.product_lane)
        )
    }
    return opportunities, stages


def _info(
    session: Session,
    lane: SalesLane,
    counts: tuple[dict[str, int], dict[str, int]] | None = None,
) -> LaneInfo:
    opportunities, stages = counts if counts is not None else _counts(session)
    return LaneInfo(
        id=lane.id,
        key=lane.key,
        name=lane.name,
        description=lane.description,
        color=lane.color,
        sort_order=lane.sort_order,
        technical_handoff=lane.technical_handoff,
        archived=lane.archived_at_utc is not None,
        opportunity_count=opportunities.get(lane.key, 0),
        stage_count=stages.get(lane.key, 0),
    )


def lanes_in(session: Session, *, include_archived: bool = True) -> list[LaneInfo]:
    """Lanes in display order, with how many records use each.

    Lane keys used by records but without a lane record (for example data from
    a colleague's lane that has not arrived yet) are listed as archived lanes
    with a readable name, so those records always stay reachable.
    """
    counts = _counts(session)
    rows = _active_rows(session, include_archived=include_archived)
    lanes = [_info(session, row, counts) for row in rows]
    if include_archived:
        known = {row.key for row in session.scalars(select(SalesLane))}
        known |= {lane.key for lane in lanes}
        orphans = sorted((set(counts[0]) | set(counts[1])) - known)
        lanes += [
            LaneInfo(
                id=lane_id(key),
                key=key,
                name=label_for_key(key),
                description=None,
                color=None,
                sort_order=10_000,
                technical_handoff=False,
                archived=True,
                opportunity_count=counts[0].get(key, 0),
                stage_count=counts[1].get(key, 0),
            )
            for key in orphans
        ]
    return lanes


def lane_names(session: Session) -> dict[str, str]:
    """Display names of all lane keys, including archived and deleted lanes."""
    names = {row.key: row.name for row in session.scalars(select(SalesLane))}
    for key in session.scalars(select(Opportunity.product_lane).distinct()):
        names.setdefault(key, label_for_key(key))
    return names


def require_active_lane(session: Session, key: str) -> SalesLane:
    """The lane for new opportunities or stages; refuses unknown and archived lanes."""
    lane = session.scalar(select(SalesLane).where(SalesLane.key == key))
    if lane is None or lane.deleted_at_utc is not None:
        raise LaneError("That sales lane does not exist.", action="Choose one of the lanes.")
    if lane.archived_at_utc is not None:
        raise LaneError(
            f"“{lane.name}” is archived.",
            action="Choose an active lane, or restore it in Settings > Sales lanes.",
        )
    return lane
