# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Sales lanes: list, create, rename, recolor, reorder, archive, move records, delete."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ctx, Ok, Svc
from tg_sales.domain.lanes import MAX_DESCRIPTION_LENGTH, MAX_NAME_LENGTH, PRESET_LABELS, LaneInfo
from tg_sales.services.lanes import LaneDraft, MoveOutcome

router = APIRouter(tags=["lanes"])


class LaneView(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    color: str | None
    sort_order: int
    technical_handoff: bool
    archived: bool
    opportunity_count: int
    stage_count: int
    in_use: bool

    @classmethod
    def of(cls, lane: LaneInfo) -> LaneView:
        return cls(
            id=lane.id,
            key=lane.key,
            name=lane.name,
            description=lane.description,
            color=lane.color,
            sort_order=lane.sort_order,
            technical_handoff=lane.technical_handoff,
            archived=lane.archived,
            opportunity_count=lane.opportunity_count,
            stage_count=lane.stage_count,
            in_use=lane.in_use,
        )


class LaneIn(Body):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    color: str | None = Field(default=None, max_length=16)
    technical_handoff: bool = False

    def draft(self) -> LaneDraft:
        return LaneDraft(self.name, self.description, self.color, self.technical_handoff)


class LaneOrder(Body):
    keys: list[str] = Field(min_length=1, max_length=200)


class LaneArchive(Body):
    archived: bool


class LaneMove(Body):
    target_key: str = Field(min_length=1, max_length=32)


class MoveResult(BaseModel):
    opportunities: int
    stages: int
    backup: str | None


class PresetView(BaseModel):
    key: str
    label: str


@router.get("/lanes", response_model=list[LaneView])
def lanes(svc: Svc, include_archived: bool = True) -> list[LaneView]:
    return [LaneView.of(lane) for lane in svc.lanes.list(include_archived=include_archived)]


@router.get("/lanes/presets", response_model=list[PresetView])
def presets() -> list[PresetView]:
    return [PresetView(key=key, label=label) for key, label in PRESET_LABELS.items()]


@router.post("/lanes/presets/{preset}", response_model=list[LaneView])
def apply_preset(preset: str, svc: Svc) -> list[LaneView]:
    return [LaneView.of(lane) for lane in svc.lanes.apply_preset(preset)]


@router.post("/lanes", response_model=LaneView, status_code=201)
def create_lane(body: LaneIn, svc: Svc) -> LaneView:
    return LaneView.of(svc.lanes.create(body.draft()))


@router.put("/lanes/order", response_model=Ok)
def reorder_lanes(body: LaneOrder, svc: Svc) -> Ok:
    svc.lanes.reorder(body.keys)
    return Ok()


@router.put("/lanes/{key}", response_model=LaneView)
def update_lane(key: str, body: LaneIn, svc: Svc) -> LaneView:
    return LaneView.of(svc.lanes.update(key, body.draft()))


@router.post("/lanes/{key}/archive", response_model=LaneView)
def archive_lane(key: str, body: LaneArchive, svc: Svc) -> LaneView:
    return LaneView.of(svc.lanes.set_archived(key, body.archived))


@router.post("/lanes/{key}/move", response_model=MoveResult)
def move_lane_records(key: str, body: LaneMove, ctx: Ctx, svc: Svc) -> MoveResult:
    backup = ctx.backup_before("pre-lane-move")
    outcome: MoveOutcome = svc.lanes.move_records(key, body.target_key)
    return MoveResult(
        opportunities=outcome.opportunities,
        stages=outcome.stages,
        backup=backup.name if backup else None,
    )


@router.delete("/lanes/{key}", response_model=Ok)
def delete_lane(key: str, svc: Svc) -> Ok:
    svc.lanes.delete(key)
    return Ok()
