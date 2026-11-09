# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from tg_sales.db.database import Database
from tg_sales.db.models import Activity, Contact
from tg_sales.domain.enums import (
    ActivityType,
    ContactStatus,
    ProductLane,
    ReleasePrecision,
    StageOutcome,
)
from tg_sales.domain.handoff import render_handoff
from tg_sales.domain.opportunities import OpportunityDraft, OpportunityEdit
from tg_sales.domain.prospects import ContactDraft, GameDraft, OrganizationDraft
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.pipeline import PipelineError, PipelineService
from tg_sales.services.pipeline_history import PipelineHistory
from tg_sales.services.prospects import ProspectService

from .conftest import START, FakeClock

pytestmark = pytest.mark.integration

STAGE = {s.key: s.id for s in DEFAULT_STAGES}
LANE = ProductLane.DATA_LICENSING


@pytest.fixture
def actor(database: Database) -> str:
    return ensure_local_actor(database)


@pytest.fixture
def pipeline(database: Database, actor: str) -> PipelineService:
    return PipelineService(database, actor)


@pytest.fixture
def prospects(database: Database, actor: str) -> ProspectService:
    return ProspectService(database, actor)


@pytest.fixture
def org(prospects: ProspectService) -> str:
    return prospects.create(
        OrganizationDraft("Pixel Forge", "pixelforge.example"),
        [ContactDraft(name="Ana Ruiz", email="ana@pixelforge.example", role_title="CTO")],
    )


def new_opp(
    pipeline: PipelineService, org: str, lane: ProductLane = LANE, stage: str = "discovered"
) -> str:
    return pipeline.create_opportunity(
        OpportunityDraft(org, lane, STAGE[stage], title=f"{lane.value} deal")
    )


def test_board_has_default_stages_and_cards(
    pipeline: PipelineService, org: str, prospects: ProspectService
) -> None:
    prospects.add_game(
        org,
        GameDraft(
            "Sky Rails", release_date=date(2027, 3, 1), release_precision=ReleasePrecision.MONTH
        ),
    )
    a = new_opp(pipeline, org)
    b = new_opp(pipeline, org, ProductLane.MIKROS_MARKETING, "contacted")
    board = pipeline.board()
    assert [s.name for s in board.stages] == [s.name for s in DEFAULT_STAGES]
    assert {c.id for c in board.cards} == {a, b}  # several opportunities per organization
    card = next(c for c in board.cards if c.id == a)
    assert card.organization_name == "Pixel Forge"
    assert card.owner_name == "Salesperson"
    assert card.release_date == date(2027, 3, 1)
    assert card.last_activity_at is not None
    assert [c.id for c in pipeline.board(ProductLane.MIKROS_MARKETING).cards] == [b]


def test_move_writes_history_and_terminal_needs_reason(
    pipeline: PipelineService, org: str, database: Database, clock: FakeClock
) -> None:
    opp = new_opp(pipeline, org)
    clock.set(START + timedelta(days=1))
    assert pipeline.move(opp, STAGE["contacted"])
    assert not pipeline.move(opp, STAGE["contacted"])  # unchanged
    with pytest.raises(PipelineError, match="needs a reason"):
        pipeline.move(opp, STAGE["won"])
    with pytest.raises(PipelineError, match="needs a reason"):
        pipeline.move(opp, STAGE["lost"], reason_code="signed")  # not a lost reason
    clock.set(START + timedelta(days=2))
    assert pipeline.move(opp, STAGE["lost"], reason_code="timing", reason_note="Budget next year")
    detail = pipeline.detail(opp)
    assert detail is not None
    assert detail.card.closed
    assert detail.outcome_reason_code == "timing"
    assert detail.outcome_reason == "Budget next year"
    summaries = [a.summary for a in detail.activities]
    assert "Moved to Lost — Budget next year" in summaries
    with database.session() as session:
        history = PipelineHistory(session)
        assert history.stage_of(opp, START + timedelta(hours=12)) == STAGE["discovered"]
        assert history.stage_of(opp, START + timedelta(days=1, hours=1)) == STAGE["contacted"]
        assert history.stage_of(opp, START + timedelta(days=3)) == STAGE["lost"]
    clock.set(START + timedelta(days=3))
    assert pipeline.move(opp, STAGE["interested"])  # reopening clears the outcome
    reopened = pipeline.detail(opp)
    assert reopened is not None
    assert (reopened.card.closed, reopened.outcome_reason_code, reopened.closed_at) == (
        False,
        None,
        None,
    )


