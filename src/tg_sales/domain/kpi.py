"""Sales KPIs computed from the activity ledger (see docs/KPI_DICTIONARY.md).

Every function here is pure: it receives plain data loaded by
:mod:`tg_sales.services.kpis` and returns numbers plus the records behind them
(for drill-down). Conventions shared by all metrics:

* Periods are local calendar days converted to a half-open UTC interval
  ``[p0, p1)``; each boundary is converted separately, so daylight-saving
  changes are handled (a day may last 23 or 25 hours).
* Corrections are applied before counting (voided events are ignored, re-timed
  events count at their corrected time; the latest correction wins).
* A count with nothing to count is ``0``; a rate or duration without a
  denominator is ``None`` ("not available").
"""

from __future__ import annotations

import calendar
import itertools
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum

from tg_sales.domain.enums import (
    OUTREACH_ACTIVITY_TYPES,
    ActivityType,
    ProductLane,
    RecordSource,
    StageOutcome,
)
from tg_sales.domain.periods import DateRange

STAGE_TYPES = frozenset({ActivityType.OPPORTUNITY_CREATED, ActivityType.STAGE_CHANGE})
SECONDS_PER_DAY = 86_400


# -- periods ------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    """Inclusive local dates and the matching half-open UTC interval."""

    dates: DateRange
    p0: datetime
    p1: datetime

    @property
    def last_moment(self) -> datetime:
        """The last representable moment of the period (used for "as of the end")."""
        return self.p1 - timedelta(microseconds=1)


def local_midnight_utc(day: date, zone: tzinfo | None = None) -> datetime:
    """UTC time of local midnight starting ``day`` (system zone when ``zone`` is None)."""
    if zone is None:
        return datetime.combine(day, time.min).astimezone(UTC)  # naive = system local time
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)


def period_for(dates: DateRange, zone: tzinfo | None = None) -> Period:
    return Period(
        dates,
        local_midnight_utc(dates.start, zone),
        local_midnight_utc(dates.end + timedelta(days=1), zone),
    )


class BucketSize(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True)
class Bucket:
    label: str
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive


def trend_buckets(period: Period, zone: tzinfo | None = None) -> tuple[BucketSize, list[Bucket]]:
    """Split a period into days (≤ 31 days), weeks (≤ 190 days) or calendar months."""
    start, end = period.dates.start, period.dates.end
    days = period.dates.days
    bounds: list[tuple[str, date, date]] = []  # label, first day, day after last
    if days <= 31:
        size = BucketSize.DAY
        day = start
        while day <= end:
            bounds.append((day.strftime("%d %b"), day, day + timedelta(days=1)))
            day += timedelta(days=1)
    elif days <= 190:
        size = BucketSize.WEEK
        day = start
        while day <= end:
            stop = min(day + timedelta(days=7), end + timedelta(days=1))
            bounds.append((f"Week of {day.strftime('%d %b')}", day, stop))
            day = stop
    else:
        size = BucketSize.MONTH
        day = start
        while day <= end:
            last = calendar.monthrange(day.year, day.month)[1]
            stop = min(date(day.year, day.month, last) + timedelta(days=1), end + timedelta(days=1))
            bounds.append((day.strftime("%b %Y"), day, stop))
            day = stop
    return size, [
        Bucket(label, local_midnight_utc(first, zone), local_midnight_utc(after, zone))
        for label, first, after in bounds
    ]


def bucket_index(buckets: Sequence[Bucket], moment: datetime) -> int | None:
    for index, bucket in enumerate(buckets):
        if bucket.start <= moment < bucket.end:
            return index
    return None


# -- inputs -------------------------------------------------------------------------


@dataclass(frozen=True)
class KpiFilters:
    actor_id: str | None = None  # salesperson
    lane: ProductLane | None = None


