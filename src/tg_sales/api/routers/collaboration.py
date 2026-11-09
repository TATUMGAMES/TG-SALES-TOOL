# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Offline collaboration (sync packages), backups and restore, and the desktop transfer."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ctx, JobRef, Ok, Svc, job_ref
from tg_sales.errors import TgSalesError
from tg_sales.legacy.transfer import transfer, write_report
from tg_sales.services.backups import BackupError, BackupInfo
from tg_sales.sync.engine import ImportPreview, ImportResult, SyncHistoryEntry
from tg_sales.sync.package import MAX_PACKAGE_BYTES

router = APIRouter(tags=["collaboration"])

MAX_LEGACY_BYTES = 2 * 1024 * 1024 * 1024


# -------------------------------------------------------------------- sync
class ExportIn(Body):
    full: bool = False
    passphrase: str | None = Field(default=None, max_length=200)
    recipient_device_id: str | None = Field(default=None, max_length=36)
    recipient_name: str | None = Field(default=None, max_length=100)


class SyncInfo(BaseModel):
    device_id: str
    pending: int
    history: list[SyncHistoryEntry]


@router.get("/sync", response_model=SyncInfo)
def sync_info(svc: Svc) -> SyncInfo:
    return SyncInfo(
        device_id=svc.sync.device_id, pending=svc.sync.pending_count(), history=svc.sync.history()
    )


@router.post("/sync/export", response_model=JobRef)
def export(body: ExportIn, ctx: Ctx, svc: Svc) -> JobRef:
    folder = ctx.paths.exports_dir / "sync"

    def work(_token, progress):  # type: ignore[no-untyped-def]
        progress(10, "Collecting changes…")
        result = svc.sync.export(
            folder,
            full=body.full,
            passphrase=body.passphrase or None,
            recipient_device_id=body.recipient_device_id or None,
            recipient_name=body.recipient_name or None,
        )
        return {
            "export_id": result.export_id,
            "file_name": result.file_name,
            "mode": result.mode,
            "records": result.record_count,
            "events": result.event_count,
            "encrypted": result.encrypted,
        }

    return job_ref(ctx.jobs.submit("sync-export", work, exclusive=True))


@router.get("/sync/exports/{file_name}")
def download_export(file_name: str, ctx: Ctx) -> FileResponse:
    folder = (ctx.paths.exports_dir / "sync").resolve()
    path = (folder / file_name).resolve()
    if (
        path.parent != folder
        or not path.is_file()
        or not file_name.startswith("tg_sales_sync_")
        or not file_name.endswith(".zip")
    ):
        raise TgSalesError("That package no longer exists.", action="Export a new package.")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/sync/import", response_model=ImportPreview)
async def stage_import(svc: Svc, package: UploadFile, passphrase: str = Form("")) -> ImportPreview:
    data = await package.read(MAX_PACKAGE_BYTES + 1)
    if len(data) > MAX_PACKAGE_BYTES:
        raise TgSalesError("The sync package is too large.", action="Ask for a smaller package.")
    name = Path((package.filename or "package.zip").replace("\\", "/")).name[:200]
    return svc.sync.stage(data, name, passphrase or None)


class ApplyIn(Body):
    resolutions: dict[str, dict[str, str]] = Field(default_factory=dict)


@router.post("/sync/import/{token}/apply", response_model=JobRef)
def apply_import(token: str, body: ApplyIn, ctx: Ctx, svc: Svc) -> JobRef:
    def work(_token, progress):  # type: ignore[no-untyped-def]
        progress(5, "Backing up your data…")
        result: ImportResult = svc.sync.apply(token, body.resolutions)
        return result

    return job_ref(ctx.jobs.submit("sync-import", work, exclusive=True))


@router.delete("/sync/import/{token}", response_model=Ok)
def discard_import(token: str, svc: Svc) -> Ok:
    svc.sync.discard(token)
    return Ok()


# ----------------------------------------------------------------- backups
class BackupsView(BaseModel):
    available: bool
    restore_available: bool
    backups: list[BackupInfo]
    keep_latest: int
    keep_monthly: int


