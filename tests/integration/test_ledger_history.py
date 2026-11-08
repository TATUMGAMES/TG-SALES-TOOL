from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from tg_sales.db.database import Database
from tg_sales.db.models import Opportunity, Organization
from tg_sales.domain.enums import ActivityType, ProductLane
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.repositories.activities import ActivityRepository
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.ledger import ActivityLedger
from tg_sales.services.opportunities import OpportunityService
from tg_sales.services.pipeline_history import PipelineHistory

pytestmark = pytest.mark.integration

STAGE = {s.key: s.id for s in DEFAULT_STAGES}
D0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def day(n: float) -> datetime:
    return D0 + timedelta(days=n)


def services(database: Database, session: Session) -> tuple[ActivityLedger, OpportunityService]:
    actor = ensure_local_actor(database)
    ledger = ActivityLedger(session, actor, database.clock)
    return ledger, OpportunityService(session, ledger, database.clock)


@pytest.fixture
def org_id(database: Database) -> str:
    with database.session() as session:
        org = Organization(name="Example Studio", normalized_name="example studio")
        session.add(org)
        session.flush()
        return org.id


def test_create_and_move_records_immutable_history(database: Database, org_id: str) -> None:
    with database.session() as session:
        _, opportunities = services(database, session)
        opp = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.DATA_LICENSING,
            stage_id=STAGE["discovered"],
            occurred_at=day(0),
        )
        assert opportunities.move_to_stage(opp.id, STAGE["discovered"]) is None
        opportunities.move_to_stage(opp.id, STAGE["contacted"], occurred_at=day(2))
        won = opportunities.move_to_stage(opp.id, STAGE["won"], occurred_at=day(9), reason="signed")
        assert won is not None
        assert opp.stage_id == STAGE["won"]
        assert opp.closed_at_utc == day(9)
        assert opp.outcome_reason == "signed"
        opp_id = opp.id

    with database.session() as session:
        timeline = ActivityRepository(session).for_opportunity(opp_id)
        assert [a.type for a in timeline] == [
            ActivityType.OPPORTUNITY_CREATED,
            ActivityType.STAGE_CHANGE,
            ActivityType.STAGE_CHANGE,
        ]
        assert timeline[1].payload["from_stage_id"] == STAGE["discovered"]
        assert timeline[1].payload["to_stage_id"] == STAGE["contacted"]
        assert timeline[2].payload["to_outcome"] == "won"
        assert all(a.actor_id is not None for a in timeline)
        assert all(a.created_by_device_id == database.device_id for a in timeline)
        assert {a.organization_id for a in timeline} == {org_id}


def test_snapshot_as_of_reconstructs_past_pipeline(database: Database, org_id: str) -> None:
    with database.session() as session:
        _, opportunities = services(database, session)
        data = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.DATA_LICENSING,
            stage_id=STAGE["discovered"],
            occurred_at=day(0),
        )
        marketing = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.MIKROS_MARKETING,
            stage_id=STAGE["researching"],
            occurred_at=day(1),
        )
        opportunities.move_to_stage(data.id, STAGE["contacted"], occurred_at=day(3))
        opportunities.move_to_stage(marketing.id, STAGE["lost"], occurred_at=day(5))
        opportunities.move_to_stage(data.id, STAGE["negotiation"], occurred_at=day(7))

    with database.session() as session:
        history = PipelineHistory(session)
        assert history.stage_counts_as_of(day(-1)) == {}
        assert history.stage_counts_as_of(day(0.5)) == {STAGE["discovered"]: 1}
        assert history.stage_counts_as_of(day(4)) == {
            STAGE["contacted"]: 1,
            STAGE["researching"]: 1,
        }
        assert history.stage_counts_as_of(day(30)) == {
            STAGE["negotiation"]: 1,
            STAGE["lost"]: 1,
        }
        assert history.stage_counts_as_of(day(4), lane=ProductLane.MIKROS_MARKETING) == {
            STAGE["researching"]: 1
        }
        assert history.stage_of(data.id, day(6)) == STAGE["contacted"]


def test_corrections_preserve_original_and_change_history(database: Database, org_id: str) -> None:
    with database.session() as session:
        ledger, opportunities = services(database, session)
        opp = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.PUBLISHER_PARTNERSHIP,
            stage_id=STAGE["discovered"],
            occurred_at=day(0),
        )
        move = opportunities.move_to_stage(opp.id, STAGE["interested"], occurred_at=day(10))
        assert move is not None
        correction = ledger.correct(move.id, reason="logged late", occurred_at=day(4))
        assert correction.corrects_event_id == move.id
        assert correction.payload["original"]["occurred_at_utc"].startswith("2026-09-11")
        with pytest.raises(ValueError, match="cannot itself be corrected"):
            ledger.correct(correction.id, reason="x", void=True)
        with pytest.raises(ValueError, match="void the event or give a new time"):
            ledger.correct(move.id, reason="x")
        with pytest.raises(ValueError, match="does not exist"):
            ledger.correct("00000000-0000-7000-8000-000000000000", reason="x", void=True)
        opp_id, move_id = opp.id, move.id

    with database.session() as session:
        history = PipelineHistory(session)
        assert history.stage_of(opp_id, day(5)) == STAGE["interested"]
        original = ActivityRepository(session).get(move_id)
        assert original is not None
        assert original.occurred_at_utc == day(10)  # the original event is untouched

    with database.session() as session:
        ledger, _ = services(database, session)
        ledger.correct(move_id, reason="never happened", void=True)
    with database.session() as session:
        assert PipelineHistory(session).stage_of(opp_id, day(30)) == STAGE["discovered"]


def test_deleted_opportunities_drop_out_after_deletion(database: Database, org_id: str) -> None:
    with database.session() as session:
        _, opportunities = services(database, session)
        opp = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.DATA_LICENSING,
            stage_id=STAGE["discovered"],
            occurred_at=day(0),
        )
        opp_id = opp.id
    with database.session() as session:
        row = session.get(Opportunity, opp_id)
        assert row is not None
        row.deleted_at_utc = day(5)
    with database.session() as session:
        history = PipelineHistory(session)
        assert history.stage_of(opp_id, day(4)) == STAGE["discovered"]
        assert history.stage_of(opp_id, day(5)) is None


def test_invalid_moves_are_rejected(database: Database, org_id: str) -> None:
    with database.session() as session:
        _, opportunities = services(database, session)
        with pytest.raises(ValueError, match="not available"):
            opportunities.create(
                organization_id=org_id,
                product_lane=ProductLane.DATA_LICENSING,
                stage_id="00000000-0000-7000-8000-000000000000",
            )
        with pytest.raises(ValueError, match="does not exist"):
            opportunities.move_to_stage("00000000-0000-7000-8000-000000000000", STAGE["won"])


def test_terminal_stage_on_creation_sets_closed_time(database: Database, org_id: str) -> None:
    with database.session() as session:
        _, opportunities = services(database, session)
        opp = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.DATA_LICENSING,
            stage_id=STAGE["not_a_fit"],
            occurred_at=day(1),
        )
        assert opp.closed_at_utc == day(1)
        reopened = opportunities.move_to_stage(opp.id, STAGE["researching"], occurred_at=day(2))
        assert reopened is not None
        assert opp.closed_at_utc is None
