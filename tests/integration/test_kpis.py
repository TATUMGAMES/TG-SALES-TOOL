from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tg_sales.db.database import Database
from tg_sales.db.models import Opportunity, Organization
from tg_sales.domain.enums import ActivityType, ProductLane, RecordSource, StageOutcome
from tg_sales.domain.kpi import KpiFilters, period_for, trend_buckets
from tg_sales.domain.opportunities import OpportunityDraft, OpportunityEdit
from tg_sales.domain.periods import DateRange
from tg_sales.domain.prospects import ContactDraft, GameDraft, OrganizationDraft
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.repositories.actors import ActorRepository
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.kpis import KpiService
from tg_sales.services.ledger import ActivityLedger
from tg_sales.services.pipeline import PipelineService
from tg_sales.services.prospects import ProspectService

from .conftest import FakeClock

pytestmark = pytest.mark.integration

NY = ZoneInfo("America/New_York")
STAGE = {s.key: s.id for s in DEFAULT_STAGES}
OCTOBER = DateRange(date(2026, 10, 1), date(2026, 10, 31))


def at(day: int, hour: int = 12, month: int = 10) -> datetime:
    """A moment in New York local time, as UTC."""
    return datetime(2026, month, day, hour, tzinfo=NY).astimezone(UTC)


class World:
    """Builds a small sales history with controlled times."""

    def __init__(self, database: Database, clock: FakeClock) -> None:
        self.db = database
        self.clock = clock
        self.actor = ensure_local_actor(database)
        with database.session() as session:
            self.other_actor = ActorRepository(session).add("Second Salesperson").id
        self.prospects = ProspectService(database, self.actor)
        self.pipeline = PipelineService(database, self.actor)
        self.other_pipeline = PipelineService(database, self.other_actor)
        self.kpis = KpiService(database, zone=NY)

    def org(self, org_name: str, when: datetime, **contact: str) -> tuple[str, str | None]:
        self.clock.set(when)
        contacts = [ContactDraft(**contact)] if contact else []  # type: ignore[arg-type]
        org_id = self.prospects.create(OrganizationDraft(org_name), contacts)
        detail = self.prospects.get_detail(org_id)
        assert detail is not None
        return org_id, (detail.contacts[0].id if detail.contacts else None)

    def opp(
        self,
        org_id: str,
        when: datetime,
        stage: str = "discovered",
        lane: ProductLane = ProductLane.DATA_LICENSING,
        pipeline: PipelineService | None = None,
    ) -> str:
        self.clock.set(when)
        service = pipeline or self.pipeline
        opp_id = service.create_opportunity(OpportunityDraft(org_id, lane, STAGE[stage]))
        if pipeline is not None:
            service.update(opp_id, OpportunityEdit(owner_actor_id=service.actor_id))
        return opp_id

    def move(self, opp_id: str, stage: str, when: datetime, code: str | None = None) -> None:
        self.clock.set(when)
        if code is None and stage in ("won", "lost", "not_a_fit"):
            code = {"won": "signed", "lost": "price", "not_a_fit": "no_need"}[stage]
        self.pipeline.move(opp_id, STAGE[stage], reason_code=code)

    def report(
        self,
        dates: DateRange = OCTOBER,
        filters: KpiFilters | None = None,
        now: datetime | None = None,
    ):  # type: ignore[no-untyped-def]
        self.clock.set(now or at(31, 23))
        return self.kpis.dashboard(dates, filters or KpiFilters()).report


@pytest.fixture
def world(database: Database, clock: FakeClock) -> World:
    return World(database, clock)


def value(report: object, key: str) -> float | None:
    return report.metrics[key].value  # type: ignore[attr-defined]