@dataclass(frozen=True)
class LedgerEvent:
    id: str
    type: ActivityType
    occurred_at: datetime
    recorded_at: datetime
    actor_id: str | None
    organization_id: str | None
    contact_id: str | None
    opportunity_id: str | None
    stage_id: str | None = None  # target stage of stage-placing events
    to_outcome: StageOutcome | None = None  # outcome recorded on stage events

    @property
    def order(self) -> tuple[datetime, datetime, str]:
        return (self.occurred_at, self.recorded_at, self.id)


@dataclass(frozen=True)
class Correction:
    corrects_event_id: str
    recorded_at: datetime
    event_id: str
    void: bool
    occurred_at: datetime | None


def apply_ledger_corrections(
    events: Iterable[LedgerEvent], corrections: Iterable[Correction]
) -> list[LedgerEvent]:
    """Events after corrections: voided ones removed, re-timed ones moved."""
    latest: dict[str, Correction] = {}
    for correction in sorted(corrections, key=lambda c: (c.recorded_at, c.event_id)):
        latest[correction.corrects_event_id] = correction
    result = []
    for event in events:
        fix = latest.get(event.id)
        if fix is None:
            result.append(event)
        elif fix.void:
            continue
        elif fix.occurred_at is not None:
            result.append(replace(event, occurred_at=fix.occurred_at))
        else:
            result.append(event)
    return result


@dataclass(frozen=True)
class OrganizationRow:
    id: str
    name: str
    source: RecordSource
    created_at: datetime
    deleted_at: datetime | None
    created_by_actor: str | None  # actor of its organization_created event, if any


@dataclass(frozen=True)
class ContactRow:
    id: str
    organization_id: str
    name: str
    created_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True)
class OpportunityRow:
    id: str
    organization_id: str
    title: str | None
    lane: ProductLane
    owner_actor_id: str | None
    deleted_at: datetime | None
    next_action_at: datetime | None
    next_action_note: str | None
    current_stage_open: bool
    outcome_reason: str | None


@dataclass(frozen=True)
class StageRow:
    id: str
    name: str
    sort_order: int
    outcome: StageOutcome


@dataclass(frozen=True)
class KpiInput:
    period: Period
    filters: KpiFilters
    now: datetime
    organizations: Sequence[OrganizationRow]  # created before p1 (for leads and sources)
    contacts: Sequence[ContactRow]  # created in the period
    opportunities: Mapping[str, OpportunityRow]
    stages: Mapping[str, StageRow]
    stage_events: Sequence[LedgerEvent]  # effective, occurred before p1
    activity_events: Sequence[LedgerEvent]  # effective, occurred in [p0, p1)
    organization_names: Mapping[str, str] = field(default_factory=dict)
    contact_names: Mapping[str, str] = field(default_factory=dict)
    zone: tzinfo | None = None  # local time zone for trend buckets (None = system)
    correction_count: int = 0  # corrections recorded during the period


# -- outputs ------------------------------------------------------------------------


class Unit(StrEnum):
    COUNT = "count"
    PERCENT = "percent"
    DAYS = "days"


@dataclass(frozen=True)
class DrillRow:
    when: datetime | None
    organization: str
    detail: str
    opportunity_id: str | None = None
    organization_id: str | None = None


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    value: float | None
    unit: Unit
    caption: str
    rows: tuple[DrillRow, ...] = ()
    current_state: bool = False  # True for "now" metrics not tied to the period


@dataclass(frozen=True)
class StagePerformance:
    stage_id: str
    name: str
    outcome: StageOutcome
    at_period_end: int
    exits: int
    forward_exits: int
    median_days: float | None

    @property
    def conversion(self) -> float | None:
        return None if self.exits == 0 else self.forward_exits / self.exits


@dataclass(frozen=True)
class SourceQuality:
    source: RecordSource
    leads: int
    progressed: int

    @property
    def share(self) -> float | None:
        return None if self.leads == 0 else self.progressed / self.leads


@dataclass(frozen=True)
class Trend:
    size: BucketSize
    labels: tuple[str, ...]
    series: Mapping[str, tuple[int, ...]]


@dataclass(frozen=True)
class FunnelStep:
    label: str
    count: int


