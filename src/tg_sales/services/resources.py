# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Resources page: bookmarks to internal documents (web links) and local folders.

Only safe ``http(s)`` links are stored (never credentials or downloaded file
contents). Web links are shared with colleagues through sync; folder
shortcuts point at folders on this computer, so they stay here.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tg_sales.db.database import Database
from tg_sales.db.models import ResourceLink
from tg_sales.domain.normalization import normalize_url
from tg_sales.errors import TgSalesError

KINDS = ("link", "folder")
MAX_TITLE = 120
MAX_NOTES = 2000


class ResourceError(TgSalesError):
    """A resource bookmark is not valid."""


@dataclass(frozen=True)
class ResourceInfo:
    id: str
    title: str
    kind: str
    target: str
    category: str | None
    notes: str | None
    sort_order: int
    available: bool  # folder exists on this computer / link is well-formed


@dataclass(frozen=True)
class ResourceDraft:
    title: str
    kind: str
    target: str
    category: str | None = None
    notes: str | None = None


def _clean(draft: ResourceDraft) -> ResourceDraft:
    title = " ".join(draft.title.split())
    if not title or len(title) > MAX_TITLE:
        raise ResourceError(
            f"Give the bookmark a name of 1 to {MAX_TITLE} characters.",
            action="Enter a short name.",
        )
    if draft.kind not in KINDS:
        raise ResourceError("Choose a web link or a folder.", action="Pick the bookmark type.")
    if draft.kind == "link":
        target = normalize_url(draft.target)
        if target is None:
            raise ResourceError(
                "That is not a web address tg_sales can open safely.",
                action="Enter an address starting with https://, without a password in it.",
            )
    else:
        path = Path(draft.target.strip().strip('"'))
        if not path.is_absolute():
            raise ResourceError(
                "Enter the full path of the folder.",
                action="For example C:\\Users\\you\\Documents\\Sales material.",
            )
        target = str(path)
    notes = (draft.notes or "").strip() or None
    if notes and len(notes) > MAX_NOTES:
        raise ResourceError(
            "The notes are too long.", action=f"Keep notes under {MAX_NOTES} characters."
        )
    category = " ".join((draft.category or "").split()) or None
    return ResourceDraft(title, draft.kind, target, category, notes)


def _info(row: ResourceLink) -> ResourceInfo:
    available = Path(row.target).is_dir() if row.kind == "folder" else True
    return ResourceInfo(
        row.id, row.title, row.kind, row.target, row.category, row.notes, row.sort_order, available
    )


class ResourceService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list(self) -> list[ResourceInfo]:
        with self._database.session() as session:
            rows = session.scalars(
                select(ResourceLink)
                .where(ResourceLink.deleted_at_utc.is_(None))
                .order_by(ResourceLink.sort_order, ResourceLink.title)
            )
            return [_info(row) for row in rows]

    def create(self, draft: ResourceDraft) -> ResourceInfo:
        clean = _clean(draft)
        with self._database.session() as session:
            last = session.scalar(
                select(ResourceLink.sort_order)
                .where(ResourceLink.deleted_at_utc.is_(None))
                .order_by(ResourceLink.sort_order.desc())
                .limit(1)
            )
            row = ResourceLink(
                title=clean.title,
                kind=clean.kind,
                target=clean.target,
                category=clean.category,
                notes=clean.notes,
                sort_order=(last or 0) + 10,
            )
            session.add(row)
            session.flush()
            return _info(row)

    def _get(self, session: Session, resource_id: str) -> ResourceLink:
        row = session.get(ResourceLink, resource_id)
        if row is None or row.is_deleted:
            raise ResourceError("That bookmark no longer exists.", action="Refresh the page.")
        return row

    def update(self, resource_id: str, draft: ResourceDraft) -> ResourceInfo:
        clean = _clean(draft)
        with self._database.session() as session:
            row = self._get(session, resource_id)
            row.title, row.kind, row.target = clean.title, clean.kind, clean.target
            row.category, row.notes = clean.category, clean.notes
            session.flush()
            return _info(row)

    def delete(self, resource_id: str) -> None:
        with self._database.session() as session:
            row = self._get(session, resource_id)
            row.deleted_at_utc = self._database.clock.now()

    def folder_path(self, resource_id: str) -> Path:
        """The folder of a folder bookmark (for opening it on this computer)."""
        with self._database.session() as session:
            row = self._get(session, resource_id)
            if row.kind != "folder":
                raise ResourceError(
                    "This bookmark is a web link.", action="Open it in your browser."
                )
            path = Path(row.target)
        if not path.is_dir():
            raise ResourceError(
                "That folder does not exist on this computer.",
                action="Check the path, or edit the bookmark.",
            )
        return path

    def reorder(self, resource_ids: builtins.list[str]) -> None:
        with self._database.session() as session:
            for index, resource_id in enumerate(resource_ids):
                self._get(session, resource_id).sort_order = (index + 1) * 10