def test_period_boundaries_follow_local_days_across_dst() -> None:
    spring = period_for(DateRange(date(2026, 3, 8), date(2026, 3, 8)), NY)
    autumn = period_for(DateRange(date(2026, 11, 1), date(2026, 11, 1)), NY)
    assert spring.p1 - spring.p0 == timedelta(hours=23)
    assert autumn.p1 - autumn.p0 == timedelta(hours=25)
    assert spring.p0 == datetime(2026, 3, 8, 5, tzinfo=UTC)  # midnight EST
    size, buckets = trend_buckets(
        period_for(DateRange(date(2026, 3, 1), date(2026, 3, 14)), NY), NY
    )
    assert size.value == "day" and len(buckets) == 14
    assert buckets[7].end - buckets[7].start == timedelta(hours=23)
    weekly = trend_buckets(period_for(DateRange(date(2026, 1, 1), date(2026, 3, 31)), NY), NY)
    monthly = trend_buckets(period_for(DateRange(date(2025, 11, 1), date(2026, 10, 31)), NY), NY)
    assert weekly[0].value == "week" and monthly[0].value == "month" and len(monthly[1]) == 12


def test_leads_and_contacts_boundaries_and_deletions(world: World, database: Database) -> None:
    period = period_for(OCTOBER, NY)
    world.org("Starts exactly", period.p0, name="Ana")
    world.org("Last microsecond", period.p1 - timedelta(microseconds=1))
    world.org("Next period", period.p1)
    world.org("Before", period.p0 - timedelta(microseconds=1))
    deleted_inside, _ = world.org("Deleted in period", at(5))
    deleted_after, _ = world.org("Deleted later", at(6))
    with database.session() as session:
        session.get(Organization, deleted_inside).deleted_at_utc = at(20)  # type: ignore[union-attr]
        session.get(Organization, deleted_after).deleted_at_utc = at(5, month=11)  # type: ignore[union-attr]
    report = world.report()
    names = sorted(r.organization for r in report.metrics["leads_added"].rows)
    assert names == ["Deleted later", "Last microsecond", "Starts exactly"]
    assert value(report, "leads_added") == 3
    assert value(report, "contacts_added") == 1


def test_unique_contacts_attempted_with_corrections_and_backdating(
    world: World, clock: FakeClock
) -> None:
    org, ana = world.org("Pixel Forge", at(1), name="Ana", email="ana@pixelforge.example")
    opp = world.opp(org, at(1))
    world.prospects.add_contact(org, ContactDraft(name="Bo"))
    bo = next(c.id for c in world.prospects.get_detail(org).contacts if c.name == "Bo")  # type: ignore[union-attr]
    clock.set(at(25))
    world.pipeline.log_activity(opp, ActivityType.EMAIL, occurred_at=at(3), contact_id=ana)
    world.pipeline.log_activity(
        opp, ActivityType.LINKEDIN_MESSAGE, occurred_at=at(4), contact_id=ana
    )
    world.pipeline.log_activity(opp, ActivityType.EMAIL, occurred_at=at(4))  # no contact
    voided = world.pipeline.log_activity(
        opp, ActivityType.PHONE_CALL, occurred_at=at(5), contact_id=bo
    )
    world.pipeline.void_activity(voided, "Wrong number")
    # Imported/backdated historical event: recorded now, happened in September.
    world.pipeline.log_activity(opp, ActivityType.EMAIL, occurred_at=at(20, month=9), contact_id=bo)
    report = world.report()
    assert (
        value(report, "contacts_attempted") == 1
    )  # Ana once; Bo's only October attempt was voided
    september = world.report(DateRange(date(2026, 9, 1), date(2026, 9, 30)))
    assert value(september, "contacts_attempted") == 1  # counted when it happened
    # A correction moving an event into the period makes it count there.
    clock.set(at(26))
    with world.db.session() as session:
        ActivityLedger(session, world.actor, world.db.clock).correct(
            _bo_email_id(world), reason="Wrong date", occurred_at=at(10)
        )
    assert value(world.report(), "contacts_attempted") == 2


def _bo_email_id(world: World) -> str:
    detail = world.pipeline.detail(world.pipeline.board().cards[0].id)
    assert detail is not None
    return next(
        a.id for a in detail.activities if a.contact_name == "Bo" and a.type is ActivityType.EMAIL
    )


