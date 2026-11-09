# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Prospects (organizations), contacts, games, notes, tags, duplicates and CSV export."""

from __future__ import annotations

import tempfile
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ok, Svc
from tg_sales.api.security import ConflictError, NotFoundError
from tg_sales.domain.enums import (
    ContactStatus,
    GameRole,
    OrganizationType,
    ReleasePrecision,
)
from tg_sales.domain.prospects import (
    ContactDraft,
    DuplicateCandidate,
    GameDraft,
    OrganizationDetail,
    OrganizationDraft,
    ProspectQuery,
    SearchResult,
)

router = APIRouter(tags=["prospects"])

MAX_PAGE = 500


class OrganizationIn(Body):
    name: str = Field(min_length=1, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    company_type: OrganizationType = OrganizationType.UNKNOWN
    location: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=10_000)
    reviewed_on: date | None = None
    qualification_source_url: str | None = Field(default=None, max_length=4000)
    # Changes by custom field key; null clears a value. Fields not listed keep their values.
    custom_fields: dict[str, Any] = Field(default_factory=dict, max_length=200)

    def draft(self) -> OrganizationDraft:
        # Fields the client did not send keep their stored values (older clients,
        # simple forms), so an edit never erases information it did not show.
        keep = frozenset(
            name
            for name in ("reviewed_on", "qualification_source_url")
            if name not in self.model_fields_set
        )
        return OrganizationDraft(
            self.name,
            website=self.website or None,
            company_type=self.company_type,
            location=self.location or None,
            country=self.country or None,
            tags=tuple(t for t in (tag.strip() for tag in self.tags) if t),
            notes=self.notes or None,
            reviewed_on=self.reviewed_on,
            qualification_source_url=self.qualification_source_url or None,
            custom_fields=dict(self.custom_fields),
            keep=keep,
        )


class ContactIn(Body):
    name: str | None = Field(default=None, max_length=200)
    role_title: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    social_urls: dict[str, str] = Field(default_factory=dict, max_length=20)
    status: ContactStatus = ContactStatus.UNKNOWN
    notes: str | None = Field(default=None, max_length=10_000)
    provenance: str | None = Field(default=None, max_length=500)
    source_url: str | None = Field(default=None, max_length=500)
    custom_fields: dict[str, Any] = Field(default_factory=dict, max_length=200)

    def draft(self) -> ContactDraft:
        keep = frozenset(
            name
            for name in ("provenance", "source_url", "social_urls")
            if name not in self.model_fields_set
        )
        return ContactDraft(
            name=self.name or None,
            role_title=self.role_title or None,
            email=self.email or None,
            social_urls=dict(self.social_urls),
            status=self.status,
            notes=self.notes or None,
            provenance=self.provenance or None,
            source_url=self.source_url or None,
            custom_fields=dict(self.custom_fields),
            keep=keep,
        )


class GameIn(Body):
    title: str = Field(min_length=1, max_length=300)
    role: GameRole = GameRole.DEVELOPER
    platform: str | None = Field(default=None, max_length=100)
    store_url: str | None = Field(default=None, max_length=500)
    release_date: date | None = None
    release_precision: ReleasePrecision = ReleasePrecision.UNKNOWN

    def draft(self) -> GameDraft:
        return GameDraft(
            self.title,
            role=self.role,
            platform=self.platform or None,
            store_url=self.store_url or None,
            release_date=self.release_date,
            release_precision=self.release_precision,
        )


class CreateProspect(Body):
    organization: OrganizationIn
    contacts: list[ContactIn] = Field(default_factory=list, max_length=50)
    allow_duplicate: bool = False


class Created(BaseModel):
    id: str


class DuplicateCheck(Body):
    organization: OrganizationIn
    emails: list[str] = Field(default_factory=list, max_length=50)
    exclude_id: str | None = None


class BulkAction(StrEnum):
    ARCHIVE = "archive"
    RESTORE = "restore"
    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"


class Bulk(Body):
    ids: list[str] = Field(min_length=1, max_length=10_000)
    action: BulkAction
    tag: str | None = Field(default=None, max_length=60)


class NoteIn(Body):
    text: str = Field(min_length=1, max_length=10_000)


class Archived(Body):
    archived: bool


class ExportIn(Body):
    ids: list[str] = Field(default_factory=list, max_length=100_000)
    text: str = ""
    tag: str | None = None
    company_type: OrganizationType | None = None
    include_archived: bool = False


