"""Report content: sections, tables and charts built from KPI results.

Every number comes from the same KPI calculation as the dashboard
(:mod:`tg_sales.domain.kpi`), so a report and the dashboard agree for the same
period and filters. Tables name the definition they follow; data that cannot
be known is shown as "Not available", and no qualitative conclusions are
generated: "notable progress" lists recorded facts only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, tzinfo

from tg_sales.domain.enums import ActivityType, ProductLane, RecordSource, StageOutcome
from tg_sales.domain.kpi import METRIC_LABELS, DrillRow, KpiFilters, KpiReport, Metric, Unit
from tg_sales.domain.opportunities import ACTIVITY_LABELS
from tg_sales.domain.periods import DateRange, describe_range
from tg_sales.domain.time import to_local

NOT_AVAILABLE = "Not available"
PDF_ROW_LIMIT = 25  # longer lists are complete in the CSV files

LANE_LABELS: dict[ProductLane, str] = {
    ProductLane.DATA_LICENSING: "Data licensing",
    ProductLane.PUBLISHER_PARTNERSHIP: "Publisher partnership",
    ProductLane.MIKROS_MARKETING: "MIKROS Marketing",
}
SOURCE_LABELS: dict[RecordSource, str] = {
    RecordSource.MANUAL: "Added manually",
    RecordSource.IMPORT: "Imported",
    RecordSource.DISCOVERY: "Game discovery",
    RecordSource.SYNC: "Synced from another computer",
    RecordSource.SYSTEM: "Built in",
}

# One-line definitions matching docs/KPI_DICTIONARY.md (section names in brackets).
DEFINITIONS: dict[str, str] = {
    "leads_added": "Prospects (organizations) created in the period and not deleted by its end. "
    "[Leads added]",
    "contacts_added": "Contacts created in the period and not deleted by its end; not filtered "
    "by salesperson or lane. [Contacts added]",
    "contacts_attempted": "Distinct contacts with at least one logged outreach (contacted, "
    "email, LinkedIn invite or message, phone call) dated in the period. "
    "[Unique contacts attempted]",
    "replies": "Logged replies dated in the period. [Replies]",
    "active_opportunities": "Opportunities in an open stage at the last moment of the period. "
    "[Active conversations / active opportunities]",
    "technical_handoffs": "Logged technical handoffs dated in the period. "
    "[Technical handoffs and proposals]",
    "proposals": "Logged proposals dated in the period. [Technical handoffs and proposals]",
    "won": "Opportunities whose last stage move in the period closed them as won. [Won and lost]",
    "lost": "Opportunities whose last stage move in the period closed them as lost. [Won and lost]",
    "win_rate": "Won ÷ (won + lost) for the period; not available when nothing was won or "
    "lost. [Win rate]",
    "follow_ups_due": "Open opportunities whose next action falls in the period (current "
    "follow-up dates). [Follow-ups due and overdue]",
    "follow_ups_overdue": "Open opportunities whose next action is before the time the report "
    "was generated (current state). [Follow-ups due and overdue]",
    "stage_distribution": "Each opportunity's stage at a moment is the target of its latest "
    "stage event at or before that moment. [Pipeline stage distribution]",
    "transitions": "Stage moves dated in the period; new opportunities are counted from "
    "“New”. [Pipeline stage distribution]",
    "activity": "Logged ledger events dated in the period, by the salesperson who recorded "
    "them and the product lane of the linked opportunity. [Conventions: attribution]",
    "sources": "Leads added in the period per source, and how many reached an open stage "
    "beyond the first one, or won, by the end of the period. [Lead-source quality]",
    "trend": "Leads added, replies, won and lost per day, week or month of the period; each "
    "series adds up to its summary number. [Trends]",
}


@dataclass(frozen=True)
class Table:
    key: str  # CSV file name (without extension)
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    definition: str | None = None
    empty_text: str = "Nothing recorded in this period."
    note: str | None = None


@dataclass(frozen=True)
class Chart:
    key: str
    title: str
    labels: tuple[str, ...]
    series: Mapping[str, tuple[float, ...]]
    kind: str = "bar"  # "bar" or "line"
    y_label: str = "Count"


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    paragraphs: tuple[str, ...] = ()
    tables: tuple[Table, ...] = ()
    charts: tuple[Chart, ...] = ()
    bullets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportMeta:
    dates: DateRange
    period_label: str  # e.g. "Last 3 months" or "Custom range"
    filters: KpiFilters
    salesperson: str | None  # display name of the filtered salesperson
    generated_at: datetime  # UTC
    app_version: str
    zone: tzinfo | None = None

    @property
    def filter_text(self) -> str:
        parts = [
            f"Salesperson: {self.salesperson or 'All'}",
            f"Product lane: {LANE_LABELS[self.filters.lane] if self.filters.lane else 'All'}",
        ]
        return " · ".join(parts)

    def local(self, moment: datetime | None) -> str:
        if moment is None:
            return ""
        return to_local(moment, self.zone).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class ReportContent:
    meta: ReportMeta
    title: str
    subtitle: str
    sections: tuple[Section, ...]
    caveats: tuple[str, ...] = field(default=())

    def tables(self) -> list[Table]:
        return [t for s in self.sections for t in s.tables]


def format_value(metric: Metric | None) -> str:
    if metric is None or metric.value is None:
        return NOT_AVAILABLE
    if metric.unit is Unit.PERCENT:
        return f"{metric.value:.0%}"
    if metric.unit is Unit.DAYS:
        return f"{metric.value:.1f} days"
    return f"{metric.value:,.0f}"


def _change(current: Metric | None, previous: Metric | None) -> str:
    if (
        current is None
        or previous is None
        or current.value is None
        or previous.value is None
        or current.current_state
    ):
        return NOT_AVAILABLE if current is None or current.value is None else "—"
    delta = current.value - previous.value
    if current.unit is Unit.PERCENT:
        points = round(delta * 100)
        return f"{points:+d} points" if points else "No change"
    return f"{delta:+,.0f}" if delta else "No change"


def _signed(value: int) -> str:
    return f"{value:+d}" if value else "0"


def _drill_rows(meta: ReportMeta, rows: Sequence[DrillRow]) -> tuple[tuple[object, ...], ...]:
    return tuple((meta.local(r.when), r.organization, r.detail) for r in rows)


def _drill_table(meta: ReportMeta, key: str, title: str, metric: Metric | None) -> Table:
    rows = metric.rows if metric else ()
    return Table(
        key=key,
        title=title,
        columns=("When", "Prospect", "Detail"),
        rows=_drill_rows(meta, rows),
        definition=DEFINITIONS.get(metric.key if metric else key),
    )


def build_report(
    meta: ReportMeta,
    report: KpiReport,
    previous: KpiReport,
    actor_names: Mapping[str, str],
) -> ReportContent:
    """Assemble the report. ``previous`` covers the same-length period just before."""
    m = report.metrics
    pm = previous.metrics
    stage_names = {s.stage_id: s.name for s in report.stages}

    summary_rows = []
    for key, label in METRIC_LABELS.items():
        metric = m.get(key)
        label_text = label + (" (now)" if metric is not None and metric.current_state else "")
        summary_rows.append(
            (
                label_text,
                format_value(metric),
                "—" if metric is not None and metric.current_state else format_value(pm.get(key)),
                _change(metric, pm.get(key)),
            )
        )
    prev_dates = previous.period.dates
    executive = Section(
        "summary",
        "Executive summary",
        paragraphs=(
            f"Period: {describe_range(meta.dates)}, {meta.period_label.lower()}. "
            f"Compared with the previous {meta.dates.days} days "
            f"({prev_dates.start.isoformat()} to {prev_dates.end.isoformat()}).",
            f"{meta.filter_text}. Counts follow the definitions listed with each table and "
            "in the Definitions section.",
        ),
        tables=(
            Table(
                "summary",
                "Key numbers",
                ("Measure", "This period", "Previous period", "Change"),
                tuple(summary_rows),
                note="“(now)” marks current-state measures, calculated when the report was "
                "generated; they have no previous-period value.",
            ),
        ),
    )

    sources_rows = tuple(
        (
            SOURCE_LABELS[s.source],
            s.leads,
            s.progressed,
            f"{s.progressed / s.leads:.0%}" if s.leads else NOT_AVAILABLE,
        )
        for s in report.sources
    )
    acquisition = Section(
        "acquisition",
        "Lead acquisition",
        paragraphs=(
            f"{format_value(m.get('leads_added'))} leads and "
            f"{format_value(m.get('contacts_added'))} contacts were added.",
        ),
        tables=(
            _drill_table(meta, "leads_added", "Leads added", m.get("leads_added")),
            _drill_table(meta, "contacts_added", "Contacts added", m.get("contacts_added")),
        ),
    )
    outreach = Section(
        "outreach",
        "Contacted and responded",
        paragraphs=(
            f"{format_value(m.get('contacts_attempted'))} contacts were attempted and "
            f"{format_value(m.get('replies'))} replies were logged.",
        ),
        tables=(
            _drill_table(
                meta, "contacts_attempted", "Contacts attempted", m.get("contacts_attempted")
            ),
            _drill_table(meta, "replies", "Replies", m.get("replies")),
        ),
    )

    distribution_rows = tuple(
        (
            s.name,
            report.at_period_start.get(s.stage_id, 0),
            s.at_period_end,
            _signed(s.at_period_end - report.at_period_start.get(s.stage_id, 0)),
        )
        for s in report.stages
    )
    removed = sum(v for k, v in report.at_period_start.items() if k not in stage_names)
    stages_section = Section(
        "stages",
        "Opportunity stages",
        paragraphs=(
            f"Stage distribution at the start ({meta.dates.start.isoformat()} 00:00) and end "
            f"({meta.dates.end.isoformat()} 23:59) of the period.",
        ),
        tables=(
            Table(
                "stage_distribution",
                "Stage distribution",
                ("Stage", "At start", "At end", "Change"),
                distribution_rows,
                DEFINITIONS["stage_distribution"],
                note=f"{removed} opportunities were in stages that no longer exist."
                if removed
                else None,
            ),
            Table(
                "stage_transitions",
                "Stage transitions",
                ("From", "To", "Opportunities"),
                tuple((t.from_stage or "New", t.to_stage, t.count) for t in report.transitions),
                DEFINITIONS["transitions"],
            ),
            Table(
                "stage_performance",
                "Stage performance",
                ("Stage", "Exits", "Moved forward", "Conversion", "Median days in stage"),
                tuple(
                    (
                        s.name,
                        s.exits,
                        s.forward_exits,
                        f"{s.forward_exits / s.exits:.0%}" if s.exits else NOT_AVAILABLE,
                        f"{s.median_days:.1f}" if s.median_days is not None else NOT_AVAILABLE,
                    )
                    for s in report.stages
                    if s.outcome is StageOutcome.OPEN
                ),
                "Exits and median time in stage use moves out of each stage dated in the "
                "period. [Median time in stage] [Stage conversion rate]",
            ),
        ),
    )

    outcomes = Section(
        "outcomes",
        "Wins and losses",
        paragraphs=(
            f"Won: {format_value(m.get('won'))}. Lost: {format_value(m.get('lost'))}. "
            f"Win rate: {format_value(m.get('win_rate'))}. Reasons are shown as recorded "
            "when the opportunity was closed.",
        ),
        tables=(
            _drill_table(meta, "won", "Won", m.get("won")),
            _drill_table(meta, "lost", "Lost", m.get("lost")),
        ),
    )

    by_actor: dict[str, dict[ActivityType, int]] = defaultdict(lambda: defaultdict(int))
    by_lane: dict[str, int] = defaultdict(int)
    for count in report.activity_counts:
        actor = actor_names.get(count.actor_id or "", "Unknown")
        by_actor[actor][count.type] += count.count
        by_lane[LANE_LABELS[count.lane] if count.lane else "Not linked to an opportunity"] += (
            count.count
        )
    types = sorted({c.type for c in report.activity_counts}, key=lambda t: t.value)
    activity = Section(
        "activity",
        "Activity by salesperson and product lane",
        tables=(
            Table(
                "activity_by_salesperson",
                "Activity by salesperson",
                ("Salesperson", *(ACTIVITY_LABELS.get(t, t.value) for t in types), "Total"),
                tuple(
                    (actor, *(counts.get(t, 0) for t in types), sum(counts.values()))
                    for actor, counts in sorted(by_actor.items())
                ),
                DEFINITIONS["activity"],
            ),
            Table(
                "activity_by_lane",
                "Activity by product lane",
                ("Product lane", "Events"),
                tuple(sorted(by_lane.items())),
                DEFINITIONS["activity"],
            ),
        ),
    )

    backlog = Section(
        "backlog",
        "Follow-up backlog",
        paragraphs=(
            f"As of {meta.local(meta.generated_at)} (when the report was generated): "
            f"overdue follow-ups: {format_value(m.get('follow_ups_overdue'))}; next actions "
            f"falling in the period: {format_value(m.get('follow_ups_due'))}. "
            "Follow-up dates are current data, not history.",
        ),
        tables=(
            _drill_table(meta, "follow_ups_overdue", "Overdue", m.get("follow_ups_overdue")),
            _drill_table(meta, "follow_ups_due", "Due in the period", m.get("follow_ups_due")),
        ),
    )

    sources = Section(
        "sources",
        "Source effectiveness",
        tables=(
            Table(
                "source_effectiveness",
                "Leads by source",
                ("Source", "Leads added", "Progressed", "Progress rate"),
                sources_rows,
                DEFINITIONS["sources"],
            ),
        ),
    )

    trend = report.trend
    trends = Section(
        "trends",
        "Trends",
        paragraphs=(f"Counts per {trend.size.value} of the period.",),
        charts=(
            Chart(
                "trend",
                f"Per {trend.size.value}",
                trend.labels,
                {k: tuple(float(v) for v in values) for k, values in trend.series.items()},
                kind="line" if len(trend.labels) > 12 else "bar",
            ),
        ),
        tables=(
            Table(
                "trend",
                "Trend data",
                ("Period", *trend.series),
                tuple(
                    (label, *(trend.series[name][i] for name in trend.series))
                    for i, label in enumerate(trend.labels)
                ),
                DEFINITIONS["trend"],
            ),
        ),
    )

    facts: list[str] = []
    for key, verb in (
        ("won", "won"),
        ("proposals", "proposal sent to"),
        ("technical_handoffs", "technical handoff for"),
    ):
        metric = m.get(key)
        for row in (metric.rows if metric else ())[:10]:
            facts.append(f"{meta.local(row.when)[:10]}: {verb} {row.organization} ({row.detail})")
    forward = sum(s.forward_exits for s in report.stages)
    if forward:
        facts.append(f"{forward} stage moves to a later stage were recorded.")
    progress = Section(
        "progress",
        "Notable progress",
        paragraphs=(
            "Recorded wins, proposals, technical handoffs and forward stage moves. This list "
            "states facts from the activity history; it does not interpret them."
            if facts
            else "No wins, proposals, technical handoffs or forward stage moves were recorded "
            "in this period.",
        ),
        bullets=tuple(facts),
    )

    quality = report.quality
    caveats = [
        "Activity is logged manually by salespeople; messages are not tracked automatically, "
        "so unlogged outreach is not counted.",
        "Logged interactions are counted by the date entered for them, which may differ from "
        "when they were recorded.",
        "Follow-up measures describe the current state at the time the report was generated.",
        "Contacts added are not filtered by salesperson or product lane; leads added are not "
        "filtered by product lane.",
    ]
    if quality.corrections:
        caveats.append(
            f"{quality.corrections} correction(s) to earlier entries were recorded in this "
            "period and are applied to all counts."
        )
    if quality.backdated:
        caveats.append(
            f"{quality.backdated} event(s) in this period were recorded more than a day after "
            "the date entered for them; a report generated earlier may show lower numbers."
        )
    if quality.unowned_opportunities:
        caveats.append(
            f"{quality.unowned_opportunities} opportunit(ies) have no salesperson and are left "
            "out when a salesperson filter is used."
        )
    if quality.unlinked_activities:
        caveats.append(
            f"{quality.unlinked_activities} event(s) in this period are not linked to an "
            "opportunity and are left out when a product lane filter is used."
        )
    quality_section = Section("quality", "Data quality and caveats", bullets=tuple(caveats))

    definitions = Section(
        "definitions",
        "Definitions",
        paragraphs=(
            "Names in brackets refer to sections of the KPI dictionary (docs/KPI_DICTIONARY.md). "
            "Periods are local calendar days; the period starts at local midnight of its first "
            "day and ends just before local midnight after its last day.",
        ),
        tables=(
            Table(
                "definitions",
                "Measures",
                ("Measure", "Definition"),
                tuple(
                    (METRIC_LABELS.get(k, k.replace("_", " ").capitalize()), v)
                    for k, v in DEFINITIONS.items()
                ),
            ),
        ),
    )

    return ReportContent(
        meta=meta,
        title="Sales report",
        subtitle=f"{meta.period_label}: {describe_range(meta.dates)}",
        sections=(
            executive,
            acquisition,
            outreach,
            stages_section,
            outcomes,
            activity,
            backlog,
            sources,
            trends,
            progress,
            quality_section,
            definitions,
        ),
        caveats=tuple(caveats),
    )
