# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Generate report folders and manage the reports library.

Each report is a folder in the reports folder containing ``report.pdf``,
optionally ``report.html`` (a self-contained preview), one CSV per table, and
``manifest.json`` describing the period, filters and totals. A report is
written to a temporary ``.partial`` folder and renamed when complete, so a
failed or cancelled run never leaves a half-written report in the list. Folder
names include the UTC epoch milliseconds, so reports never overwrite each other.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path
from typing import Any

from tg_sales.cancellation import CancelToken
from tg_sales.domain.kpi import KpiFilters, KpiReport
from tg_sales.domain.periods import DateRange, previous_range
from tg_sales.errors import TgSalesError
from tg_sales.reports.content import ReportContent, ReportMeta, build_report
from tg_sales.reports.document import preview_html, write_pdf
from tg_sales.services.csv_export import write_csv
from tg_sales.services.kpis import KpiService

MANIFEST = "manifest.json"
PDF_NAME = "report.pdf"
HTML_NAME = "report.html"
CSV_DIR = "data"
PARTIAL_SUFFIX = ".partial"

ProgressCallback = Callable[[int, str], None]


class ReportError(TgSalesError):
    """A report could not be created, opened, exported or deleted."""


@dataclass(frozen=True)
class ReportRequest:
    dates: DateRange
    period_label: str
    filters: KpiFilters = KpiFilters()  # noqa: RUF009 - immutable value
    salesperson: str | None = None
    include_html: bool = True
    lane_names: Mapping[str, str] = field(default_factory=dict)  # lane key -> display name


@dataclass(frozen=True)
class ReportEntry:
    folder: Path
    title: str
    subtitle: str
    filter_text: str
    generated_at: datetime
    start: date
    end: date
    pdf: Path | None
    html: Path | None
    csv_files: tuple[Path, ...]
    pages: int
    totals: Mapping[str, float | None]


def epoch_ms(moment: datetime) -> int:
    return int(moment.astimezone(UTC).timestamp() * 1000)


