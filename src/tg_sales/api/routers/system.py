# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Health, application information, background jobs, integrity and local folders."""

from __future__ import annotations

import dataclasses
import hmac
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from tg_sales.api.deps import Body, Ctx, JobView, Ok
from tg_sales.api.security import NotFoundError
from tg_sales.errors import TgSalesError

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    database: str


class Info(BaseModel):
    app_name: str
    version: str
    schema_revision: str | None
    device_id: str
    actor_id: str
    display_name: str
    first_run: bool
    desktop_integration: bool
    backups_available: bool
    restore_available: bool
    data_folder: str | None
    environment: str


@router.get("/health", response_model=Health)
def health(ctx: Ctx) -> Health:
    report = ctx.database.check_integrity()
    return Health(
        status="ok" if report.ok else "degraded", database="ok" if report.ok else "problem"
    )


@router.get("/system/info", response_model=Info)
def info(ctx: Ctx) -> Info:
    return Info(
        app_name="TG Sales CRM",
        version=ctx.version,
        schema_revision=ctx.database.schema_revision(),
        device_id=ctx.database.device_id,
        actor_id=ctx.actor_id,
        display_name=ctx.services.settings.display_name(),
        first_run=ctx.services.settings.is_first_run,
        desktop_integration=ctx.desktop_integration,
        backups_available=ctx.backups is not None,
        restore_available=bool(ctx.backups and ctx.backups.can_restore),
        data_folder=str(ctx.paths.root) if ctx.desktop_integration else None,
        environment=str(ctx.server.environment),
    )


class IntegrityView(BaseModel):
    ok: bool
    problems: list[str]
    checked_at: str


@router.post("/system/integrity", response_model=IntegrityView)
def integrity(ctx: Ctx) -> IntegrityView:
    report = ctx.database.check_integrity(full=True)
    return IntegrityView(
        ok=report.ok, problems=list(report.problems), checked_at=report.checked_at.isoformat()
    )


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@router.get("/jobs/{job_id}", response_model=JobView)
def job(job_id: str, ctx: Ctx) -> JobView:
    found = ctx.jobs.get(job_id)
    if found is None:
        raise NotFoundError("That task")
    return JobView(
        id=found.id,
        kind=found.kind,
        status=found.status.value,
        percent=found.percent,
        message=found.message,
        result=_jsonable(found.result) if found.done else None,
        error=found.error,
    )


@router.post("/jobs/{job_id}/cancel", response_model=Ok)
def cancel_job(job_id: str, ctx: Ctx) -> Ok:
    return Ok(ok=ctx.jobs.cancel(job_id))


class FolderName(StrEnum):
    DATA = "data"
    BACKUPS = "backups"
    REPORTS = "reports"
    SNAPSHOTS = "snapshots"
    LOGS = "logs"
    EXPORTS = "exports"


class OpenFolder(Body):
    folder: FolderName


@router.post("/system/open-folder", response_model=Ok)
def open_folder(body: OpenFolder, ctx: Ctx) -> Ok:
    paths = {
        FolderName.DATA: ctx.paths.root,
        FolderName.BACKUPS: ctx.paths.backups_dir,
        FolderName.REPORTS: ctx.paths.reports_dir,
        FolderName.SNAPSHOTS: ctx.paths.snapshots_dir,
        FolderName.LOGS: ctx.paths.logs_dir,
        FolderName.EXPORTS: ctx.paths.exports_dir,
    }
    target = paths[body.folder]
    target.mkdir(parents=True, exist_ok=True)
    ctx.open_path(target)
    return Ok()


@router.post("/system/shutdown", response_model=Ok, include_in_schema=False)
def shutdown(request: Request) -> Ok:
    """Stop the local server; only the launcher knows the secret this requires."""
    expected = getattr(request.app.state, "stop_secret", None)
    given = request.headers.get("x-tg-sales-stop", "")
    if not expected or not hmac.compare_digest(str(expected), given):
        raise TgSalesError("Not allowed.", action="Use stop.bat to stop tg_sales.")
    request.app.state.request_stop()
    return Ok()
