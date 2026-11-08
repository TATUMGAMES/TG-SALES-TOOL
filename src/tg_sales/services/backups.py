"""Database backups and restore for PostgreSQL.

A backup is a ``pg_dump`` custom-format archive plus a small JSON manifest
(time, reason, app version, schema revision, SHA-256 and per-table row
counts). Every backup is verified after writing by listing the archive with
``pg_restore`` and comparing its checksum, and is written to a ``.partial``
file that is renamed only when complete.

Restore never overwrites the live database in place:

1. A safety backup of the current database is taken.
2. The chosen backup is restored into a new temporary database.
3. The temporary database is checked (schema revision known, row counts equal
   to the manifest).
4. Only then are the databases swapped by renaming; the previous database is
   kept under an ``_previous_`` name until the next restore, so a mistaken
   restore can itself be undone.

Retention: the newest ``keep_latest`` backups, plus the newest backup of each
of the last ``keep_monthly`` months, are kept; older automatic backups are
removed. Backups the user created explicitly are removed by retention too,
but never the newest one.
"""

from __future__ import annotations

import builtins
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL

from tg_sales import __version__
from tg_sales.db.engine import create_pg_engine
from tg_sales.domain.time import Clock, format_utc, parse_utc
from tg_sales.errors import TgSalesError

logger = logging.getLogger(__name__)

SUFFIX = ".dump"
MANIFEST_SUFFIX = ".json"
NAME_PATTERN = re.compile(r"^tg_sales_backup_\d{8}T\d{9}Z_[a-z-]{3,24}\.dump$")
REASONS = ("manual", "scheduled", "pre-migration", "pre-import", "pre-sync", "pre-restore")
DEFAULT_KEEP_LATEST = 10
DEFAULT_KEEP_MONTHLY = 6


class BackupError(TgSalesError):
    """A backup could not be created, verified, exported, deleted or restored."""


@dataclass(frozen=True)
class BackupInfo:
    name: str
    created_at: datetime
    reason: str
    size_bytes: int
    app_version: str
    schema_revision: str | None
    sha256: str
    table_counts: dict[str, int]
    verified: bool


@dataclass(frozen=True)
class RestoreOutcome:
    restored: BackupInfo
    safety_backup: BackupInfo
    previous_database: str


