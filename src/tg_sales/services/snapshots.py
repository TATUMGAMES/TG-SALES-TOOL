"""Dashboard snapshots: save PNG images in the snapshots folder and keep their metadata.

The image itself is rendered by the UI from the dashboard widgets (never a
screen capture). Files live only in this computer's snapshots folder; every
path read from the database is checked to stay inside that folder.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

from sqlalchemy import select

from tg_sales import __version__
from tg_sales.db.database import Database
from tg_sales.db.models import Snapshot
from tg_sales.domain.snapshots import is_snapshot_name, unique_snapshot_name
from tg_sales.errors import TgSalesError


class SnapshotError(TgSalesError):
    """A snapshot could not be saved, opened, exported or deleted."""


@dataclass(frozen=True)
class SnapshotInfo:
    id: str
    path: Path
    file_name: str
    generated_at: datetime
    filters: dict[str, Any]
    app_version: str
    width: int | None
    height: int | None
    exists: bool


class SnapshotService:
    def __init__(self, database: Database, folder: Path, zone: tzinfo | None = None) -> None:
        self._database = database
        self._folder = folder
        self._zone = zone

    @property
    def folder(self) -> Path:
        return self._folder

    def _inside(self, relative: str) -> Path:
        path = (self._folder / relative).resolve()
        if not path.is_relative_to(self._folder.resolve()) or not is_snapshot_name(path.name):
            raise SnapshotError(
                "This snapshot's file is not in the snapshots folder.",
                action="Delete the snapshot entry and take a new snapshot.",
                detail=relative,
            )
        return path

    def save(
        self,
        png: bytes,
        filters: dict[str, Any],
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> SnapshotInfo:
        """Write the image under a new unique name and record it."""
        if not png.startswith(b"\x89PNG"):
            raise SnapshotError("The snapshot image is not a PNG.", action="Try again.")
        moment = self._database.clock.now()
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            name = unique_snapshot_name(moment, lambda n: (self._folder / n).exists(), self._zone)
            target = self._folder / name
            partial = target.with_name(name + ".partial")
            with partial.open("wb") as handle:
                handle.write(png)
                handle.flush()
                os.fsync(handle.fileno())
            partial.replace(target)
        except OSError as exc:
            raise SnapshotError(
                "The snapshot could not be saved.",
                action="Check that there is free disk space and try again.",
                detail=repr(exc),
            ) from exc
        with self._database.session() as session:
            row = Snapshot(
                relative_path=name,
                filters=dict(filters),
                generated_at_utc=moment,
                app_version=__version__,
                width_px=width,
                height_px=height,
            )
            session.add(row)
            session.flush()
            return self._info(row)

    def _info(self, row: Snapshot) -> SnapshotInfo:
        try:
            path = self._inside(row.relative_path)
            exists = path.is_file()
        except SnapshotError:
            path, exists = self._folder / Path(row.relative_path).name, False
        return SnapshotInfo(
            id=row.id,
            path=path,
            file_name=Path(row.relative_path).name,
            generated_at=row.generated_at_utc,
            filters=dict(row.filters or {}),
            app_version=row.app_version,
            width=row.width_px,
            height=row.height_px,
            exists=exists,
        )

    def list(self) -> list[SnapshotInfo]:
        """Snapshots recorded on this computer, newest first."""
        with self._database.session() as session:
            rows = session.scalars(
                select(Snapshot)
                .where(Snapshot.deleted_at_utc.is_(None))
                .order_by(Snapshot.generated_at_utc.desc(), Snapshot.id)
            )
            return [self._info(r) for r in rows]

    def _row(self, session: Any, snapshot_id: str) -> Snapshot:
        row = session.get(Snapshot, snapshot_id)
        if row is None or row.is_deleted:
            raise SnapshotError("This snapshot no longer exists.", action="Refresh the list.")
        return row  # type: ignore[no-any-return]

    def path(self, snapshot_id: str) -> Path:
        with self._database.session() as session:
            path = self._inside(self._row(session, snapshot_id).relative_path)
        if not path.is_file():
            raise SnapshotError(
                "The snapshot image is missing from the snapshots folder.",
                action="It may have been moved or deleted outside tg_sales. Delete the entry.",
            )
        return path

    def export(self, snapshot_id: str, target: Path, *, overwrite: bool = False) -> Path:
        """Copy the image to ``target``; an existing file is replaced only with ``overwrite``."""
        source = self.path(snapshot_id)
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".partial")
            shutil.copy2(source, partial)
            partial.replace(target)
        except OSError as exc:
            raise SnapshotError(
                f"The snapshot could not be exported to:\n{target}",
                action="Choose a folder you can write to and try again.",
                detail=repr(exc),
            ) from exc
        return target

    def delete(self, snapshot_id: str) -> None:
        """Delete the image file and its entry."""
        with self._database.session() as session:
            row = self._row(session, snapshot_id)
            try:
                path = self._inside(row.relative_path)
                path.unlink(missing_ok=True)
            except SnapshotError:
                pass  # never touch a file outside the folder; just remove the entry
            except OSError as exc:
                raise SnapshotError(
                    "The snapshot image could not be deleted.",
                    action="Close it if it is open in another program and try again.",
                    detail=repr(exc),
                ) from exc
            row.deleted_at_utc = self._database.clock.now()