@router.get("/prospects", response_model=SearchResult)
def search(
    svc: Svc,
    text: str = "",
    tag: str | None = None,
    company_type: OrganizationType | None = None,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SearchResult:
    return svc.prospects.search(
        ProspectQuery(text, tag or None, company_type, include_archived, limit, offset)
    )


@router.get("/prospects/tags", response_model=list[str])
def tags(svc: Svc) -> list[str]:
    return svc.prospects.all_tags()


@router.post("/prospects/duplicates", response_model=list[DuplicateCandidate])
def duplicates(body: DuplicateCheck, svc: Svc) -> list[DuplicateCandidate]:
    return svc.prospects.find_duplicates(
        body.organization.draft(), body.emails, exclude_id=body.exclude_id
    )


@router.post("/prospects", response_model=Created, status_code=201)
def create(body: CreateProspect, svc: Svc) -> Created:
    draft = body.organization.draft()
    if not body.allow_duplicate:
        emails = [c.email for c in body.contacts if c.email]
        found = svc.prospects.find_duplicates(draft, emails)
        if found:
            raise ConflictError(
                f"A similar prospect already exists: {found[0].name} ({found[0].reason}).",
                action="Open the existing prospect, or choose “Create anyway”.",
            )
    return Created(id=svc.prospects.create(draft, [c.draft() for c in body.contacts]))


@router.get("/prospects/{organization_id}", response_model=OrganizationDetail)
def detail(organization_id: str, svc: Svc) -> OrganizationDetail:
    found = svc.prospects.get_detail(organization_id)
    if found is None:
        raise NotFoundError("That prospect")
    return found


@router.put("/prospects/{organization_id}", response_model=Ok)
def update(organization_id: str, body: OrganizationIn, svc: Svc) -> Ok:
    if svc.prospects.get_detail(organization_id) is None:
        raise NotFoundError("That prospect")
    return Ok(ok=svc.prospects.update(organization_id, body.draft()))


@router.post("/prospects/bulk", response_model=Ok)
def bulk(body: Bulk, svc: Svc) -> Ok:
    if body.action in {BulkAction.ADD_TAG, BulkAction.REMOVE_TAG} and not body.tag:
        raise ConflictError("Enter a tag.", action="Type the tag to add or remove.")
    if body.action is BulkAction.ARCHIVE:
        count = svc.prospects.set_archived(body.ids, True)
    elif body.action is BulkAction.RESTORE:
        count = svc.prospects.set_archived(body.ids, False)
    elif body.action is BulkAction.ADD_TAG:
        count = svc.prospects.add_tag(body.ids, body.tag or "")
    else:
        count = svc.prospects.remove_tag(body.ids, body.tag or "")
    return Ok(count=count)


@router.post("/prospects/export")
def export_csv(body: ExportIn, svc: Svc, background: BackgroundTasks) -> FileResponse:
    ids = body.ids or svc.prospects.ids_for_query(
        ProspectQuery(body.text, body.tag, body.company_type, body.include_archived, 1_000_000)
    )
    handle = tempfile.NamedTemporaryFile(prefix="tg_sales_export_", suffix=".csv", delete=False)  # noqa: SIM115
    handle.close()
    path = Path(handle.name)
    svc.prospects.export_csv(path, ids)
    background.add_task(path.unlink, missing_ok=True)
    return FileResponse(path, media_type="text/csv", filename="tg_sales_prospects.csv")


@router.post("/prospects/{organization_id}/notes", response_model=Ok)
def add_note(organization_id: str, body: NoteIn, svc: Svc) -> Ok:
    svc.prospects.add_note(organization_id, body.text)
    return Ok()


@router.post("/prospects/{organization_id}/contacts", response_model=Created, status_code=201)
def add_contact(organization_id: str, body: ContactIn, svc: Svc) -> Created:
    return Created(id=svc.prospects.add_contact(organization_id, body.draft()))


@router.put("/contacts/{contact_id}", response_model=Ok)
def update_contact(contact_id: str, body: ContactIn, svc: Svc) -> Ok:
    if not svc.prospects.update_contact(contact_id, body.draft()):
        raise NotFoundError("That contact")
    return Ok()


@router.post("/contacts/{contact_id}/archive", response_model=Ok)
def archive_contact(contact_id: str, body: Archived, svc: Svc) -> Ok:
    if not svc.prospects.set_contact_archived(contact_id, body.archived):
        raise NotFoundError("That contact")
    return Ok()


@router.get("/contacts/email-in-use", response_model=list[str])
def email_in_use(svc: Svc, email: str, exclude_contact_id: str | None = None) -> list[str]:
    return svc.prospects.contact_email_in_use(email, exclude_contact_id=exclude_contact_id)


@router.post("/prospects/{organization_id}/games", response_model=Created, status_code=201)
def add_game(organization_id: str, body: GameIn, svc: Svc) -> Created:
    return Created(id=svc.prospects.add_game(organization_id, body.draft()))