def ensure_inside(root: Path, path: Path) -> Path:
    """Resolve ``path`` and refuse anything outside ``root`` (no path traversal)."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ReportError(
            "That file is not in the tg_sales reports folder.",
            action="Choose a report from the list.",
            detail=str(path),
        )
    return resolved


def copy_out(source: Path, target: Path, *, overwrite: bool = False) -> Path:
    """Copy a file or folder to ``target``; refuse to replace it unless ``overwrite``."""
    if target.exists() and not overwrite:
        raise FileExistsError(str(target))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            partial = target.with_name(target.name + PARTIAL_SUFFIX)
            shutil.copy2(source, partial)
            partial.replace(target)
    except OSError as exc:
        raise ReportError(
            f"The export could not be saved:\n{target}",
            action="Choose a folder you can write to, close the file if it is open in another "
            "program, and try again.",
            detail=repr(exc),
        ) from exc
    return target


def _totals(report: KpiReport) -> dict[str, float | None]:
    return {key: metric.value for key, metric in report.metrics.items()}


def write_report(
    root: Path,
    content: ReportContent,
    report: KpiReport,
    *,
    include_html: bool = True,
    token: CancelToken | None = None,
) -> ReportEntry:
    meta = content.meta
    stamp = epoch_ms(meta.generated_at)
    name = f"report_{meta.dates.start.isoformat()}_{meta.dates.end.isoformat()}_{stamp}"
    folder = root / name
    while folder.exists():  # a second report in the same millisecond
        stamp += 1
        folder = (
            root / f"report_{meta.dates.start.isoformat()}_{meta.dates.end.isoformat()}_{stamp}"
        )
    partial = folder.with_name(folder.name + PARTIAL_SUFFIX)
    try:
        partial.mkdir(parents=True, exist_ok=False)
        csv_names = []
        for table in content.tables():
            if token is not None:
                token.raise_if_cancelled()
            target = partial / CSV_DIR / f"{table.key}.csv"
            if target.exists():
                continue
            write_csv(target, table.columns, table.rows)
            csv_names.append(f"{CSV_DIR}/{table.key}.csv")
        if token is not None:
            token.raise_if_cancelled()
        pages = write_pdf(content, partial / PDF_NAME)
        if include_html:
            (partial / HTML_NAME).write_text(preview_html(content), encoding="utf-8")
        manifest: dict[str, Any] = {
            "format": 1,
            "title": content.title,
            "subtitle": content.subtitle,
            "period_label": meta.period_label,
            "start": meta.dates.start.isoformat(),
            "end": meta.dates.end.isoformat(),
            "filters": {
                "actor_id": meta.filters.actor_id,
                "lane": meta.filters.lane,
            },
            "filter_text": meta.filter_text,
            "generated_at_utc": meta.generated_at.astimezone(UTC).isoformat(),
            "app_version": meta.app_version,
            "pages": pages,
            "files": {
                "pdf": PDF_NAME,
                "html": HTML_NAME if include_html else None,
                "csv": csv_names,
            },
            "totals": _totals(report),
        }
        (partial / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        partial.rename(folder)
    except BaseException as exc:
        shutil.rmtree(partial, ignore_errors=True)
        if isinstance(exc, OSError):
            raise ReportError(
                "The report could not be saved.",
                action="Check that there is free disk space and that the reports folder can "
                "be written to, then try again.",
                detail=repr(exc),
            ) from exc
        raise
    entry = read_entry(folder)
    assert entry is not None  # noqa: S101 - just written
    return entry


def create_report(
    kpis: KpiService,
    root: Path,
    request: ReportRequest,
    actor_names: Mapping[str, str],
    app_version: str,
    *,
    zone: tzinfo | None = None,
    token: CancelToken | None = None,
    progress: ProgressCallback | None = None,
) -> ReportEntry:
    """Calculate the KPIs (exactly as the dashboard does) and write the report."""

    def step(percent: int, text: str) -> None:
        if token is not None:
            token.raise_if_cancelled()
        if progress is not None:
            progress(percent, text)

    step(2, "Calculating this period…")
    current = kpis.dashboard(request.dates, request.filters, token)
    step(40, "Calculating the previous period…")
    previous = kpis.dashboard(previous_range(request.dates), request.filters, token)
    step(65, "Building the report…")
    meta = ReportMeta(
        dates=request.dates,
        period_label=request.period_label,
        filters=request.filters,
        salesperson=request.salesperson,
        generated_at=current.computed_at,
        app_version=app_version,
        zone=zone,
        lane_names=request.lane_names,
    )
    content = build_report(meta, current.report, previous.report, actor_names)
    step(75, "Writing the PDF and data files…")
    entry = write_report(
        root, content, current.report, include_html=request.include_html, token=token
    )
    step(100, "Done")
    return entry


def read_entry(folder: Path) -> ReportEntry | None:
    """Read a report folder's manifest; None when it is not a valid report."""
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        files = data.get("files") or {}
        pdf = folder / str(files["pdf"]) if files.get("pdf") else None
        html = folder / str(files["html"]) if files.get("html") else None
        return ReportEntry(
            folder=folder,
            title=str(data["title"]),
            subtitle=str(data["subtitle"]),
            filter_text=str(data.get("filter_text") or ""),
            generated_at=datetime.fromisoformat(str(data["generated_at_utc"])),
            start=date.fromisoformat(str(data["start"])),
            end=date.fromisoformat(str(data["end"])),
            pdf=pdf if pdf and pdf.is_file() else None,
            html=html if html and html.is_file() else None,
            csv_files=tuple(
                folder / str(name)
                for name in files.get("csv") or ()
                if (folder / str(name)).is_file()
            ),
            pages=int(data.get("pages") or 0),
            totals=dict(data.get("totals") or {}),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


class ReportLibrary:
    """The reports in the reports folder, newest first."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def entries(self) -> list[ReportEntry]:
        if not self.root.is_dir():
            return []
        found = []
        for folder in self.root.iterdir():
            if folder.is_dir() and not folder.name.endswith(PARTIAL_SUFFIX):
                entry = read_entry(folder)
                if entry is not None:
                    found.append(entry)
        return sorted(found, key=lambda e: e.generated_at, reverse=True)

    def delete(self, entry: ReportEntry) -> None:
        folder = ensure_inside(self.root, entry.folder)
        if folder == self.root.resolve():
            raise ReportError(
                "The reports folder itself cannot be deleted.", action="Choose a report."
            )
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            raise ReportError(
                "The report could not be deleted.",
                action="Close the report if it is open in another program and try again.",
                detail=repr(exc),
            ) from exc

    def export(self, entry: ReportEntry, target: Path, *, overwrite: bool = False) -> Path:
        """Copy the whole report folder to ``target``."""
        return copy_out(ensure_inside(self.root, entry.folder), target, overwrite=overwrite)