def test_lane_specific_stage_rules(pipeline: PipelineService, org: str) -> None:
    lane_stage = pipeline.create_stage(
        "Data room review", lane=LANE, after_stage_id=STAGE["interested"]
    )
    marketing = new_opp(pipeline, org, ProductLane.MIKROS_MARKETING)
    with pytest.raises(PipelineError, match="sales lane"):
        pipeline.move(marketing, lane_stage)
    data = new_opp(pipeline, org)
    assert pipeline.move(data, lane_stage)
    assert lane_stage in [s.id for s in pipeline.board(LANE).stages]
    assert lane_stage not in [s.id for s in pipeline.board(ProductLane.MIKROS_MARKETING).stages]


def test_stage_create_rename_reorder(
    pipeline: PipelineService, org: str, database: Database
) -> None:
    opp = new_opp(pipeline, org, stage="researching")
    new_id = pipeline.create_stage("Qualified", after_stage_id=STAGE["researching"])
    names = [s.name for s in pipeline.stages()]
    assert names.index("Qualified") == names.index("Researching") + 1
    with pytest.raises(PipelineError, match="already exists"):
        pipeline.create_stage("qualified")
    with pytest.raises(PipelineError, match="needs a name"):
        pipeline.rename_stage(new_id, "  ")
    assert pipeline.rename_stage(STAGE["researching"], "Research")
    detail = pipeline.detail(opp)
    assert detail is not None and detail.stage.name == "Research"
    assert detail.stage.id == STAGE["researching"]  # ids never change, so history stays valid
    pipeline.move_stage(new_id, -10)
    assert pipeline.stages()[0].id == new_id
    orders = [s.sort_order for s in pipeline.stages()]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)
    with pytest.raises(PipelineError, match="changed"):
        pipeline.reorder_stages([new_id])
    with database.session() as session:
        stage_events = session.scalars(
            select(Activity).where(Activity.type == ActivityType.FIELD_CHANGE)
        ).all()
        entities = {e.payload.get("entity") for e in stage_events}
        assert "pipeline_stages" in entities


def test_archive_stage_moves_opportunities_and_keeps_reports_consistent(
    pipeline: PipelineService, org: str, database: Database, clock: FakeClock
) -> None:
    opps = [new_opp(pipeline, org, stage="follow_up") for _ in range(3)]
    with pytest.raises(PipelineError, match="has 3 opportunities"):
        pipeline.archive_stage(STAGE["follow_up"], None)
    clock.set(START + timedelta(days=5))
    assert pipeline.archive_stage(STAGE["follow_up"], STAGE["contacted"]) == 3
    assert STAGE["follow_up"] not in [s.id for s in pipeline.stages()]
    archived = next(s for s in pipeline.stages(include_archived=True) if s.id == STAGE["follow_up"])
    assert archived.archived
    with pytest.raises(PipelineError, match="archived"):
        pipeline.move(opps[0], STAGE["follow_up"])
    with database.session() as session:
        history = PipelineHistory(session)
        before = history.stage_counts_as_of(START + timedelta(days=1))
        after = history.stage_counts_as_of(START + timedelta(days=6))
    assert before == {STAGE["follow_up"]: 3}  # the past is unchanged
    assert after == {STAGE["contacted"]: 3}
    assert pipeline.restore_stage(STAGE["follow_up"])
    assert STAGE["follow_up"] in [s.id for s in pipeline.stages()]


