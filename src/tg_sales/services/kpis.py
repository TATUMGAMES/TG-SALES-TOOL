"""Dashboard data: KPIs for a period and filters, plus release windows and recent activity.

Results are cached per (period, filters, minute) and reused while the
database is unchanged; a cheap version token (latest change times and row
counts, all indexed) detects any change, including sync and imports. The work
is safe to run on a background thread.
"""

from __future__ import annotations

import calendar
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from sqlalchemy.orm import Session

from tg_sales.cancellation import CancelToken
from tg_sales.db.database import Database
from tg_sales.domain.kpi import (
    KpiFilters,
    KpiInput,
    KpiReport,
    OpportunityRow,
    apply_ledger_corrections,
    compute,
    period_for,
)
from tg_sales.domain.opportunities import ACTIVITY_LABELS
from tg_sales.domain.periods import DateRange
from tg_sales.domain.time import to_local
from tg_sales.repositories.kpis import KpiRepository
from tg_sales.repositories.pipeline import PipelineRepository
from tg_sales.services.timeline import summarize

RECENT_LIMIT = 50
# Results are reused while the data is unchanged and they are this recent, so
# time-dependent values (overdue follow-ups) stay current.
CACHE_SECONDS = 60
RELEASE_MONTHS_BEFORE = 2
RELEASE_MONTHS_AFTER = 5

ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class RecentActivity:
    occurred_at: datetime
    kind: str
    organization: str
    summary: str
    opportunity_id: str | None
    voided: bool


@dataclass(frozen=True)
class ReleaseWindows:
    labels: tuple[str, ...]
    counts: tuple[int, ...]
    rows: tuple[tuple[date, str, str], ...]  # release date, game, prospect


@dataclass(frozen=True)
class DashboardData:
    report: KpiReport
    recent: tuple[RecentActivity, ...]
    releases: ReleaseWindows
    computed_at: datetime
    has_data: bool


def _month_start(day: date, offset: int) -> date:
    index = day.year * 12 + day.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


class KpiService:
    def __init__(self, database: Database, zone: tzinfo | None = None) -> None:
        self._database = database
        self._zone = zone
        self._lock = threading.Lock()
        self._cache: dict[tuple[object, ...], tuple[tuple[object, ...], DashboardData]] = {}

    def now(self) -> datetime:
        return self._database.clock.now()

    def today(self) -> date:
        return to_local(self.now(), self._zone).date()

    def actors(self) -> list[tuple[str, str]]:
        with self._database.session() as session:
            return KpiRepository(session).actors()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    def dashboard(
        self,
        dates: DateRange,
        filters: KpiFilters = KpiFilters(),  # noqa: B008 - immutable default
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> DashboardData:
        now = self.now()
        key = (dates.start, dates.end, filters)
        with self._database.session() as session:
            version = KpiRepository(session).version_token()
        with self._lock:
            cached = self._cache.get(key)
        if (
            cached is not None
            and cached[0] == version
            and timedelta(0) <= now - cached[1].computed_at < timedelta(seconds=CACHE_SECONDS)
        ):
            return cached[1]
        data = self._compute(dates, filters, now, token, progress)
        with self._lock:
            if len(self._cache) > 32:
                self._cache.clear()
            self._cache[key] = (version, data)
        return data

    def _compute(
        self,
        dates: DateRange,
        filters: KpiFilters,
        now: datetime,
        token: CancelToken | None,
        progress: ProgressCallback | None,
    ) -> DashboardData:
        def step(percent: int, message: str) -> None:
            if token is not None:
                token.raise_if_cancelled()
            if progress is not None:
                progress(percent, message)

        period = period_for(dates, self._zone)
        with self._database.session() as session:
            repo = KpiRepository(session)
            step(5, "Reading history…")
            corrections = repo.corrections()
            retimed = {c.corrects_event_id for c in corrections if c.occurred_at is not None}
            stage_events = apply_ledger_corrections(
                repo.stage_events(period.p1, retimed), corrections
            )
            stage_events = [e for e in stage_events if e.occurred_at < period.p1]
            step(35, "Reading activity…")
            activity = apply_ledger_corrections(
                repo.activity_events(period.p0, period.p1, retimed), corrections
            )
            activity = [e for e in activity if period.p0 <= e.occurred_at < period.p1]
            step(55, "Reading prospects…")
            organizations = repo.organizations_created(period.p0, period.p1)
            contacts = repo.contacts_created(period.p0, period.p1)
            opportunities = repo.opportunities()
            stages = repo.stages()
            org_ids = {o.organization_id for o in opportunities.values()}
            org_ids |= {e.organization_id for e in activity if e.organization_id}
            org_ids |= {c.organization_id for c in contacts}
            names = repo.organization_names(org_ids)
            contact_names = repo.contact_names({e.contact_id for e in activity if e.contact_id})
            step(75, "Calculating…")
            report = compute(
                KpiInput(
                    period=period,
                    filters=filters,
                    now=now,
                    organizations=organizations,
                    contacts=contacts,
                    opportunities=opportunities,
                    stages=stages,
                    stage_events=stage_events,
                    activity_events=activity,
                    organization_names=names,
                    contact_names=contact_names,
                    zone=self._zone,
                    correction_count=sum(
                        1 for c in corrections if period.p0 <= c.recorded_at < period.p1
                    ),
                )
            )
            step(90, "Collecting recent activity…")
            recent = self._recent(
                repo, session, period.p0, period.p1, filters, opportunities, names
            )
            releases = self._releases(repo)
            has_data = repo.has_data()
        step(100, "Done")
        return DashboardData(report, recent, releases, now, has_data)

    def _recent(
        self,
        repo: KpiRepository,
        session: Session,
        start: datetime,
        end: datetime,
        filters: KpiFilters,
        opportunities: Mapping[str, OpportunityRow],
        names: Mapping[str, str],
    ) -> tuple[RecentActivity, ...]:
        stage_names = {s.id: s.name for s in repo.stages().values()}
        rows = repo.recent_activities(start, end, RECENT_LIMIT * 4)
        voided = PipelineRepository(session).voided_event_ids([a.id for a in rows])
        result = []
        for activity in rows:
            if filters.actor_id is not None and activity.actor_id != filters.actor_id:
                continue
            if filters.lane is not None:
                opp = opportunities.get(activity.opportunity_id or "")
                if opp is None or opp.lane is not filters.lane:
                    continue
            result.append(
                RecentActivity(
                    activity.occurred_at_utc,
                    ACTIVITY_LABELS.get(activity.type, activity.type.value),
                    names.get(activity.organization_id or "", "")
                    if activity.organization_id
                    else "",
                    summarize(activity, stage_names),
                    activity.opportunity_id,
                    activity.id in voided,
                )
            )
            if len(result) >= RECENT_LIMIT:
                break
        return tuple(result)

    def _releases(self, repo: KpiRepository) -> ReleaseWindows:
        today = self.today()
        first = _month_start(today, -RELEASE_MONTHS_BEFORE)
        after = _month_start(today, RELEASE_MONTHS_AFTER + 1)
        rows = repo.release_dates(first, after - timedelta(days=1))
        labels = []
        counts = []
        month = first
        while month < after:
            last = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
            labels.append(month.strftime("%b %Y"))
            counts.append(sum(1 for day, _, _ in rows if month <= day <= last))
            month = _month_start(month, 1)
        return ReleaseWindows(tuple(labels), tuple(counts), tuple(rows))
