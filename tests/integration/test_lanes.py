# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Configurable sales lanes: upgrade of existing data, defaults, management and safety."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.engine import URL

from tg_sales.db.database import Database, alembic_config
from tg_sales.db.engine import create_pg_engine
from tg_sales.db.models import Activity, Opportunity, PipelineStage, SalesLane
from tg_sales.domain.enums import ActivityType, StageOutcome
from tg_sales.domain.kpi import KpiFilters
from tg_sales.domain.lanes import GENERIC_LANES, TATUM_GAMES_LANES, lane_id
from tg_sales.domain.opportunities import OpportunityDraft
from tg_sales.domain.periods import DateRange
from tg_sales.domain.prospects import OrganizationDraft
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.kpis import KpiService
from tg_sales.services.lanes import LaneDraft, LaneError, LaneService
from tg_sales.services.pipeline import PipelineError, PipelineService
from tg_sales.services.prospects import ProspectService

pytestmark = pytest.mark.integration

STAGE = {s.key: s.id for s in DEFAULT_STAGES}
NOW = "2026-05-01T12:00:00.000000Z"


def keys(lanes: LaneService, *, include_archived: bool = False) -> list[str]:
    return [lane.key for lane in lanes.list(include_archived=include_archived)]


# -- upgrade and defaults -----------------------------------------------------------


def test_new_installation_gets_generic_lanes(make_database: Callable[..., Database]) -> None:
    database = make_database(lane_preset=None)
    lanes = LaneService(database, None)
    assert keys(lanes) == [lane.key for lane in GENERIC_LANES]
    assert not any(lane.key == "mikros_marketing" for lane in lanes.list())