def test_stage_safeguards(pipeline: PipelineService, org: str) -> None:
    opp = new_opp(pipeline, org, stage="negotiation")
    with pytest.raises(PipelineError, match="has opportunities"):
        pipeline.set_stage_outcome(STAGE["negotiation"], StageOutcome.LOST)
    assert pipeline.set_stage_outcome(STAGE["researching"], StageOutcome.NOT_A_FIT)
    open_ids = [s.id for s in pipeline.stages() if s.outcome is StageOutcome.OPEN]
    for stage_id in open_ids:
        if stage_id != STAGE["negotiation"]:
            pipeline.archive_stage(stage_id, None)
    with pytest.raises(PipelineError, match="open stage"):
        pipeline.archive_stage(STAGE["negotiation"], STAGE["lost"])
    del opp


def test_update_details_and_validation(pipeline: PipelineService, org: str, actor: str) -> None:
    opp = new_opp(pipeline, org)
    due = datetime(2026, 10, 3, 9, tzinfo=UTC)
    assert pipeline.update(
        opp,
        OpportunityEdit(
            title="Historical data",
            owner_actor_id=actor,
            estimated_value=25000,
            currency="usd",
            probability=0.4,
            next_action_at=due,
            next_action_note="Send sample",
        ),
    )
    assert not pipeline.update(
        opp,
        OpportunityEdit(
            title="Historical data",
            owner_actor_id=actor,
            estimated_value=25000,
            currency="USD",
            probability=0.4,
            next_action_at=due,
            next_action_note="Send sample",
        ),
    )
    detail = pipeline.detail(opp)
    assert detail is not None
    assert (detail.currency, detail.card.next_action_at, detail.card.title) == (
        "USD",
        due,
        "Historical data",
    )
    assert any(a.summary.startswith("Opportunity updated") for a in detail.activities)
    for edit, message in (
        (OpportunityEdit(estimated_value=-1), "negative"),
        (OpportunityEdit(probability=1.5), "between"),
        (OpportunityEdit(currency="dollars"), "currency code"),
        (OpportunityEdit(owner_actor_id="nobody"), "owner"),
    ):
        with pytest.raises(PipelineError, match=message):
            pipeline.update(opp, edit)


def test_log_interactions_updates_contact_status(
    pipeline: PipelineService, org: str, database: Database, prospects: ProspectService
) -> None:
    opp = new_opp(pipeline, org)
    detail = pipeline.detail(opp)
    assert detail is not None
    contact_id = detail.contacts[0].id
    assert detail.contacts[0].label == "Ana Ruiz (CTO)"
    pipeline.log_activity(opp, ActivityType.EMAIL, contact_id=contact_id, note="Intro email")
    with database.session() as session:
        contact = session.get(Contact, contact_id)
        assert contact is not None and contact.contact_status is ContactStatus.ATTEMPTED
    pipeline.log_activity(opp, ActivityType.REPLY, contact_id=contact_id)
    with database.session() as session:
        contact = session.get(Contact, contact_id)
        assert contact is not None and contact.contact_status is ContactStatus.RESPONDED
    pipeline.log_activity(opp, ActivityType.EMAIL, contact_id=contact_id)
    with database.session() as session:
        contact = session.get(Contact, contact_id)
        assert (
            contact is not None and contact.contact_status is ContactStatus.RESPONDED
        )  # never goes back
    summaries = [a.summary for a in pipeline.detail(opp).activities]  # type: ignore[union-attr]
    assert "Email logged: Intro email" in summaries
    assert not any("sent" in s.lower() for s in summaries)
    with pytest.raises(PipelineError, match="future"):
        pipeline.log_activity(opp, ActivityType.EMAIL, occurred_at=datetime(2030, 1, 1, tzinfo=UTC))
    with pytest.raises(PipelineError, match="cannot be logged"):
        pipeline.log_activity(opp, ActivityType.STAGE_CHANGE)
    other = prospects.create(OrganizationDraft("Other"), [ContactDraft(name="Zed")])
    other_contact = prospects.get_detail(other).contacts[0].id  # type: ignore[union-attr]
    with pytest.raises(PipelineError, match="does not belong"):
        pipeline.log_activity(opp, ActivityType.EMAIL, contact_id=other_contact)
    backdated = pipeline.log_activity(
        opp, ActivityType.PHONE_CALL, occurred_at=START - timedelta(days=2), note="Old call"
    )
    pipeline.void_activity(backdated, "Wrong prospect")
    voided = next(a for a in pipeline.detail(opp).activities if a.id == backdated)  # type: ignore[union-attr]
    assert voided.voided


