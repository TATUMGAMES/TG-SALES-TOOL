"""Settings, the salesperson's name, the company logo and the Resources page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ctx, Ok, Svc
from tg_sales.api.routers.prospects import Created
from tg_sales.services.app_settings import AppSettings
from tg_sales.services.branding import LOGO_REQUIREMENTS_TEXT, MAX_LOGO_FILE_BYTES
from tg_sales.services.resources import ResourceDraft, ResourceInfo

router = APIRouter(tags=["settings"])


class NameIn(Body):
    display_name: str = Field(min_length=1, max_length=80)


class Me(BaseModel):
    actor_id: str
    display_name: str


@router.get("/settings", response_model=AppSettings)
def get_settings(svc: Svc) -> AppSettings:
    return svc.settings.get()


@router.patch("/settings", response_model=AppSettings)
def update_settings(changes: dict[str, Any], ctx: Ctx, svc: Svc) -> AppSettings:
    previous = svc.settings.get()
    updated = svc.settings.update(changes)
    if (
        updated.time_zone != previous.time_zone
        or updated.discovery_cache_hours != previous.discovery_cache_hours
    ):
        ctx.reopen()  # services that depend on these settings are rebuilt
    if ctx.backups is not None:
        ctx.backups.keep_latest = updated.backup_keep_latest
        ctx.backups.keep_monthly = updated.backup_keep_monthly
    return updated


@router.get("/me", response_model=Me)
def me(ctx: Ctx, svc: Svc) -> Me:
    return Me(actor_id=ctx.actor_id, display_name=svc.settings.display_name())


@router.put("/me", response_model=Me)
def set_name(body: NameIn, ctx: Ctx, svc: Svc) -> Me:
    return Me(actor_id=ctx.actor_id, display_name=svc.settings.set_display_name(body.display_name))


# ------------------------------------------------------------------- logo
class LogoInfo(BaseModel):
    present: bool
    requirements: str
    max_bytes: int


@router.get("/branding/logo/info", response_model=LogoInfo)
def logo_info(ctx: Ctx) -> LogoInfo:
    return LogoInfo(
        present=ctx.logo.read() is not None,
        requirements=LOGO_REQUIREMENTS_TEXT,
        max_bytes=MAX_LOGO_FILE_BYTES,
    )


@router.get("/branding/logo")
def logo(ctx: Ctx) -> Response:
    data = ctx.logo.read()
    if data is None:
        return Response(status_code=204)
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.put("/branding/logo", response_model=Ok)
async def upload_logo(image: UploadFile, ctx: Ctx) -> Ok:
    data = await image.read(MAX_LOGO_FILE_BYTES + 1)
    ctx.logo.save(data)
    return Ok()


@router.delete("/branding/logo", response_model=Ok)
def remove_logo(ctx: Ctx) -> Ok:
    ctx.logo.remove()
    return Ok()


# -------------------------------------------------------------- resources
class ResourceIn(Body):
    title: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(link|folder)$")
    target: str = Field(min_length=1, max_length=2000)
    category: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)

    def draft(self) -> ResourceDraft:
        return ResourceDraft(self.title, self.kind, self.target, self.category, self.notes)


class ResourceOrder(Body):
    ids: list[str] = Field(min_length=1, max_length=1000)


@router.get("/resources", response_model=list[ResourceInfo])
def resources(svc: Svc) -> list[ResourceInfo]:
    return svc.resources.list()


@router.post("/resources", response_model=Created, status_code=201)
def create_resource(body: ResourceIn, svc: Svc) -> Created:
    return Created(id=svc.resources.create(body.draft()).id)


@router.put("/resources/order", response_model=Ok)
def reorder_resources(body: ResourceOrder, svc: Svc) -> Ok:
    svc.resources.reorder(body.ids)
    return Ok()


@router.put("/resources/{resource_id}", response_model=ResourceInfo)
def update_resource(resource_id: str, body: ResourceIn, svc: Svc) -> ResourceInfo:
    return svc.resources.update(resource_id, body.draft())


@router.delete("/resources/{resource_id}", response_model=Ok)
def delete_resource(resource_id: str, svc: Svc) -> Ok:
    svc.resources.delete(resource_id)
    return Ok()


@router.post("/resources/{resource_id}/open", response_model=Ok)
def open_resource(resource_id: str, ctx: Ctx, svc: Svc) -> Ok:
    ctx.open_path(svc.resources.folder_path(resource_id))
    return Ok()
