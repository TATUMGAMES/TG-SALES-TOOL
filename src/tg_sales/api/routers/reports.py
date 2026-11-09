# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Reports (PDF, CSV, HTML preview) and dashboard snapshots."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from tg_sales import __version__
from tg_sales.api.deps import Body, Ctx, JobRef, Ok, Svc, job_ref
from tg_sales.api.routers.dashboard import resolve_period
from tg_sales.domain.kpi import KpiFilters
from tg_sales.domain.periods import PRESET_LABELS, PeriodPreset
from tg_sales.errors import TgSalesError
from tg_sales.reports.generator import ReportRequest, create_report
from tg_sales.services.branding import sanitize_image
from tg_sales.services.report_catalog import ReportCatalog, ReportInfo
from tg_sales.services.snapshots import SnapshotInfo

router = APIRouter(tags=["reports"])

MAX_SNAPSHOT_BYTES = 40 * 1024 * 1024
MAX_SNAPSHOT_DIMENSION = 16_384


def catalog(ctx: Ctx) -> ReportCatalog:
    return ReportCatalog(ctx.database, ctx.reports, ctx.actor_id)


class ReportIn(Body):
    preset: PeriodPreset = PeriodPreset.LAST_1_MONTH
    start: date | None = None
    end: date | None = None
    actor_id: str | None = None
    lane: str | None = Field(default=None, max_length=32)  # sales lane key
    include_html: bool = True


@router.post("/reports", response_model=JobRef)
def create(body: ReportIn, ctx: Ctx, svc: Svc) -> JobRef:
    dates = resolve_period(svc.kpis.today(), body.preset, body.start, body.end)
    actors = dict(svc.kpis.actors())
    if body.actor_id and body.actor_id not in actors:
        raise TgSalesError(
            "That salesperson is unknown.", action="Choose a salesperson from the list."
        )
    request = ReportRequest(
        dates,
        PRESET_LABELS.get(body.preset, "Custom range"),
        KpiFilters(body.actor_id or None, body.lane),
        salesperson=actors.get(body.actor_id) if body.actor_id else None,
        include_html=body.include_html,
        lane_names=svc.lanes.names(),
    )
    zone = svc.settings.get().zone()
    reports = catalog(ctx)

    def work(token, progress):  # type: ignore[no-untyped-def]
        entry = create_report(
            svc.kpis,
            ctx.paths.reports_dir,
            request,
            actors,
            __version__,
            zone=zone,
            token=token,
            progress=progress,
        )
        report_id = reports.register(
            entry,
            {
                "preset": body.preset.value,
                "actor_id": body.actor_id,
                "lane": body.lane,
            },
        )
        return {"report_id": report_id, "pages": entry.pages}

    return job_ref(ctx.jobs.submit("report", work))


@router.get("/reports", response_model=list[ReportInfo])
def reports(ctx: Ctx) -> list[ReportInfo]:
    return catalog(ctx).list()


@router.get("/reports/{report_id}/pdf")
def pdf(report_id: str, ctx: Ctx, download: bool = False) -> FileResponse:
    path = catalog(ctx).file(report_id, "pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{path.parent.name}.pdf",
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/reports/{report_id}/html")
def html(report_id: str, ctx: Ctx) -> FileResponse:
    path = catalog(ctx).file(report_id, "html")
    response = FileResponse(path, media_type="text/html; charset=utf-8")
    # The preview is a static document: no scripts, nothing from other sites.
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    )
    return response


@router.get("/reports/{report_id}/csv/{name}")
def csv_file(report_id: str, name: str, ctx: Ctx) -> FileResponse:
    path = catalog(ctx).file(report_id, "csv", name)
    return FileResponse(path, media_type="text/csv", filename=path.name)


@router.get("/reports/{report_id}/download")
def download(report_id: str, ctx: Ctx) -> Response:
    name, data = catalog(ctx).zip_bytes(report_id)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.delete("/reports/{report_id}", response_model=Ok)
def delete(report_id: str, ctx: Ctx) -> Ok:
    catalog(ctx).delete(report_id)
    return Ok()


@router.post("/reports/{report_id}/open-folder", response_model=Ok)
def open_folder(report_id: str, ctx: Ctx) -> Ok:
    ctx.open_path(catalog(ctx).entry(report_id).folder)
    return Ok()


# --------------------------------------------------------------- snapshots
class SnapshotView(BaseModel):
    id: str
    file_name: str
    generated_at: str
    filters: dict[str, object]
    app_version: str
    width: int | None
    height: int | None
    exists: bool


def _view(info: SnapshotInfo) -> SnapshotView:
    return SnapshotView(
        id=info.id,
        file_name=info.file_name,
        generated_at=info.generated_at.isoformat(),
        filters=info.filters,
        app_version=info.app_version,
        width=info.width,
        height=info.height,
        exists=info.exists,
    )


class SnapshotFilters(BaseModel):
    model_config = {"extra": "ignore"}

    period: str = Field(default="", max_length=200)
    period_start: str | None = Field(default=None, max_length=10)
    period_end: str | None = Field(default=None, max_length=10)
    salesperson: str | None = Field(default=None, max_length=200)
    lane: str | None = Field(default=None, max_length=100)
    area: str = Field(default="visible", pattern="^(visible|whole)$")


@router.post("/snapshots", response_model=SnapshotView, status_code=201)
async def save_snapshot(svc: Svc, image: UploadFile, filters: str = Form("{}")) -> SnapshotView:
    data = await image.read(MAX_SNAPSHOT_BYTES + 1)
    try:
        parsed = SnapshotFilters.model_validate(json.loads(filters or "{}"))
    except ValueError as exc:
        raise TgSalesError("The snapshot details are not valid.", action="Try again.") from exc
    png, width, height = sanitize_image(
        data,
        max_bytes=MAX_SNAPSHOT_BYTES,
        max_dimension=MAX_SNAPSHOT_DIMENSION,
        allowed=frozenset({"PNG"}),
    )
    info = svc.snapshots.save(png, parsed.model_dump(), width=width, height=height)
    return _view(info)


@router.get("/snapshots", response_model=list[SnapshotView])
def snapshots(svc: Svc) -> list[SnapshotView]:
    return [_view(s) for s in svc.snapshots.list()]


@router.get("/snapshots/{snapshot_id}/image")
def snapshot_image(snapshot_id: str, svc: Svc, download: bool = False) -> FileResponse:
    path = svc.snapshots.path(snapshot_id)
    return FileResponse(
        path,
        media_type="image/png",
        filename=path.name,
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/snapshots/{snapshot_id}", response_model=Ok)
def delete_snapshot(snapshot_id: str, svc: Svc) -> Ok:
    svc.snapshots.delete(snapshot_id)
    return Ok()
