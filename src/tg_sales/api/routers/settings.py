# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Settings, the salesperson's name, company branding and the Resources page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, UploadFile
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ctx, Ok, Svc
from tg_sales.api.routers.prospects import Created
from tg_sales.services.app_settings import AppSettings
from tg_sales.services.branding import (
    BRANDING_REQUIREMENTS_TEXT,
    DEFAULT_COMPANY_NAME,
    LOGO_REQUIREMENTS_TEXT,
    MAX_COMPANY_NAME,
    MAX_LOGO_FILE_BYTES,
    BrandingSettings,
    ImageSlot,
)
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


# --------------------------------------------------------------- branding
class BrandImage(BaseModel):
    present: bool
    media_type: str | None
    version: str | None  # changes with the image; add as ?v= to bypass caches


class BrandingView(BaseModel):
    company_name: str | None  # None: the default name is shown
    display_name: str
    default_company_name: str
    accent_color: str | None
    accent_text_color: str | None
    images: dict[str, BrandImage]
    requirements: str
    max_bytes: int


class BrandingIn(Body):
    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME)
    accent_color: str | None = Field(default=None, max_length=7)


def _branding_view(settings: BrandingSettings, ctx: Ctx) -> BrandingView:
    images = {}
    for slot in ImageSlot:
        stored = ctx.branding_store.read(slot)
        images[slot.value] = BrandImage(
            present=stored is not None,
            media_type=stored.media_type if stored else None,
            version=stored.version if stored else None,
        )
    return BrandingView(
        company_name=settings.company_name,
        display_name=settings.display_name,
        default_company_name=DEFAULT_COMPANY_NAME,
        accent_color=settings.accent_color,
        accent_text_color=settings.accent_text_color,
        images=images,
        requirements=BRANDING_REQUIREMENTS_TEXT,
        max_bytes=MAX_LOGO_FILE_BYTES,
    )


def _image_response(ctx: Ctx, slot: ImageSlot) -> RawResponse:
    stored = ctx.branding_store.read(slot)
    if stored is None:
        return RawResponse(status_code=204)
    return RawResponse(
        stored.data,
        media_type=stored.media_type,
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
            # An SVG opened directly can never run anything or load anything.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
            "img-src data:; sandbox",
            "Content-Disposition": "inline",
        },
    )


@router.get("/branding", response_model=BrandingView)
def branding(ctx: Ctx, svc: Svc) -> BrandingView:
    return _branding_view(svc.branding.get(), ctx)


@router.patch("/branding", response_model=BrandingView)
def update_branding(body: BrandingIn, ctx: Ctx, svc: Svc) -> BrandingView:
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    return _branding_view(svc.branding.update(changes), ctx)


@router.post("/branding/reset", response_model=BrandingView)
def reset_branding(ctx: Ctx, svc: Svc) -> BrandingView:
    return _branding_view(svc.branding.reset(), ctx)


@router.get("/branding/images/{slot}")
def branding_image(slot: ImageSlot, ctx: Ctx) -> RawResponse:
    return _image_response(ctx, slot)


@router.put("/branding/images/{slot}", response_model=Ok)
async def upload_branding_image(slot: ImageSlot, image: UploadFile, ctx: Ctx) -> Ok:
    data = await image.read(MAX_LOGO_FILE_BYTES + 1)
    ctx.branding_store.save(slot, data)
    return Ok()


@router.delete("/branding/images/{slot}", response_model=Ok)
def remove_branding_image(slot: ImageSlot, ctx: Ctx) -> Ok:
    ctx.branding_store.remove(slot)
    return Ok()


# Earlier routes for the main logo (kept for compatibility; same file as the logo slot).
class LogoInfo(BaseModel):
    present: bool
    requirements: str
    max_bytes: int


@router.get("/branding/logo/info", response_model=LogoInfo)
def logo_info(ctx: Ctx) -> LogoInfo:
    return LogoInfo(
        present=ctx.branding_store.read(ImageSlot.LOGO) is not None,
        requirements=LOGO_REQUIREMENTS_TEXT,
        max_bytes=MAX_LOGO_FILE_BYTES,
    )


@router.get("/branding/logo")
def logo(ctx: Ctx) -> RawResponse:
    return _image_response(ctx, ImageSlot.LOGO)


@router.put("/branding/logo", response_model=Ok)
async def upload_logo(image: UploadFile, ctx: Ctx) -> Ok:
    data = await image.read(MAX_LOGO_FILE_BYTES + 1)
    ctx.branding_store.save(ImageSlot.LOGO, data)
    return Ok()


@router.delete("/branding/logo", response_model=Ok)
def remove_logo(ctx: Ctx) -> Ok:
    ctx.branding_store.remove(ImageSlot.LOGO)
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
