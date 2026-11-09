# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Pipeline: stages, the board, opportunities, logged activities, tasks, reminders
and technical-review handoffs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ok, Svc
from tg_sales.api.routers.prospects import Created
from tg_sales.api.security import NotFoundError
from tg_sales.domain.enums import ActivityType, StageOutcome
from tg_sales.domain.handoff import (
    REVIEW_NOTICE,
    HandoffDraft,
    handoff_subject,
    missing_sections,
    render_handoff,
)
from tg_sales.domain.opportunities import (
    ACTIVITY_LABELS,
    LOGGABLE_ACTIVITIES,
    REASON_CODES,
    ActorInfo,
    Board,
    OpportunityDetail,
    OpportunityDraft,
    OpportunityEdit,
    Reminder,
    StageInfo,
)

router = APIRouter(tags=["pipeline"])


class Choice(BaseModel):
    value: str
    label: str


class PipelineMeta(BaseModel):
    lanes: list[Choice]
    outcomes: list[str]
    loggable_activities: list[Choice]
    activity_labels: dict[str, str]
    reason_codes: dict[str, list[Choice]]
    review_notice: str


@router.get("/pipeline/meta", response_model=PipelineMeta)
def meta(svc: Svc) -> PipelineMeta:
    return PipelineMeta(
        lanes=[
            Choice(value=lane.key, label=lane.name)
            for lane in svc.lanes.list(include_archived=False)
        ],
        outcomes=[o.value for o in StageOutcome],
        loggable_activities=[
            Choice(value=t.value, label=label) for t, label in LOGGABLE_ACTIVITIES
        ],
        activity_labels={t.value: label for t, label in ACTIVITY_LABELS.items()},
        reason_codes={
            outcome.value: [Choice(value=code, label=label) for code, label in codes]
            for outcome, codes in REASON_CODES.items()
        },
        review_notice=REVIEW_NOTICE,
    )


# ------------------------------------------------------------------ stages
class StageIn(Body):
    name: str = Field(min_length=1, max_length=80)
    outcome: StageOutcome = StageOutcome.OPEN
    lane: str | None = Field(default=None, max_length=32)  # sales lane key
    after_stage_id: str | None = None


class StageEdit(Body):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    outcome: StageOutcome | None = None


class StageOrder(Body):
    stage_ids: list[str] = Field(min_length=1, max_length=200)


class ArchiveStage(Body):
    move_to_stage_id: str | None = None


@router.get("/pipeline/stages", response_model=list[StageInfo])
def stages(svc: Svc, include_archived: bool = False) -> list[StageInfo]:
    return svc.pipeline.stages(include_archived=include_archived)


@router.post("/pipeline/stages", response_model=Created, status_code=201)
def create_stage(body: StageIn, svc: Svc) -> Created:
    return Created(
        id=svc.pipeline.create_stage(
            body.name, body.outcome, body.lane, after_stage_id=body.after_stage_id
        )
    )


@router.patch("/pipeline/stages/{stage_id}", response_model=Ok)
def edit_stage(stage_id: str, body: StageEdit, svc: Svc) -> Ok:
    if body.name is not None:
        svc.pipeline.rename_stage(stage_id, body.name)
    if body.outcome is not None:
        svc.pipeline.set_stage_outcome(stage_id, body.outcome)
    return Ok()


@router.put("/pipeline/stages/order", response_model=Ok)
def reorder(body: StageOrder, svc: Svc) -> Ok:
    svc.pipeline.reorder_stages(body.stage_ids)
    return Ok()


@router.post("/pipeline/stages/{stage_id}/archive", response_model=Ok)
def archive_stage(stage_id: str, body: ArchiveStage, svc: Svc) -> Ok:
    return Ok(count=svc.pipeline.archive_stage(stage_id, body.move_to_stage_id))


@router.post("/pipeline/stages/{stage_id}/restore", response_model=Ok)
def restore_stage(stage_id: str, svc: Svc) -> Ok:
    return Ok(ok=svc.pipeline.restore_stage(stage_id))


