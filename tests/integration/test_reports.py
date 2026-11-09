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

import csv
import itertools
import json
from datetime import date
from pathlib import Path

import pytest

from tg_sales.cancellation import CancelToken, OperationCancelledError
from tg_sales.db.database import Database
from tg_sales.domain.enums import ActivityType, ProductLane
from tg_sales.domain.kpi import KpiFilters
from tg_sales.domain.opportunities import ACTIVITY_LABELS
from tg_sales.domain.periods import DateRange
from tg_sales.reports.charts import layout, nice_max, to_drawing, to_svg
from tg_sales.reports.content import Chart
from tg_sales.reports.generator import (
    PARTIAL_SUFFIX,
    ReportError,
    ReportLibrary,
    ReportRequest,
    create_report,
    ensure_inside,
)

from .conftest import FakeClock
from .test_kpis import OCTOBER, World, at

pytestmark = pytest.mark.integration


@pytest.fixture
def world(database: Database, clock: FakeClock) -> World:
    return World(database, clock)


@pytest.fixture
def history(world: World) -> World:
    """A month with leads, outreach, replies, stage moves, a win and a loss on two lanes."""
    org, ana = world.org("=Pixel Forge <b>", at(2), name="Ana", email="ana@pixel.example")
    org2, _ = world.org("Quiet Owl", at(3))
    deal = world.opp(org, at(4))
    world.clock.set(at(7, 13))
    world.pipeline.log_activity(deal, ActivityType.EMAIL, occurred_at=at(5), contact_id=ana)
    world.pipeline.log_activity(deal, ActivityType.REPLY, occurred_at=at(7), contact_id=ana)
    world.move(deal, "contacted", at(6))
    world.move(deal, "won", at(20))
    other = world.opp(org2, at(8), lane=ProductLane.MIKROS_MARKETING, pipeline=world.other_pipeline)
    world.move(other, "lost", at(22))
    world.opp(org2, at(9, month=9))  # existed before the period
    return world


def make(world: World, root: Path, filters: KpiFilters | None = None, **kwargs: object):  # type: ignore[no-untyped-def]
    world.clock.set(at(31, 23))
    return create_report(
        world.kpis,
        root,
        ReportRequest(OCTOBER, "Custom range", filters or KpiFilters(), **kwargs),  # type: ignore[arg-type]
        {world.actor: "Salesperson", world.other_actor: "Second Salesperson"},
        "test",
        zone=world.kpis._zone,
    )


@pytest.mark.parametrize(
    "filters",
    [
        KpiFilters(),
        KpiFilters(lane=ProductLane.MIKROS_MARKETING),
        KpiFilters(lane=ProductLane.DATA_LICENSING),
    ],
)
def test_report_totals_match_dashboard(history: World, tmp_path: Path, filters: KpiFilters) -> None:
    entry = make(history, tmp_path, filters)
    dashboard = history.report(OCTOBER, filters)
    assert entry.totals == {k: m.value for k, m in dashboard.metrics.items()}
    with (entry.folder / "data" / "summary.csv").open(encoding="utf-8-sig") as handle:
        summary = {row["Measure"]: row["This period"] for row in csv.DictReader(handle)}
    assert summary["Won"] == f"{dashboard.metrics['won'].value:,.0f}"
    assert summary["Replies"] == f"{dashboard.metrics['replies'].value:,.0f}"