@dataclass(frozen=True)
class StageTransition:
    """Stage moves in the period; ``from_stage`` is None for newly created opportunities."""

    from_stage: str | None
    to_stage: str
    count: int


@dataclass(frozen=True)
class ActivityCount:
    """Logged ledger events in the period by salesperson, product lane and type."""

    actor_id: str | None
    lane: ProductLane | None  # None: not linked to an opportunity
    type: ActivityType
    count: int


@dataclass(frozen=True)
class DataQuality:
    """Facts about the data behind a report that affect how far it can be trusted."""

    corrections: int  # corrections recorded in the period
    backdated: int  # events in the period recorded more than a day after they happened
    unowned_opportunities: int  # visible opportunities without a salesperson
    unlinked_activities: int  # activity in the period not linked to an opportunity


@dataclass(frozen=True)
class KpiReport:
    period: Period
    filters: KpiFilters
    metrics: Mapping[str, Metric]
    stages: tuple[StagePerformance, ...]
    sources: tuple[SourceQuality, ...]
    trend: Trend
    funnel: tuple[FunnelStep, ...]
    funnel_cohort: int
    at_period_start: Mapping[str, int] = field(default_factory=dict)  # stage id -> count
    transitions: tuple[StageTransition, ...] = ()
    activity_counts: tuple[ActivityCount, ...] = ()
    quality: DataQuality = DataQuality(0, 0, 0, 0)


# Metric keys, in display order. Labels match the headings of the KPI dictionary.
METRIC_LABELS: dict[str, str] = {
    "leads_added": "Leads added",
    "contacts_added": "Contacts added",
    "contacts_attempted": "Unique contacts attempted",
    "replies": "Replies",
    "active_opportunities": "Active opportunities",
    "technical_handoffs": "Technical handoffs",
    "proposals": "Proposals",
    "won": "Won",
    "lost": "Lost",
    "win_rate": "Win rate",
    "follow_ups_due": "Follow-ups due",
    "follow_ups_overdue": "Follow-ups overdue",
}


# -- helpers ------------------------------------------------------------------------


def _live(deleted_at: datetime | None, moment: datetime) -> bool:
    return deleted_at is None or deleted_at >= moment


def _opportunity_matches(opp: OpportunityRow | None, filters: KpiFilters) -> bool:
    if opp is None:
        return False
    if filters.lane is not None and opp.lane is not filters.lane:
        return False
    return filters.actor_id is None or opp.owner_actor_id == filters.actor_id


def _activity_matches(
    event: LedgerEvent, data: KpiInput, opportunities: Mapping[str, OpportunityRow]
) -> bool:
    filters = data.filters
    if filters.actor_id is not None and event.actor_id != filters.actor_id:
        return False
    if filters.lane is None:
        return True
    opp = opportunities.get(event.opportunity_id or "")
    return opp is not None and opp.lane is filters.lane


def _event_outcome(event: LedgerEvent, stages: Mapping[str, StageRow]) -> StageOutcome | None:
    if event.to_outcome is not None:
        return event.to_outcome
    stage = stages.get(event.stage_id or "")
    return stage.outcome if stage else None


def _org(data: KpiInput, organization_id: str | None) -> str:
    return data.organization_names.get(organization_id or "", "Unknown prospect")


def _opp_label(opp: OpportunityRow) -> str:
    return opp.title or opp.lane.value.replace("_", " ").capitalize()


def _plural(count: int, word: str) -> str:
    return f"{count:,} {word}{'' if count == 1 else 's'}"


# -- metrics ------------------------------------------------------------------------


def stages_at(events: Sequence[LedgerEvent], moment: datetime) -> dict[str, LedgerEvent]:
    """Latest stage-placing event per opportunity at or before ``moment``."""
    current: dict[str, LedgerEvent] = {}
    for event in events:
        if event.opportunity_id is None or event.occurred_at > moment:
            continue
        previous = current.get(event.opportunity_id)
        if previous is None or event.order > previous.order:
            current[event.opportunity_id] = event
    return current