@router.get("/backups", response_model=BackupsView)
def backups(ctx: Ctx) -> BackupsView:
    manager = ctx.backups
    return BackupsView(
        available=manager is not None,
        restore_available=bool(manager and manager.can_restore),
        backups=manager.list() if manager else [],
        keep_latest=manager.keep_latest if manager else 0,
        keep_monthly=manager.keep_monthly if manager else 0,
    )


def _manager(ctx: Ctx):  # type: ignore[no-untyped-def]
    if ctx.backups is None:
        raise BackupError(
            "Backups are not available because the PostgreSQL backup programs were not found.",
            action="Run setup.bat again, then restart tg_sales.",
        )
    return ctx.backups


@router.post("/backups", response_model=JobRef)
def create_backup(ctx: Ctx) -> JobRef:
    manager = _manager(ctx)
    return job_ref(
        ctx.jobs.submit("backup", lambda _t, _p: manager.create("manual"), exclusive=True)
    )


@router.post("/backups/{name}/verify", response_model=BackupInfo)
def verify_backup(name: str, ctx: Ctx) -> BackupInfo:
    return _manager(ctx).verify(name)  # type: ignore[no-any-return]


@router.get("/backups/{name}/download")
def download_backup(name: str, ctx: Ctx) -> FileResponse:
    path = _manager(ctx).path(name)
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.delete("/backups/{name}", response_model=Ok)
def delete_backup(name: str, ctx: Ctx) -> Ok:
    _manager(ctx).delete(name)
    return Ok()


class RestoreIn(Body):
    confirm: str = Field(description="Type RESTORE to confirm")


@router.post("/backups/{name}/restore", response_model=JobRef)
def restore_backup(name: str, body: RestoreIn, ctx: Ctx) -> JobRef:
    if body.confirm != "RESTORE":
        raise TgSalesError(
            "Restoring replaces all current data with the backup.",
            action="Type RESTORE to confirm.",
        )
    manager = _manager(ctx)

    def work(_token, progress):  # type: ignore[no-untyped-def]
        progress(5, "Checking the backup and saving a safety copy…")
        outcome = manager.restore(name, before_swap=ctx.database.dispose)
        progress(90, "Reopening the database…")
        ctx.reopen()
        return {
            "restored": outcome.restored.name,
            "safety_backup": outcome.safety_backup.name,
            "previous_database": outcome.previous_database,
        }

    return job_ref(ctx.jobs.submit("restore", work, exclusive=True))


# ------------------------------------------------------- desktop transfer
@router.post("/legacy/transfer", response_model=JobRef)
async def legacy_transfer(ctx: Ctx, database: UploadFile, dry_run: bool = Form(False)) -> JobRef:
    scratch = Path(tempfile.mkdtemp(prefix="tg_sales_desktop_", dir=ctx.paths.cache_dir))
    source = scratch / "data" / "tg_sales.db"
    source.parent.mkdir(parents=True)
    size = 0
    with source.open("wb") as handle:
        while chunk := await database.read(1 << 20):
            size += len(chunk)
            if size > MAX_LEGACY_BYTES:
                shutil.rmtree(scratch, ignore_errors=True)
                raise TgSalesError("The file is too large.", action="Choose the tg_sales.db file.")
            handle.write(chunk)

    def work(_token, progress):  # type: ignore[no-untyped-def]
        try:
            if not dry_run:
                progress(5, "Backing up your data…")
                ctx.backup_before("pre-import")
            progress(20, "Transferring records…")
            report = transfer(source, ctx.database, data_root=None, dry_run=dry_run)
            json_path, md_path = write_report(report, ctx.paths.root / "migration_reports")
            if report.adopted_device_id:
                ctx.reopen()
            result: dict[str, Any] = {
                "ok": report.ok,
                "dry_run": dry_run,
                "tables": {k: v.__dict__ for k, v in report.tables.items()},
                "issues": [i.__dict__ for i in report.issues[:200]],
                "issue_count": len(report.issues),
                "verification": report.verification,
                "adopted_device_id": report.adopted_device_id,
                "report_file": md_path.name,
                "report_json": json_path.name,
            }
            return result
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    return job_ref(ctx.jobs.submit("legacy-transfer", work, exclusive=True))