def test_notes_tasks_and_reminders(pipeline: PipelineService, org: str, clock: FakeClock) -> None:
    opp = new_opp(pipeline, org)
    pipeline.add_note(opp, "Prefers calls")
    with pytest.raises(PipelineError):
        pipeline.add_note(opp, " ")
    overdue_task = pipeline.add_task(opp, "Send pricing", START - timedelta(hours=1))
    pipeline.add_task(opp, "Later task", START + timedelta(days=30))
    with pytest.raises(PipelineError):
        pipeline.add_task(opp, "", None)
    pipeline.update(
        opp,
        OpportunityEdit(next_action_at=START + timedelta(hours=3), next_action_note="Call back"),
    )
    reminders = pipeline.reminders(START + timedelta(days=1))
    assert [(r.kind, r.title, r.overdue) for r in reminders] == [
        ("task", "Send pricing", True),
        ("next_action", "Call back", False),
    ]
    assert pipeline.set_task_done(overdue_task, True)
    assert not pipeline.set_task_done(overdue_task, True)
    assert [r.title for r in pipeline.reminders(START + timedelta(days=1))] == ["Call back"]
    pipeline.move(opp, STAGE["won"], reason_code="signed")
    assert (
        pipeline.reminders(START + timedelta(days=1)) == []
    )  # closed deals have no due next action
    detail = pipeline.detail(opp)
    assert detail is not None
    assert [t.title for t in detail.tasks] == ["Later task", "Send pricing"]  # open first
    summaries = [a.summary for a in detail.activities]
    assert "Task completed: Send pricing" in summaries and "Note: Prefers calls" in summaries
    assert pipeline.set_task_done(overdue_task, False)


def test_technical_handoff_draft(pipeline: PipelineService, org: str) -> None:
    opp = new_opp(pipeline, org)
    draft = pipeline.handoff_draft(opp)
    assert draft.recipient == ""  # no built-in recipient; the salesperson fills it in
    assert draft.contact == "Ana Ruiz (CTO) <ana@pixelforge.example>"
    text = render_handoff(draft)
    assert text.startswith("Subject: Technical handoff: Pixel Forge")
    assert "authorized internal review" in text
    assert "Not provided yet" in text
    pipeline.record_handoff(opp, draft.recipient)
    detail = pipeline.detail(opp)
    assert detail is not None
    assert detail.activities[0].type is ActivityType.TECHNICAL_HANDOFF
    assert (
        "copied" in detail.activities[0].summary
        and "sent" not in detail.activities[0].summary.split(":")[0]
    )
    marketing = new_opp(pipeline, org, ProductLane.MIKROS_MARKETING)
    with pytest.raises(PipelineError, match="handoffs are not turned on"):
        pipeline.handoff_draft(marketing)


def test_create_validation_and_choices(pipeline: PipelineService, org: str) -> None:
    with pytest.raises(PipelineError, match="no longer exists"):
        pipeline.create_opportunity(OpportunityDraft("missing", LANE, STAGE["discovered"]))
    lane_stage = pipeline.create_stage("Marketing brief", lane=ProductLane.MIKROS_MARKETING)
    with pytest.raises(PipelineError, match="sales lane"):
        pipeline.create_opportunity(OpportunityDraft(org, LANE, lane_stage))
    assert pipeline.organization_choices("pixel") == [(org, "Pixel Forge")]
    assert pipeline.organization_choices("100%") == []
    assert [a.name for a in pipeline.actors()] == ["Salesperson"]