def test_activity_counts_and_salesperson_and_lane_filters(world: World, clock: FakeClock) -> None:
    org, ana = world.org("Pixel Forge", at(1), name="Ana")
    data = world.opp(org, at(1))
    marketing = world.opp(
        org, at(1), lane=ProductLane.MIKROS_MARKETING, pipeline=world.other_pipeline
    )
    clock.set(at(25))
    world.pipeline.log_activity(data, ActivityType.REPLY, occurred_at=at(5), contact_id=ana)
    world.other_pipeline.log_activity(
        marketing, ActivityType.REPLY, occurred_at=at(6), contact_id=ana
    )
    world.pipeline.log_activity(data, ActivityType.PROPOSAL, occurred_at=at(7))
    world.pipeline.record_handoff(data, "")
    report = world.report()
    assert (
        value(report, "replies"),
        value(report, "proposals"),
        value(report, "technical_handoffs"),
    ) == (2, 1, 1)
    mine = world.report(filters=KpiFilters(actor_id=world.actor))
    assert value(mine, "replies") == 1
    assert (
        value(mine, "active_opportunities") == 1
    )  # owner filter: the marketing deal is owned by the other person
    assert value(mine, "leads_added") == 1  # created by this salesperson
    theirs = world.report(filters=KpiFilters(actor_id=world.other_actor))
    assert (value(theirs, "replies"), value(theirs, "leads_added")) == (1, 0)
    marketing_only = world.report(filters=KpiFilters(lane=ProductLane.MIKROS_MARKETING))
    assert (value(marketing_only, "replies"), value(marketing_only, "proposals")) == (1, 0)
    assert "all product lanes" in marketing_only.metrics["leads_added"].caption


def test_active_won_lost_and_win_rate(world: World, database: Database) -> None:
    org, _ = world.org("Pixel Forge", at(1, month=9))
    open_deal = world.opp(org, at(2, month=9))
    won_deal = world.opp(org, at(2, month=9))
    lost_deal = world.opp(org, at(2, month=9))
    flip = world.opp(org, at(2, month=9))
    reopened = world.opp(org, at(2, month=9))
    deleted = world.opp(org, at(2, month=9))
    not_fit = world.opp(org, at(2, month=9))
    world.move(won_deal, "won", at(10))
    world.move(lost_deal, "lost", at(11))
    world.move(flip, "lost", at(12))
    world.move(flip, "interested", at(13))
    world.move(flip, "won", at(14))  # counted once, by its last transition: won
    world.move(reopened, "lost", at(15))
    world.move(reopened, "negotiation", at(16))  # ends the period open: not counted as closed
    world.move(not_fit, "not_a_fit", at(17))
    with database.session() as session:
        session.get(Opportunity, deleted).deleted_at_utc = at(20)  # type: ignore[union-attr]
    report = world.report()
    assert (value(report, "won"), value(report, "lost")) == (2, 1)
    assert value(report, "win_rate") == pytest.approx(2 / 3)
    assert "2 of 3" in report.metrics["win_rate"].caption
    active = {r.opportunity_id for r in report.metrics["active_opportunities"].rows}
    assert active == {open_deal, reopened}
    september = world.report(DateRange(date(2026, 9, 1), date(2026, 9, 30)))
    assert value(september, "win_rate") is None  # nothing decided: not available, not 0
    assert value(september, "won") == 0
    assert value(september, "active_opportunities") == 7  # including the one deleted later