# ------------------------------------------------------------------- board
@router.get("/pipeline/board", response_model=Board)
def board(svc: Svc, lane: Annotated[str | None, Query(max_length=32)] = None) -> Board:
    return svc.pipeline.board(lane)


@router.get("/pipeline/actors", response_model=list[ActorInfo])
def actors(svc: Svc) -> list[ActorInfo]:
    return svc.pipeline.actors()


class OrgChoice(BaseModel):
    id: str
    name: str


@router.get("/pipeline/organizations", response_model=list[OrgChoice])
def organization_choices(svc: Svc, text: str = "") -> list[OrgChoice]:
    return [OrgChoice(id=i, name=n) for i, n in svc.pipeline.organization_choices(text)]


# ------------------------------------------------------------ opportunities
class OpportunityIn(Body):
    organization_id: str
    product_lane: str = Field(min_length=1, max_length=32)  # sales lane key
    stage_id: str
    title: str | None = Field(default=None, max_length=200)
    owner_actor_id: str | None = None
    estimated_value: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    probability: float | None = Field(default=None, ge=0, le=1)
    next_action_at: datetime | None = None
    next_action_note: str | None = Field(default=None, max_length=500)


class OpportunityEditIn(Body):
    title: str | None = Field(default=None, max_length=200)
    owner_actor_id: str | None = None
    estimated_value: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    probability: float | None = Field(default=None, ge=0, le=1)
    next_action_at: datetime | None = None
    next_action_note: str | None = Field(default=None, max_length=500)


class MoveIn(Body):
    stage_id: str
    reason_code: str | None = None
    reason_note: str | None = Field(default=None, max_length=1000)


class ActivityIn(Body):
    type: ActivityType
    occurred_at: datetime | None = None
    contact_id: str | None = None
    note: str | None = Field(default=None, max_length=10_000)


class NoteIn(Body):
    text: str = Field(min_length=1, max_length=10_000)


class VoidIn(Body):
    reason: str = Field(min_length=1, max_length=500)


class TaskIn(Body):
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime | None = None


class TaskDone(Body):
    done: bool


def _upper(currency: str | None) -> str | None:
    return currency.upper() if currency else None


@router.post("/opportunities", response_model=Created, status_code=201)
def create_opportunity(body: OpportunityIn, svc: Svc) -> Created:
    return Created(
        id=svc.pipeline.create_opportunity(
            OpportunityDraft(
                body.organization_id,
                body.product_lane,
                body.stage_id,
                title=body.title or None,
                owner_actor_id=body.owner_actor_id,
                estimated_value=body.estimated_value,
                currency=_upper(body.currency),
                probability=body.probability,
                next_action_at=body.next_action_at,
                next_action_note=body.next_action_note or None,
            )
        )
    )


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityDetail)
def opportunity(opportunity_id: str, svc: Svc) -> OpportunityDetail:
    found = svc.pipeline.detail(opportunity_id)
    if found is None:
        raise NotFoundError("That opportunity")
    return found


@router.put("/opportunities/{opportunity_id}", response_model=Ok)
def update_opportunity(opportunity_id: str, body: OpportunityEditIn, svc: Svc) -> Ok:
    changed = svc.pipeline.update(
        opportunity_id,
        OpportunityEdit(
            title=body.title or None,
            owner_actor_id=body.owner_actor_id,
            estimated_value=body.estimated_value,
            currency=_upper(body.currency),
            probability=body.probability,
            next_action_at=body.next_action_at,
            next_action_note=body.next_action_note or None,
        ),
    )
    return Ok(ok=changed)


@router.post("/opportunities/{opportunity_id}/move", response_model=Ok)
def move(opportunity_id: str, body: MoveIn, svc: Svc) -> Ok:
    moved = svc.pipeline.move(
        opportunity_id, body.stage_id, reason_code=body.reason_code, reason_note=body.reason_note
    )
    return Ok(ok=moved)