def test_upgrade_keeps_tatum_games_lanes_and_every_record(pg_url: URL) -> None:
    """A database from before configurable lanes keeps its lanes, records and history."""
    engine = create_pg_engine(pg_url, pool_size=1)
    config = alembic_config()
    try:
        with engine.connect() as connection, connection.begin():
            config.attributes["connection"] = connection
            command.downgrade(config, "0001")
        with engine.begin() as connection:
            stamp = {"now": NOW, "dev": "00000000-0000-0000-0000-000000000001"}
            connection.execute(
                text(
                    "INSERT INTO organizations (id, name, normalized_name, company_type, source,"
                    " tags, created_at_utc, updated_at_utc, created_by_device_id)"
                    " VALUES ('01900000-0000-7000-8000-000000000001', 'Old Studio', 'old studio',"
                    " 'studio', 'manual', '[]', :now, :now, :dev)"
                ),
                stamp,
            )
            for number, lane in enumerate(("data_licensing", "mikros_marketing"), start=1):
                connection.execute(
                    text(
                        "INSERT INTO opportunities (id, organization_id, product_lane, stage_id,"
                        " created_at_utc, updated_at_utc, created_by_device_id)"
                        " VALUES (:id, '01900000-0000-7000-8000-000000000001', :lane, :stage,"
                        " :now, :now, :dev)"
                    ),
                    {
                        **stamp,
                        "id": f"01900000-0000-7000-8000-00000000010{number}",
                        "lane": lane,
                        "stage": STAGE["contacted"],
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO pipeline_stages (id, name, sort_order, product_lane, outcome,"
                    " created_at_utc, updated_at_utc, created_by_device_id)"
                    " VALUES ('01900000-0000-7000-8000-000000000201', 'Data room', 65,"
                    " 'data_licensing', 'open', :now, :now, :dev)"
                ),
                stamp,
            )
    finally:
        engine.dispose()

    database = Database.open(pg_url)  # upgrades to the latest revision
    try:
        lanes = LaneService(database, None)
        assert keys(lanes) == [lane.key for lane in TATUM_GAMES_LANES]
        by_key = {lane.key: lane for lane in lanes.list()}
        assert by_key["data_licensing"].name == "Data licensing"
        assert by_key["data_licensing"].technical_handoff
        assert by_key["data_licensing"].opportunity_count == 1
        assert by_key["data_licensing"].stage_count == 1
        assert by_key["mikros_marketing"].opportunity_count == 1
        assert "general_sales" not in by_key  # generic lanes are for new installations only
        with database.session() as session:
            assert sorted(session.scalars(select(Opportunity.product_lane))) == [
                "data_licensing",
                "mikros_marketing",
            ]
            stage = session.get(PipelineStage, "01900000-0000-7000-8000-000000000201")
            assert stage is not None and stage.product_lane == "data_licensing"
            lane = session.get(SalesLane, lane_id("data_licensing"))
            assert lane is not None and lane.key == "data_licensing"
    finally:
        database.dispose()


# -- management -----------------------------------------------------------------------


@pytest.fixture
def actor(database: Database) -> str:
    return ensure_local_actor(database)


@pytest.fixture
def lanes(database: Database, actor: str) -> LaneService:
    return LaneService(database, actor)


@pytest.fixture
def pipeline(database: Database, actor: str) -> PipelineService:
    return PipelineService(database, actor)


def _opportunity(database: Database, pipeline: PipelineService, lane: str) -> str:
    org = ProspectService(database, None).create(OrganizationDraft(f"Studio {lane}"))
    return pipeline.create_opportunity(
        OpportunityDraft(organization_id=org, product_lane=lane, stage_id=STAGE["contacted"])
    )


def test_create_rename_reorder_and_use_a_lane(
    database: Database, lanes: LaneService, pipeline: PipelineService
) -> None:
    created = lanes.create(LaneDraft("Enterprise Sales", "Large accounts", "#8FA8D8"))
    assert (created.key, created.color) == ("enterprise_sales", "#8fa8d8")
    assert created.key in keys(lanes)
    opp = _opportunity(database, pipeline, created.key)

    renamed = lanes.update(created.key, LaneDraft("Enterprise", "Large accounts", "#8fa8d8"))
    assert (renamed.key, renamed.name) == ("enterprise_sales", "Enterprise")
    detail = pipeline.detail(opp)
    assert detail is not None and detail.card.product_lane == "enterprise_sales"  # unchanged key

    order = keys(lanes)
    lanes.reorder([order[-1], *order[:-1]])
    assert keys(lanes)[0] == "enterprise_sales"

    # The new lane is available in filters and the board.
    board = pipeline.board("enterprise_sales")
    assert [c.id for c in board.cards] == [opp]
    kpis = KpiService(database)
    today = kpis.today()
    report = kpis.dashboard(DateRange(today, today), KpiFilters(None, "enterprise_sales"))
    assert report.report is not None


def test_names_must_be_unique_and_valid(lanes: LaneService) -> None:
    lanes.create(LaneDraft("Consulting"))
    with pytest.raises(LaneError, match="already a lane"):
        lanes.create(LaneDraft("consulting"))
    with pytest.raises(LaneError, match="color"):
        lanes.create(LaneDraft("Sponsorships", color="purple"))
    with pytest.raises(LaneError, match="name"):
        lanes.create(LaneDraft("   "))


def test_archiving_keeps_records_and_blocks_new_opportunities(
    database: Database, lanes: LaneService, pipeline: PipelineService
) -> None:
    opp = _opportunity(database, pipeline, "mikros_marketing")
    archived = lanes.set_archived("mikros_marketing", True)
    assert archived.archived and archived.opportunity_count == 1
    assert "mikros_marketing" not in keys(lanes)
    assert "mikros_marketing" in keys(lanes, include_archived=True)
    detail = pipeline.detail(opp)
    assert detail is not None  # still there, with its history
    with pytest.raises(LaneError, match="archived"):
        _opportunity(database, pipeline, "mikros_marketing")
    assert lanes.set_archived("mikros_marketing", False).archived is False


def test_delete_is_refused_while_records_use_the_lane(
    database: Database, lanes: LaneService, pipeline: PipelineService
) -> None:
    opp = _opportunity(database, pipeline, "publisher_partnership")
    with pytest.raises(LaneError, match="still has 1 opportunities") as refused:
        lanes.delete("publisher_partnership")
    assert "archive the lane" in refused.value.suggested_action
    with database.session() as session:
        assert session.get(Opportunity, opp) is not None

    moved = lanes.move_records("publisher_partnership", "data_licensing")
    assert (moved.opportunities, moved.stages) == (1, 0)
    lanes.delete("publisher_partnership")
    assert "publisher_partnership" not in keys(lanes, include_archived=True)
    with database.session() as session:
        opportunity = session.get(Opportunity, opp)
        assert opportunity is not None and opportunity.deleted_at_utc is None
        assert opportunity.product_lane == "data_licensing"
        events = session.scalars(
            select(Activity).where(
                Activity.opportunity_id == opp, Activity.type == ActivityType.FIELD_CHANGE
            )
        ).all()
        assert [e.payload["changes"]["product_lane"] for e in events] == [
            {"old": "publisher_partnership", "new": "data_licensing"}
        ]


def test_moving_records_takes_lane_specific_stages_along(
    database: Database, lanes: LaneService, pipeline: PipelineService
) -> None:
    stage = pipeline.create_stage("Data room review", StageOutcome.OPEN, "data_licensing")
    lanes.create(LaneDraft("Software Licensing"))
    opp = _opportunity(database, pipeline, "data_licensing")
    pipeline.move(opp, stage)
    moved = lanes.move_records("data_licensing", "software_licensing")
    assert (moved.opportunities, moved.stages) == (1, 1)
    detail = pipeline.detail(opp)
    assert detail is not None and detail.card.stage_id == stage  # still a valid stage
    with pytest.raises(LaneError, match="different lane"):
        lanes.move_records("software_licensing", "software_licensing")


def test_last_active_lane_cannot_be_archived_or_deleted(
    make_database: Callable[..., Database],
) -> None:
    lanes = LaneService(make_database(lane_preset=None), None)
    lanes.delete("partnerships")
    lanes.set_archived("other", True)
    with pytest.raises(LaneError, match="At least one lane"):
        lanes.set_archived("general_sales", True)
    with pytest.raises(LaneError, match="last active lane"):
        lanes.delete("general_sales")


def test_deleted_lane_name_can_be_reused(lanes: LaneService) -> None:
    lanes.create(LaneDraft("Sponsorships"))
    lanes.delete("sponsorships")
    again = lanes.create(LaneDraft("Sponsorships", color="#d87b7a"))
    assert (again.key, again.archived, again.color) == ("sponsorships", False, "#d87b7a")


def test_presets_add_only_missing_lanes(make_database: Callable[..., Database]) -> None:
    lanes = LaneService(make_database(lane_preset=None), None)
    lanes.update("other", LaneDraft("Something else"))
    lanes.apply_preset("tatum_games")
    lanes.apply_preset("generic")  # already there: unchanged
    names = {lane.key: lane.name for lane in lanes.list()}
    assert names["other"] == "Something else"
    assert {"data_licensing", "publisher_partnership", "mikros_marketing"} <= set(names)
    with pytest.raises(LaneError):
        lanes.apply_preset("unknown")


def test_unknown_lane_is_refused_and_technical_handoff_follows_the_lane(
    database: Database, lanes: LaneService, pipeline: PipelineService
) -> None:
    with pytest.raises(LaneError, match="does not exist"):
        _opportunity(database, pipeline, "crypto")
    lanes.create(LaneDraft("Consulting", technical_handoff=True))
    opp = _opportunity(database, pipeline, "consulting")
    draft = pipeline.handoff_draft(opp)
    assert draft.opportunity == "Consulting"
    other = _opportunity(database, pipeline, "mikros_marketing")
    with pytest.raises(PipelineError, match="handoffs are not turned on"):
        pipeline.handoff_draft(other)


def test_records_with_an_unknown_lane_key_stay_visible(
    database: Database, lanes: LaneService, pipeline: PipelineService
) -> None:
    opp = _opportunity(database, pipeline, "data_licensing")
    with database.session() as session:  # e.g. a colleague's lane that has not arrived yet
        opportunity = session.get(Opportunity, opp)
        assert opportunity is not None
        opportunity.product_lane = "colleague_lane"
    listed = {lane.key: lane for lane in lanes.list(include_archived=True)}
    assert listed["colleague_lane"].name == "Colleague lane"
    assert listed["colleague_lane"].opportunity_count == 1
    assert lanes.names()["colleague_lane"] == "Colleague lane"


def test_identical_lanes_on_two_computers_are_the_same_record(
    make_database: Callable[..., Database],
) -> None:
    rows = []
    for _ in range(2):  # two computers create the same lane independently
        database = make_database(lane_preset=None)
        created = LaneService(database, None).create(LaneDraft("Consulting"))
        with database.session() as session:
            row = session.get(SalesLane, created.id)
            assert row is not None
            rows.append((row.id, row.created_at_utc, row.created_by_device_id))
    assert rows[0] == rows[1]  # identical, so sync merges them without a conflict
    assert rows[0][0] == lane_id("consulting")
    assert rows[0][1] == datetime(2026, 1, 1, tzinfo=UTC)