def test_stage_durations_conversion_funnel_and_trend(world: World) -> None:
    org, _ = world.org("Pixel Forge", at(1))
    a = world.opp(org, at(1))
    b = world.opp(org, at(1))
    world.move(a, "contacted", at(3))  # 2 days in Discovered, forward
    world.move(b, "contacted", at(5))  # 4 days, forward
    world.move(b, "researching", at(6))  # 1 day in Contacted, backward
    world.move(a, "won", at(9))  # 6 days in Contacted, forward
    report = world.report()
    rows = {s.name: s for s in report.stages}
    assert rows["Discovered"].median_days == pytest.approx(3.0)
    assert rows["Discovered"].conversion == 1.0
    assert rows["Contacted"].exits == 2 and rows["Contacted"].conversion == 0.5
    assert rows["Contacted"].median_days == pytest.approx(3.5)
    assert rows["Negotiation"].median_days is None and rows["Negotiation"].conversion is None
    assert rows["Researching"].at_period_end == 1 and rows["Won"].at_period_end == 1
    funnel = {step.label: step.count for step in report.funnel}
    assert report.funnel_cohort == 2
    assert funnel["Discovered"] == 2 and funnel["Contacted"] == 2 and funnel["Interested"] == 1
    assert funnel["Won"] == 1
    # Trend buckets reconcile with the card totals.
    for series, key in (
        ("Leads added", "leads_added"),
        ("Won", "won"),
        ("Lost", "lost"),
        ("Replies", "replies"),
    ):
        assert sum(report.trend.series[series]) == value(report, key)
    assert len(report.trend.labels) == 31


def test_lead_source_quality(world: World, clock: FakeClock) -> None:
    manual, _ = world.org("Manual Co", at(2))
    world.org("Idle Co", at(3))
    opp = world.opp(manual, at(3))
    world.move(opp, "researching", at(4))
    report = world.report()
    sources = {s.source: s for s in report.sources}
    assert (sources[RecordSource.MANUAL].leads, sources[RecordSource.MANUAL].progressed) == (2, 1)
    assert sources[RecordSource.MANUAL].share == 0.5
    assert sources[RecordSource.IMPORT].share is None  # no leads: not available


def test_follow_ups_are_current_state(world: World) -> None:
    org, _ = world.org("Pixel Forge", at(1))
    soon = world.opp(org, at(1))
    late = world.opp(org, at(1))
    closed = world.opp(org, at(1))
    world.pipeline.update(soon, OpportunityEdit(next_action_at=at(28)))
    world.pipeline.update(late, OpportunityEdit(next_action_at=at(5)))
    world.pipeline.update(closed, OpportunityEdit(next_action_at=at(6)))
    world.move(closed, "lost", at(7))
    report = world.report(now=at(20))
    assert value(report, "follow_ups_due") == 2
    assert value(report, "follow_ups_overdue") == 1
    assert report.metrics["follow_ups_overdue"].current_state


def test_cache_reused_until_data_changes(world: World) -> None:
    world.org("Pixel Forge", at(1))
    world.clock.set(at(31, 22))
    first = world.kpis.dashboard(OCTOBER)
    world.clock.set(at(31, 22))
    assert world.kpis.dashboard(OCTOBER) is first
    world.org("Moon Owl", at(2))
    world.clock.set(at(31, 22))
    second = world.kpis.dashboard(OCTOBER)
    assert second is not first
    assert value(second.report, "leads_added") == 2


def test_release_windows_and_recent_activity(world: World, clock: FakeClock) -> None:
    org, _ = world.org("Pixel Forge", at(1))
    world.prospects.add_game(org, GameDraft("Sky Rails", release_date=date(2027, 1, 15)))
    world.prospects.add_game(org, GameDraft("Old Game", release_date=date(2025, 1, 1)))
    opp = world.opp(org, at(2))
    world.move(opp, "contacted", at(3))
    clock.set(at(31, 22))
    data = world.kpis.dashboard(OCTOBER)
    assert data.releases.labels[0] == "Aug 2026" and len(data.releases.labels) == 8
    assert sum(data.releases.counts) == 1  # the future release; the old one is outside the window
    assert data.releases.rows[0][1] == "Sky Rails"
    kinds = [r.kind for r in data.recent]
    assert "Stage change" in kinds and "Opportunity created" in kinds
    assert data.has_data


def test_empty_database(database: Database, clock: FakeClock) -> None:
    clock.set(at(31, 22))
    data = KpiService(database, zone=NY).dashboard(OCTOBER)
    assert not data.has_data
    assert all(m.value in (0, None) for m in data.report.metrics.values())
    assert data.report.metrics["win_rate"].value is None
    assert StageOutcome.OPEN in {s.outcome for s in data.report.stages}