@router.post("/opportunities/{opportunity_id}/activities", response_model=Created, status_code=201)
def log_activity(opportunity_id: str, body: ActivityIn, svc: Svc) -> Created:
    return Created(
        id=svc.pipeline.log_activity(
            opportunity_id,
            body.type,
            occurred_at=body.occurred_at,
            contact_id=body.contact_id,
            note=body.note or None,
        )
    )


@router.post("/opportunities/{opportunity_id}/notes", response_model=Ok)
def add_note(opportunity_id: str, body: NoteIn, svc: Svc) -> Ok:
    svc.pipeline.add_note(opportunity_id, body.text)
    return Ok()


@router.post("/activities/{activity_id}/void", response_model=Ok)
def void(activity_id: str, body: VoidIn, svc: Svc) -> Ok:
    svc.pipeline.void_activity(activity_id, body.reason)
    return Ok()


@router.post("/opportunities/{opportunity_id}/tasks", response_model=Created, status_code=201)
def add_task(opportunity_id: str, body: TaskIn, svc: Svc) -> Created:
    return Created(id=svc.pipeline.add_task(opportunity_id, body.title, body.due_at))


@router.post("/tasks/{task_id}/done", response_model=Ok)
def task_done(task_id: str, body: TaskDone, svc: Svc) -> Ok:
    return Ok(ok=svc.pipeline.set_task_done(task_id, body.done))


@router.get("/reminders", response_model=list[Reminder])
def reminders(svc: Svc, days_ahead: int = 0) -> list[Reminder]:
    """Overdue and due follow-ups and tasks (up to the end of today plus ``days_ahead``)."""
    now = svc.pipeline.now()
    days = max(0, min(days_ahead, 60))
    return svc.pipeline.reminders(now + timedelta(days=days + 1))


# ----------------------------------------------------------------- handoff
class HandoffIn(Body):
    recipient: str = Field(default="", max_length=320)
    contact_id: str | None = None
    proposed_dataset: str = Field(default="", max_length=5000)
    use_case: str = Field(default="", max_length=5000)
    fields_and_format: str = Field(default="", max_length=5000)
    refresh_cadence: str = Field(default="", max_length=2000)
    privacy_security: str = Field(default="", max_length=5000)
    delivery_expectations: str = Field(default="", max_length=5000)
    open_questions: str = Field(default="", max_length=5000)


class HandoffView(BaseModel):
    draft: HandoffDraft
    subject: str
    body: str
    missing: list[str]


@router.post("/opportunities/{opportunity_id}/handoff/render", response_model=HandoffView)
def render(opportunity_id: str, body: HandoffIn, svc: Svc) -> HandoffView:
    base = svc.pipeline.handoff_draft(opportunity_id, body.contact_id)
    draft = HandoffDraft(
        recipient=body.recipient,
        organization=base.organization,
        website=base.website,
        contact=base.contact,
        opportunity=base.opportunity,
        proposed_dataset=body.proposed_dataset,
        use_case=body.use_case,
        fields_and_format=body.fields_and_format,
        refresh_cadence=body.refresh_cadence,
        privacy_security=body.privacy_security,
        delivery_expectations=body.delivery_expectations,
        open_questions=body.open_questions,
        prepared_by=base.prepared_by,
    )
    return HandoffView(
        draft=draft,
        subject=handoff_subject(draft),
        body=render_handoff(draft),
        missing=missing_sections(draft),
    )


class HandoffRecord(Body):
    recipient: str = Field(default="", max_length=320)
    contact_id: str | None = None


@router.post("/opportunities/{opportunity_id}/handoff", response_model=Created, status_code=201)
def record_handoff(opportunity_id: str, body: HandoffRecord, svc: Svc) -> Created:
    return Created(
        id=svc.pipeline.record_handoff(opportunity_id, body.recipient, contact_id=body.contact_id)
    )
