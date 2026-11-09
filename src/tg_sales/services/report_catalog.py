# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Report metadata in the database, alongside the report folders on disk.

Every generated report gets a ``report_records`` row (period, filters, time,
app version, page count and totals). The files themselves stay in the reports
data folder. Listing reconciles the two: folders without a row (for example
copied from the desktop version) are registered, and rows whose folder was
removed are shown as missing until deleted.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from tg_sales import __version__
from tg_sales.db.database import Database
from tg_sales.db.models import ReportRecord
from tg_sales.reports.generator import (
    ReportEntry,
    ReportError,
    ReportLibrary,
    ensure_inside,
    read_entry,
)


@dataclass(frozen=True)
class ReportInfo:
    id: str
    folder_name: str
    title: str
    period_start: date
    period_end: date
    filters: dict[str, Any]
    filter_text: str
    generated_at: datetime
    app_version: str
    page_count: int | None
    has_pdf: bool
    has_html: bool
    csv_files: tuple[str, ...]
    totals: dict[str, Any]
    exists: bool


class ReportCatalog:
    def __init__(self, database: Database, library: ReportLibrary, actor_id: str | None) -> None:
        self._database = database
        self._library = library
        self._actor_id = actor_id

    @property
    def root(self) -> Path:
        return self._library.root

    def register(self, entry: ReportEntry, filters: dict[str, Any]) -> str:
        with self._database.session() as session:
            existing = session.scalar(
                select(ReportRecord).where(ReportRecord.folder_name == entry.folder.name)
            )
            if existing is not None:
                return existing.id
            record = ReportRecord(
                folder_name=entry.folder.name,
                title=f"{entry.title} · {entry.subtitle}",
                period_start=entry.start,
                period_end=entry.end,
                filters={**filters, "text": entry.filter_text},
                generated_at_utc=entry.generated_at,
                app_version=__version__,
                page_count=entry.pages,
                has_html=entry.html is not None,
                totals=dict(entry.totals),
                author_actor_id=self._actor_id,
            )
            session.add(record)
            session.flush()
            return record.id

    def list(self) -> list[ReportInfo]:
        on_disk = {entry.folder.name: entry for entry in self._library.entries()}
        with self._database.session() as session:
            known = {
                r.folder_name
                for r in session.scalars(
                    select(ReportRecord).where(ReportRecord.deleted_at_utc.is_(None))
                )
            }
        for name, entry in on_disk.items():
            if name not in known:
                self.register(entry, {})
        with self._database.session() as session:
            rows = session.scalars(
                select(ReportRecord)
                .where(ReportRecord.deleted_at_utc.is_(None))
                .order_by(ReportRecord.generated_at_utc.desc())
            ).all()
            return [self._info(row, on_disk.get(row.folder_name)) for row in rows]

    @staticmethod
    def _info(row: ReportRecord, entry: ReportEntry | None) -> ReportInfo:
        return ReportInfo(
            id=row.id,
            folder_name=row.folder_name,
            title=row.title,
            period_start=row.period_start,
            period_end=row.period_end,
            filters=dict(row.filters),
            filter_text=str(row.filters.get("text", "")),
            generated_at=row.generated_at_utc,
            app_version=row.app_version,
            page_count=row.page_count,
            has_pdf=bool(entry and entry.pdf),
            has_html=bool(entry and entry.html),
            csv_files=tuple(p.name for p in entry.csv_files) if entry else (),
            totals=dict(row.totals),
            exists=entry is not None,
        )

    def _row(self, report_id: str) -> ReportRecord:
        with self._database.session() as session:
            row = session.get(ReportRecord, report_id)
            if row is None or row.is_deleted:
                raise ReportError("That report no longer exists.", action="Refresh the list.")
            return row

    def entry(self, report_id: str) -> ReportEntry:
        row = self._row(report_id)
        folder = ensure_inside(self.root, self.root / row.folder_name)
        entry = read_entry(folder)
        if entry is None:
            raise ReportError(
                "The report's files are missing from the reports folder.",
                action="Delete this entry and create the report again.",
            )
        return entry

    def file(self, report_id: str, kind: str, name: str | None = None) -> Path:
        entry = self.entry(report_id)
        if kind == "pdf" and entry.pdf:
            return ensure_inside(self.root, entry.pdf)
        if kind == "html" and entry.html:
            return ensure_inside(self.root, entry.html)
        if kind == "csv" and name:
            for path in entry.csv_files:
                if path.name == name:
                    return ensure_inside(self.root, path)
        raise ReportError(
            "That file is not part of the report.", action="Choose a file from the list."
        )

    def zip_bytes(self, report_id: str) -> tuple[str, bytes]:
        entry = self.entry(report_id)
        folder = ensure_inside(self.root, entry.folder)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    archive.write(path, path.relative_to(folder).as_posix())
        return f"{folder.name}.zip", buffer.getvalue()

    def delete(self, report_id: str) -> None:
        row = self._row(report_id)
        folder = self.root / row.folder_name
        if folder.exists():
            entry = read_entry(folder)
            if entry is not None:
                self._library.delete(entry)
        with self._database.session() as session:
            record = session.get(ReportRecord, report_id)
            if record is not None:
                record.deleted_at_utc = self._database.clock.now()