def test_report_files_and_content(history: World, tmp_path: Path) -> None:
    entry = make(history, tmp_path)
    assert entry.folder.name.startswith("report_2026-10-01_2026-10-31_")
    assert entry.pdf is not None and entry.pdf.read_bytes().startswith(b"%PDF")
    assert entry.pages >= 5  # major sections start on new pages
    assert entry.html is not None
    page = entry.html.read_text(encoding="utf-8")
    assert "&lt;b&gt;" in page and "<b>" not in page.split("<body>")[1].split("Sales report")[0]
    assert "data:image/svg+xml;base64," in page
    names = {p.name for p in entry.csv_files}
    assert {
        "summary.csv",
        "stage_distribution.csv",
        "stage_transitions.csv",
        "won.csv",
        "lost.csv",
        "activity_by_salesperson.csv",
        "activity_by_lane.csv",
        "source_effectiveness.csv",
        "trend.csv",
        "definitions.csv",
    } <= names
    leads = (entry.folder / "data" / "leads_added.csv").read_text(encoding="utf-8-sig")
    assert "'=Pixel Forge <b>" in leads  # formula-safe CSV
    with (entry.folder / "data" / "stage_distribution.csv").open(encoding="utf-8-sig") as handle:
        rows = {r["Stage"]: r for r in csv.DictReader(handle)}
    assert rows["Discovered"]["At start"] == "1"  # the September opportunity
    assert rows["Won"]["At end"] == "1" and rows["Lost"]["At end"] == "1"
    with (entry.folder / "data" / "stage_transitions.csv").open(encoding="utf-8-sig") as handle:
        moves = {(r["From"], r["To"]): r["Opportunities"] for r in csv.DictReader(handle)}
    assert moves[("New", "Discovered")] == "2"
    assert moves[("Discovered", "Contacted")] == "1"
    assert moves[("Contacted", "Won")] == "1"
    with (entry.folder / "data" / "activity_by_salesperson.csv").open(encoding="utf-8-sig") as h:
        activity = {r["Salesperson"]: r for r in csv.DictReader(h)}
    mine = activity["Salesperson"]
    assert mine[ACTIVITY_LABELS[ActivityType.EMAIL]] == "1"
    assert mine[ACTIVITY_LABELS[ActivityType.REPLY]] == "1"
    manifest = json.loads((entry.folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["start"] == "2026-10-01" and manifest["app_version"] == "test"
    assert not list(tmp_path.glob(f"*{PARTIAL_SUFFIX}"))


def test_empty_period_marks_unavailable(world: World, tmp_path: Path) -> None:
    entry = make(world, tmp_path, include_html=True)
    assert entry.totals["win_rate"] is None
    page = entry.html.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "Not available" in page
    assert "No wins, proposals, technical handoffs or forward stage moves" in page


def test_library_list_export_delete_and_safety(history: World, tmp_path: Path) -> None:
    root = tmp_path / "reports"
    first = make(history, root)
    second = make(history, root)
    assert first.folder != second.folder  # never overwritten
    library = ReportLibrary(root)
    (root / "not-a-report").mkdir()
    (root / "broken").mkdir()
    (root / "broken" / "manifest.json").write_text("{", encoding="utf-8")
    assert {e.folder for e in library.entries()} == {first.folder, second.folder}

    target = tmp_path / "export" / first.folder.name
    library.export(first, target)
    assert (target / "report.pdf").is_file()
    with pytest.raises(FileExistsError):
        library.export(first, target)  # never replaced without confirmation
    library.export(first, target, overwrite=True)

    with pytest.raises(ReportError):
        ensure_inside(root, root / ".." / "outside")
    outsider = type(first)(**{**first.__dict__, "folder": tmp_path / "export"})
    with pytest.raises(ReportError):
        library.delete(outsider)
    assert (tmp_path / "export").is_dir()
    library.delete(first)
    assert not first.folder.exists() and second.folder.exists()


def test_cancel_leaves_nothing(history: World, tmp_path: Path) -> None:
    root = tmp_path / "reports"
    token = CancelToken()
    token.cancel()
    history.clock.set(at(31, 23))
    with pytest.raises(OperationCancelledError):
        create_report(history.kpis, root, ReportRequest(OCTOBER, "Custom"), {}, "test", token=token)
    assert not root.exists() or list(root.iterdir()) == []


def test_chart_rendering() -> None:
    assert [nice_max(v) for v in (0, 1, 3, 7, 11, 240)] == [1, 1, 5, 10, 20, 250]
    chart = Chart("t", "T", ("a", "b"), {"Leads added": (1.0, 4.0), "Won <&>": (0.0, 2.0)})
    svg = to_svg(chart, 400, 200)
    assert svg.startswith("<svg") and 'viewBox="0 0 400 200"' in svg
    assert "Won &lt;&amp;&gt;" in svg  # legend text is escaped
    assert to_drawing(chart, 400, 200).width == 400  # vector drawing for the PDF
    assert "No data" in to_svg(Chart("e", "E", (), {}))


def test_chart_axis_labels_never_overlap() -> None:
    labels = tuple(f"Week of {day:02d} Oct" for day in range(1, 31))
    chart = Chart("t", "T", labels, {"Leads added": tuple(float(i) for i in range(30))})
    texts = [s for s in layout(chart, 300, 200) if s.kind == "text" and s.text in labels]
    assert 1 < len(texts) < len(labels)
    for left, right in itertools.pairwise(texts):
        assert left.x + 20 < right.x


def test_previous_period_comparison(history: World, tmp_path: Path) -> None:
    entry = make(history, tmp_path)
    with (entry.folder / "data" / "summary.csv").open(encoding="utf-8-sig") as handle:
        rows = {r["Measure"]: r for r in csv.DictReader(handle)}
    assert rows["Leads added"]["Previous period"] == "0"
    assert rows["Leads added"]["Change"] == "+2"
    assert rows["Follow-ups overdue (now)"]["Previous period"] == "—"
    assert rows["Win rate"]["This period"] == "50%"
    _ = date
    _ = DateRange