def _closings(
    data: KpiInput, opportunities: Mapping[str, OpportunityRow]
) -> dict[str, LedgerEvent]:
    """Per opportunity, its last stage event in the period, when that event closes it."""
    last: dict[str, LedgerEvent] = {}
    for event in data.stage_events:
        if not (data.period.p0 <= event.occurred_at < data.period.p1):
            continue
        opp_id = event.opportunity_id or ""
        if opp_id not in opportunities:
            continue
        previous = last.get(opp_id)
        if previous is None or event.order > previous.order:
            last[opp_id] = event
    return {
        opp_id: event
        for opp_id, event in last.items()
        if (_event_outcome(event, data.stages) or StageOutcome.OPEN).is_terminal
    }


def compute(data: KpiInput) -> KpiReport:
    period, filters = data.period, data.filters
    p0, p1, end = period.p0, period.p1, period.last_moment
    metrics: dict[str, Metric] = {}

    def add(
        key: str,
        value: float | None,
        caption: str,
        rows: Iterable[DrillRow] = (),
        unit: Unit = Unit.COUNT,
        current: bool = False,
    ) -> None:
        ordered = sorted(
            rows, key=lambda r: r.when or datetime.min.replace(tzinfo=UTC), reverse=True
        )
        metrics[key] = Metric(
            key, METRIC_LABELS[key], value, unit, caption, tuple(ordered), current
        )

    # Opportunities visible to this report: filters match and not deleted by the period end.
    opportunities = {
        opp_id: opp
        for opp_id, opp in data.opportunities.items()
        if _opportunity_matches(opp, filters) and _live(opp.deleted_at, p1)
    }

    # Leads and contacts added.
    leads = [
        o
        for o in data.organizations
        if p0 <= o.created_at < p1
        and _live(o.deleted_at, p1)
        and (filters.actor_id is None or o.created_by_actor == filters.actor_id)
    ]
    lane_note = " (all product lanes)" if filters.lane is not None else ""
    add(
        "leads_added",
        len(leads),
        f"New prospects{lane_note}",
        (
            DrillRow(o.created_at, o.name, f"Source: {o.source.value}", organization_id=o.id)
            for o in leads
        ),
    )
    contacts = [c for c in data.contacts if p0 <= c.created_at < p1 and _live(c.deleted_at, p1)]
    add(
        "contacts_added",
        len(contacts),
        "New contacts (not filtered)",
        (
            DrillRow(
                c.created_at,
                _org(data, c.organization_id),
                c.name,
                organization_id=c.organization_id,
            )
            for c in contacts
        ),
    )

    # Activity-based counts.
    activity = [e for e in data.activity_events if _activity_matches(e, data, opportunities)]
    attempts: dict[str, list[LedgerEvent]] = defaultdict(list)
    for event in activity:
        if event.type in OUTREACH_ACTIVITY_TYPES and event.contact_id is not None:
            attempts[event.contact_id].append(event)
    add(
        "contacts_attempted",
        len(attempts),
        "Contacts with logged outreach",
        (
            DrillRow(
                max(e.occurred_at for e in events),
                _org(data, events[0].organization_id),
                f"{data.contact_names.get(contact_id, 'Contact')} · "
                f"{_plural(len(events), 'attempt')}",
                events[0].opportunity_id,
                events[0].organization_id,
            )
            for contact_id, events in attempts.items()
        ),
    )
    for key, kind, caption in (
        ("replies", ActivityType.REPLY, "Replies logged"),
        ("technical_handoffs", ActivityType.TECHNICAL_HANDOFF, "Technical handoffs logged"),
        ("proposals", ActivityType.PROPOSAL, "Proposals logged"),
    ):
        events = [e for e in activity if e.type is kind]
        add(
            key,
            len(events),
            caption,
            (
                DrillRow(
                    e.occurred_at,
                    _org(data, e.organization_id),
                    data.contact_names.get(e.contact_id or "", ""),
                    e.opportunity_id,
                    e.organization_id,
                )
                for e in events
            ),
        )

    # Pipeline state at the end of the period.
    placed = {
        opp_id: event
        for opp_id, event in stages_at(data.stage_events, end).items()
        if opp_id in opportunities
    }
    active = {
        opp_id: event
        for opp_id, event in placed.items()
        if (stage := data.stages.get(event.stage_id or "")) is not None
        and stage.outcome is StageOutcome.OPEN
    }
    add(
        "active_opportunities",
        len(active),
        "Open at period end",
        (
            DrillRow(
                event.occurred_at,
                _org(data, opportunities[opp_id].organization_id),
                f"{_opp_label(opportunities[opp_id])} · {data.stages[event.stage_id or ''].name}",
                opp_id,
                opportunities[opp_id].organization_id,
            )
            for opp_id, event in active.items()
        ),
    )

    # Won, lost and win rate.
    closings = _closings(data, opportunities)
    by_outcome: dict[StageOutcome, list[tuple[str, LedgerEvent]]] = defaultdict(list)
    for opp_id, event in closings.items():
        outcome = _event_outcome(event, data.stages)
        if outcome is not None:
            by_outcome[outcome].append((opp_id, event))

    def closing_rows(items: Iterable[tuple[str, LedgerEvent]]) -> Iterable[DrillRow]:
        for opp_id, event in items:
            opp = opportunities[opp_id]
            reason = f" · {opp.outcome_reason}" if opp.outcome_reason else ""
            stage = data.stages.get(event.stage_id or "")
            yield DrillRow(
                event.occurred_at,
                _org(data, opp.organization_id),
                f"{_opp_label(opp)} · {stage.name if stage else ''}{reason}",
                opp_id,
                opp.organization_id,
            )

    won, lost = by_outcome[StageOutcome.WON], by_outcome[StageOutcome.LOST]
    add("won", len(won), "Closed as won", closing_rows(won))
    add("lost", len(lost), "Closed as lost", closing_rows(lost))
    decided = len(won) + len(lost)
    add(
        "win_rate",
        None if decided == 0 else len(won) / decided,
        f"Won ÷ (won + lost): {len(won)} of {decided}" if decided else "None won or lost yet",
        closing_rows([*won, *lost]),
        unit=Unit.PERCENT,
    )

    # Follow-ups (current state).
    follow = [
        o
        for o in opportunities.values()
        if o.current_stage_open and o.next_action_at is not None and o.deleted_at is None
    ]

    def follow_rows(items: Iterable[OpportunityRow]) -> Iterable[DrillRow]:
        for opp in items:
            yield DrillRow(
                opp.next_action_at,
                _org(data, opp.organization_id),
                f"{_opp_label(opp)} · {opp.next_action_note or 'Next action'}",
                opp.id,
                opp.organization_id,
            )

    due = [o for o in follow if o.next_action_at is not None and p0 <= o.next_action_at < p1]
    overdue = [o for o in follow if o.next_action_at is not None and o.next_action_at < data.now]
    add(
        "follow_ups_due",
        len(due),
        "Next actions in the period",
        follow_rows(due),
        current=True,
    )
    add(
        "follow_ups_overdue",
        len(overdue),
        "Next actions past due",
        follow_rows(overdue),
        current=True,
    )

    at_start: dict[str, int] = defaultdict(int)
    for opp_id, event in stages_at(data.stage_events, p0 - timedelta(microseconds=1)).items():
        if opp_id in opportunities:
            at_start[event.stage_id or ""] += 1
    activity_counts: dict[tuple[str | None, ProductLane | None, ActivityType], int] = defaultdict(
        int
    )
    for event in activity:
        opp = opportunities.get(event.opportunity_id or "")
        activity_counts[(event.actor_id, opp.lane if opp else None, event.type)] += 1
    quality = DataQuality(
        corrections=data.correction_count,
        backdated=sum(
            1 for e in activity if (e.recorded_at - e.occurred_at).total_seconds() > SECONDS_PER_DAY
        ),
        unowned_opportunities=sum(1 for o in opportunities.values() if o.owner_actor_id is None),
        unlinked_activities=sum(1 for e in data.activity_events if e.opportunity_id is None),
    )

    return KpiReport(
        at_period_start=dict(at_start),
        transitions=tuple(_stage_transitions(data, opportunities)),
        activity_counts=tuple(
            ActivityCount(actor, lane, kind, count)
            for (actor, lane, kind), count in sorted(
                activity_counts.items(),
                key=lambda item: (item[0][0] or "", str(item[0][1] or ""), item[0][2].value),
            )
        ),
        quality=quality,
        period=period,
        filters=filters,
        metrics=metrics,
        stages=tuple(_stage_performance(data, opportunities, placed)),
        sources=tuple(_source_quality(data, leads, opportunities)),
        trend=_trend(data, leads, activity, closings),
        funnel=tuple(_funnel(data, opportunities)),
        funnel_cohort=sum(
            1
            for e in data.stage_events
            if e.type is ActivityType.OPPORTUNITY_CREATED
            and p0 <= e.occurred_at < p1
            and (e.opportunity_id or "") in opportunities
        ),
    )