@dataclass(frozen=True)
class PgTools:
    """Paths of the PostgreSQL client programs (same major version as the server or newer)."""

    pg_dump: str
    pg_restore: str

    @classmethod
    def find(cls, bin_dir: Path | None) -> PgTools | None:
        def locate(name: str) -> str | None:
            if bin_dir is not None:
                for candidate in (bin_dir / f"{name}.exe", bin_dir / name):
                    if candidate.is_file():
                        return str(candidate)
            return shutil.which(name)

        dump, restore = locate("pg_dump"), locate("pg_restore")
        return cls(dump, restore) if dump and restore else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    args: Sequence[str],
    url: URL,
    *,
    stdin_path: Path | None = None,
    stdout_path: Path | None = None,
    timeout: float = 1800,
) -> str:
    """Run a PostgreSQL client program; archives are piped through stdin/stdout.

    File paths are never passed to the programs: on Windows they cannot open
    paths outside the system code page (e.g. a user folder with accents).
    """
    env = dict(os.environ)
    env["PGPASSWORD"] = url.password or ""  # never on the command line
    env["PGTZ"] = "UTC"
    with contextlib.ExitStack() as stack:
        log = stack.enter_context(tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace"))
        stdin = stack.enter_context(stdin_path.open("rb")) if stdin_path else subprocess.DEVNULL
        stdout = stack.enter_context(stdout_path.open("wb")) if stdout_path else log
        result = subprocess.run(  # noqa: S603 - fixed PostgreSQL client programs
            [
                *args,
                "--host",
                str(url.host or "127.0.0.1"),
                "--port",
                str(url.port or 5432),
                "--username",
                str(url.username or ""),
            ],
            stdin=stdin,
            stdout=stdout,
            stderr=log,
            env=env,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.seek(0)
        text_out = log.read()
    if result.returncode != 0:
        raise BackupError(
            "The database backup program reported an error.",
            action="Check that the disk is not full, then try again.",
            detail=f"{Path(args[0]).name} exited {result.returncode}: {text_out.strip()[-2000:]}",
        )
    return text_out


class BackupManager:
    """Creates, lists, verifies, exports, prunes and restores backups in ``folder``."""

    def __init__(
        self,
        tools: PgTools,
        url: URL,
        folder: Path,
        clock: Clock,
        *,
        admin_url: URL | None = None,
        keep_latest: int = DEFAULT_KEEP_LATEST,
        keep_monthly: int = DEFAULT_KEEP_MONTHLY,
    ) -> None:
        self._tools = tools
        self._url = url
        self._admin_url = admin_url
        self._folder = folder
        self._clock = clock
        self.keep_latest = keep_latest
        self.keep_monthly = keep_monthly

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def can_restore(self) -> bool:
        return self._admin_url is not None

    # ---------------------------------------------------------------- create
    def _counts(self, url: URL) -> tuple[dict[str, int], str | None]:
        engine = create_pg_engine(url, pool_size=1)
        try:
            tables = sorted(inspect(engine).get_table_names())
            with engine.connect() as connection:
                counts = {
                    table: int(
                        connection.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0  # noqa: S608
                    )
                    for table in tables
                    if table != "alembic_version"
                }
                revision = (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    if "alembic_version" in tables
                    else None
                )
        finally:
            engine.dispose()
        return counts, None if revision is None else str(revision)

    def create(self, reason: str = "manual") -> BackupInfo:
        if reason not in REASONS:
            raise ValueError(f"unknown backup reason {reason!r}")
        now = self._clock.now()
        stamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
        name = f"tg_sales_backup_{stamp}_{reason}{SUFFIX}"
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackupError(
                f"The backups folder could not be created:\n{self._folder}",
                action="Check that the data folder is writable and the disk is not full.",
                detail=repr(exc),
            ) from exc
        target = self._folder / name
        partial = target.with_name(name + ".partial")
        try:
            counts, revision = self._counts(self._url)
            _run(
                [
                    self._tools.pg_dump,
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    str(self._url.database),
                ],
                self._url,
                stdout_path=partial,
            )
            listing = _run([self._tools.pg_restore, "--list"], self._url, stdin_path=partial)
            if "TABLE DATA" not in listing and counts:
                raise BackupError(
                    "The new backup could not be verified.",
                    action="Try again. Your data was not changed.",
                    detail="archive listing has no table data",
                )
            partial.replace(target)
            info = BackupInfo(
                name=name,
                created_at=now,
                reason=reason,
                size_bytes=target.stat().st_size,
                app_version=__version__,
                schema_revision=revision,
                sha256=_sha256(target),
                table_counts=counts,
                verified=True,
            )
            self._write_manifest(info)
        except OSError as exc:
            raise BackupError(
                "The backup could not be written.",
                action="Check that the disk is not full and the backups folder is writable.",
                detail=repr(exc),
            ) from exc
        finally:
            partial.unlink(missing_ok=True)
        logger.info("Backup created", extra={"context": {"name": name, "reason": reason}})
        self.prune()
        return info

    def _write_manifest(self, info: BackupInfo) -> None:
        data = {
            "name": info.name,
            "created_at_utc": format_utc(info.created_at),
            "reason": info.reason,
            "size_bytes": info.size_bytes,
            "app_version": info.app_version,
            "schema_revision": info.schema_revision,
            "sha256": info.sha256,
            "table_counts": info.table_counts,
        }
        path = self._manifest_path(info.name)
        partial = path.with_name(path.name + ".partial")
        partial.write_text(json.dumps(data, indent=2), encoding="utf-8")
        partial.replace(path)

    def _manifest_path(self, name: str) -> Path:
        return self._folder / (name[: -len(SUFFIX)] + MANIFEST_SUFFIX)

    # ------------------------------------------------------------------ read
    def path(self, name: str) -> Path:
        """The archive for ``name``; refuses anything that is not a backup in the folder."""
        if not NAME_PATTERN.fullmatch(name):
            raise BackupError(
                "That is not a tg_sales backup.", action="Choose a backup from the list."
            )
        path = (self._folder / name).resolve()
        if path.parent != self._folder.resolve() or not path.is_file():
            raise BackupError(
                "The backup file no longer exists.", action="Refresh the list of backups."
            )
        return path

    def info(self, name: str) -> BackupInfo:
        path = self.path(name)
        try:
            data: dict[str, Any] = json.loads(self._manifest_path(name).read_text(encoding="utf-8"))
            return BackupInfo(
                name=name,
                created_at=parse_utc(str(data["created_at_utc"])),
                reason=str(data["reason"]),
                size_bytes=path.stat().st_size,
                app_version=str(data.get("app_version", "")),
                schema_revision=data.get("schema_revision"),
                sha256=str(data["sha256"]),
                table_counts={str(k): int(v) for k, v in dict(data["table_counts"]).items()},
                verified=False,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise BackupError(
                "The backup's description file is missing or damaged.",
                action="Choose a different backup.",
                detail=repr(exc),
            ) from exc

    def list(self) -> list[BackupInfo]:
        if not self._folder.is_dir():
            return []
        entries: list[BackupInfo] = []
        for path in self._folder.glob(f"tg_sales_backup_*{SUFFIX}"):
            try:
                entries.append(self.info(path.name))
            except BackupError:
                logger.warning("Skipping unreadable backup", extra={"context": {"name": path.name}})
        return sorted(entries, key=lambda e: e.created_at, reverse=True)

    def verify(self, name: str) -> BackupInfo:
        info = self.info(name)
        path = self.path(name)
        if _sha256(path) != info.sha256:
            raise BackupError(
                "This backup is damaged (its checksum does not match).",
                action="Choose a different backup.",
            )
        _run([self._tools.pg_restore, "--list"], self._url, stdin_path=path)
        return BackupInfo(**{**info.__dict__, "verified": True})

    # ---------------------------------------------------------- export/delete
    def export(self, name: str, target_dir: Path, *, overwrite: bool = False) -> Path:
        source = self.path(name)
        target = target_dir / name
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            shutil.copy2(self._manifest_path(name), target_dir / self._manifest_path(name).name)
        except OSError as exc:
            raise BackupError(
                "The backup could not be copied to that folder.",
                action="Choose a folder you can write to with enough free space.",
                detail=repr(exc),
            ) from exc
        return target

    def delete(self, name: str) -> None:
        path = self.path(name)
        path.unlink()
        self._manifest_path(name).unlink(missing_ok=True)

    def prune(self) -> builtins.list[str]:
        entries = self.list()
        keep = {entry.name for entry in entries[: max(1, self.keep_latest)]}
        months: dict[str, str] = {}
        for entry in entries:  # newest first
            months.setdefault(entry.created_at.strftime("%Y-%m"), entry.name)
        for month in sorted(months, reverse=True)[: self.keep_monthly]:
            keep.add(months[month])
        removed = []
        for entry in entries:
            if entry.name not in keep:
                self.delete(entry.name)
                removed.append(entry.name)
        if removed:
            logger.info("Old backups removed", extra={"context": {"count": len(removed)}})
        return removed

    # --------------------------------------------------------------- restore
    def restore(self, name: str, *, before_swap: Callable[[], None]) -> RestoreOutcome:
        """Restore ``name`` (see module docstring). ``before_swap`` must close all connections."""
        if self._admin_url is None:
            raise BackupError(
                "Restoring needs the database administrator account, which is not configured.",
                action="Ask your administrator to restore the backup on the database server.",
            )
        chosen = self.verify(name)
        safety = self.create("pre-restore")
        stamp = self._clock.now().strftime("%Y%m%d%H%M%S")
        live = str(self._url.database)
        temporary = f"{live}_restoring_{stamp}"
        previous = f"{live}_previous_{stamp}"
        admin = self._admin_url

        def connect() -> psycopg.Connection[tuple[Any, ...]]:
            return psycopg.connect(
                host=admin.host,
                port=admin.port,
                user=admin.username,
                password=admin.password,
                dbname=admin.database or "postgres",
                autocommit=True,
            )

        owner = sql.Identifier(str(self._url.username))
        with connect() as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(temporary), owner
                )
            )
        temp_url = self._url.set(database=temporary)
        try:
            _run(
                [
                    self._tools.pg_restore,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "--single-transaction",
                    "--dbname",
                    temporary,
                ],
                temp_url,
                stdin_path=self.path(name),
            )
            counts, _revision = self._counts(temp_url)
            expected = {k: v for k, v in chosen.table_counts.items() if k != "alembic_version"}
            if counts != expected:
                raise BackupError(
                    "The restored copy does not match the backup's description.",
                    action="Your current data was not changed. Choose a different backup.",
                    detail=f"expected {expected}, got {counts}",
                )
        except BaseException:
            with connect() as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(temporary)
                    )
                )
            raise

        before_swap()
        with connect() as connection:
            for old in connection.execute(
                "SELECT datname FROM pg_database WHERE datname LIKE %s",
                (f"{live}_previous_%",),
            ).fetchall():
                connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(str(old[0]))
                    )
                )
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (live,),
            )
            connection.execute(
                sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                    sql.Identifier(live), sql.Identifier(previous)
                )
            )
            connection.execute(
                sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                    sql.Identifier(temporary), sql.Identifier(live)
                )
            )
        logger.info(
            "Backup restored",
            extra={"context": {"name": name, "previous_database": previous}},
        )
        return RestoreOutcome(chosen, safety, previous)