def _transitions(
    events: Sequence[LedgerEvent], opportunities: Mapping[str, OpportunityRow]
) -> dict[str, list[LedgerEvent]]:
    by_opp: dict[str, list[LedgerEvent]] = defaultdict(list)
    for event in events:
        if (event.opportunity_id or "") in opportunities:
            by_opp[event.opportunity_id or ""].append(event)
    for items in by_opp.values():
        items.sort(key=lambda e: e.order)
    return by_opp


def _stage_transitions(
    data: KpiInput, opportunities: Mapping[str, OpportunityRow]
) -> Iterable[StageTransition]:
    counts: dict[tuple[str | None, str], int] = defaultdict(int)

    def name(stage_id: str | None) -> str:
        stage = data.stages.get(stage_id or "")
        return stage.name if stage else "Removed stage"

    for items in _transitions(data.stage_events, opportunities).values():
        previous: LedgerEvent | None = None
        for event in items:
            in_period = data.period.p0 <= event.occurred_at < data.period.p1
            if in_period:
                if event.type is ActivityType.OPPORTUNITY_CREATED or previous is None:
                    counts[(None, name(event.stage_id))] += 1
                elif previous.stage_id != event.stage_id:
                    counts[(name(previous.stage_id), name(event.stage_id))] += 1
            previous = event
    order = {s.name: s.sort_order for s in data.stages.values()}
    for (source, target), count in sorted(
        counts.items(),
        key=lambda item: (
            -1 if item[0][0] is None else order.get(item[0][0], 999),
            order.get(item[0][1], 999),
        ),
    ):
        yield StageTransition(source, target, count)


def _stage_performance(
    data: KpiInput,
    opportunities: Mapping[str, OpportunityRow],
    placed: Mapping[str, LedgerEvent],
) -> Iterable[StagePerformance]:
    durations: dict[str, list[float]] = defaultdict(list)
    forward: dict[str, int] = defaultdict(int)
    for items in _transitions(data.stage_events, opportunities).values():
        for current, following in itertools.pairwise(items):
            if current.stage_id == following.stage_id:
                continue
            if not (data.period.p0 <= following.occurred_at < data.period.p1):
                continue
            stage_id = current.stage_id or ""
            seconds = (following.occurred_at - current.occurred_at).total_seconds()
            durations[stage_id].append(max(0.0, seconds) / SECONDS_PER_DAY)
            source = data.stages.get(stage_id)
            target = data.stages.get(following.stage_id or "")
            if source and target and target.sort_order > source.sort_order:
                forward[stage_id] += 1
    at_end: dict[str, int] = defaultdict(int)
    for event in placed.values():
        at_end[event.stage_id or ""] += 1
    for stage in sorted(data.stages.values(), key=lambda s: (s.sort_order, s.name)):
        values = durations.get(stage.id, [])
        yield StagePerformance(
            stage.id,
            stage.name,
            stage.outcome,
            at_end.get(stage.id, 0),
            len(values),
            forward.get(stage.id, 0),
            statistics.median(values) if values else None,
        )


def _source_quality(
    data: KpiInput, leads: Sequence[OrganizationRow], opportunities: Mapping[str, OpportunityRow]
) -> Iterable[SourceQuality]:
    open_orders = sorted(
        s.sort_order for s in data.stages.values() if s.outcome is StageOutcome.OPEN
    )
    first_open = open_orders[0] if open_orders else None
    progressed_orgs: set[str] = set()
    for event in data.stage_events:
        opp = opportunities.get(event.opportunity_id or "")
        stage = data.stages.get(event.stage_id or "")
        if opp is None or stage is None:
            continue
        outcome = _event_outcome(event, data.stages)
        beyond_first = (
            stage.outcome is StageOutcome.OPEN
            and first_open is not None
            and stage.sort_order > first_open
        )
        if beyond_first or outcome is StageOutcome.WON:
            progressed_orgs.add(opp.organization_id)
    counts: dict[RecordSource, list[int]] = {}
    for lead in leads:
        bucket = counts.setdefault(lead.source, [0, 0])
        bucket[0] += 1
        if lead.id in progressed_orgs:
            bucket[1] += 1
    for source in RecordSource:
        if source is RecordSource.SYSTEM:
            continue
        leads_count, progressed = counts.get(source, [0, 0])
        yield SourceQuality(source, leads_count, progressed)


def _trend(
    data: KpiInput,
    leads: Sequence[OrganizationRow],
    activity: Sequence[LedgerEvent],
    closings: Mapping[str, LedgerEvent],
) -> Trend:
    size, buckets = trend_buckets(data.period, data.zone)
    series: dict[str, list[int]] = {
        name: [0] * len(buckets) for name in ("Leads added", "Replies", "Won", "Lost")
    }

    def bump(name: str, moment: datetime) -> None:
        index = bucket_index(buckets, moment)
        if index is not None:
            series[name][index] += 1

    for lead in leads:
        bump("Leads added", lead.created_at)
    for event in activity:
        if event.type is ActivityType.REPLY:
            bump("Replies", event.occurred_at)
    for event in closings.values():
        outcome = _event_outcome(event, data.stages)
        if outcome is StageOutcome.WON:
            bump("Won", event.occurred_at)
        elif outcome is StageOutcome.LOST:
            bump("Lost", event.occurred_at)
    return Trend(size, tuple(b.label for b in buckets), {k: tuple(v) for k, v in series.items()})


def _funnel(data: KpiInput, opportunities: Mapping[str, OpportunityRow]) -> Iterable[FunnelStep]:
    """For opportunities created in the period: how many reached at least each open stage."""
    open_stages = sorted(
        (s for s in data.stages.values() if s.outcome is StageOutcome.OPEN),
        key=lambda s: s.sort_order,
    )
    cohort = {
        e.opportunity_id
        for e in data.stage_events
        if e.type is ActivityType.OPPORTUNITY_CREATED
        and data.period.p0 <= e.occurred_at < data.period.p1
        and (e.opportunity_id or "") in opportunities
    }
    furthest: dict[str, int] = {}
    won: set[str] = set()
    for event in data.stage_events:
        if event.opportunity_id not in cohort:
            continue
        stage = data.stages.get(event.stage_id or "")
        if stage is None:
            continue
        if stage.outcome is StageOutcome.OPEN:
            furthest[event.opportunity_id or ""] = max(
                furthest.get(event.opportunity_id or "", -1), stage.sort_order
            )
        elif _event_outcome(event, data.stages) is StageOutcome.WON:
            won.add(event.opportunity_id or "")
    for stage in open_stages:
        count = sum(
            1 for opp in cohort if opp in won or furthest.get(opp or "", -1) >= stage.sort_order
        )
        yield FunnelStep(stage.name, count)
    yield FunnelStep("Won", len(won))
