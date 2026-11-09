# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Exporting and importing change packages (offline collaboration).

How changes are tracked
-----------------------
Database triggers write a ``change_log`` row for every insert or update of a
synchronized record, identified by a ``change_id``. A record's *history* is
its list of change ids in order; the last one is its *head* (current version).

Export
------
A delta package contains every record changed since this computer's previous
export (by change-log sequence, not by ``updated_at``), each with its current
values, head and full history. A full package contains every synchronized
record. Records received from colleagues are in the change log too, so they
are forwarded onward (A → B → C) and recognized when they come back (no loops).

Import
------
Each incoming record is compared with the local one:

* missing locally → **insert** (tombstoned records are inserted as tombstones);
* incoming head already in the local history → **skip** (already have it, or
  it is older);
* local head in the incoming history (or no local history) → **update**
  (fast-forward to the newer version);
* both changed since they last agreed → **conflict**: the differing fields are
  shown and the user picks, per field, which value to keep. The resolved
  record becomes a new version whose history contains both sides, so it
  propagates without further conflicts. Identical values on both sides simply
  **converge**.

Activity events are immutable and identified by id: inserted once, never
updated. Records referring to records that are not present yet (packages
imported out of order) are kept as *pending* and applied automatically after a
later import brings the missing record. Everything is applied in one
transaction after an automatic backup; any failure rolls back completely.
Importing the same package twice changes nothing.
"""

from __future__ import annotations

import enum
import logging
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Float,
    Integer,
    String,
    Table,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import JSON

from tg_sales import __version__
from tg_sales.db.database import Database
from tg_sales.db.models import SYNCED_TABLES, Base
from tg_sales.db.types import UTCDateTime
from tg_sales.domain.ids import is_valid_id, new_id
from tg_sales.domain.normalization import identifying_domain
from tg_sales.domain.time import format_utc, parse_utc
from tg_sales.errors import TgSalesError
from tg_sales.sync.package import (
    FORMAT,
    FORMAT_VERSION,
    PackageContents,
    PackageError,
    build_zip,
    person_slug,
    read_package,
    seal,
    write_package,
)

logger = logging.getLogger(__name__)

TABLES: list[Table] = [t for t in Base.metadata.sorted_tables if t.name in SYNCED_TABLES]
TABLE_BY_NAME = {t.name: t for t in TABLES}
IGNORED_IN_COMPARISON = frozenset({"updated_at_utc"})
PREVIEW_TTL_SECONDS = 3600
CHUNK = 500


class SyncError(TgSalesError):
    """A sync export or import could not be completed; nothing was changed."""


# --------------------------------------------------------------------- values
def to_json(table: Table, row: Mapping[Any, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in table.columns:
        value = row.get(column.name)
        if isinstance(value, datetime):
            value = format_utc(value)
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, enum.Enum):
            value = value.value
        out[column.name] = value
    return out


class _Invalid(Exception):  # noqa: N818 - internal signal
    pass


def from_json(table: Table, data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and convert a package row; raise _Invalid with a reason."""
    out: dict[str, Any] = {}
    for column in table.columns:
        name = column.name
        if name not in data:
            if column.nullable:
                out[name] = None
                continue
            if isinstance(column.type, JSON):
                # Added in a later version (e.g. custom field values): empty, not invalid.
                out[name] = {}
                continue
            raise _Invalid(f"{name} is missing")
        value = data[name]
        if value is None:
            if not column.nullable:
                raise _Invalid(f"{name} cannot be empty")
            out[name] = None
            continue
        kind = column.type
        try:
            if isinstance(kind, UTCDateTime):
                out[name] = parse_utc(str(value))
            elif isinstance(kind, Date):
                out[name] = date.fromisoformat(str(value))
            elif isinstance(kind, SqlEnum):
                if str(value) not in set(kind.enums):
                    raise _Invalid(f"{name} has an unknown value")
                out[name] = str(value)
            elif isinstance(kind, Boolean):
                if not isinstance(value, bool):
                    raise _Invalid(f"{name} must be true or false")
                out[name] = value
            elif isinstance(kind, (Integer, BigInteger)):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise _Invalid(f"{name} must be a whole number")
                out[name] = value
            elif isinstance(kind, Float):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise _Invalid(f"{name} must be a number")
                out[name] = float(value)
            elif isinstance(kind, JSON):
                out[name] = value
            elif isinstance(kind, String):
                if not isinstance(value, str):
                    raise _Invalid(f"{name} must be text")
                if kind.length is not None and len(value) > kind.length:
                    raise _Invalid(f"{name} is too long")
                if (name == "id" or column.foreign_keys) and not is_valid_id(value):
                    raise _Invalid(f"{name} is not a valid identifier")
                out[name] = value
            else:
                if not isinstance(value, str):
                    raise _Invalid(f"{name} must be text")
                out[name] = value
        except ValueError as exc:
            raise _Invalid(f"{name} is malformed") from exc
    return out


def _comparable(table: Table, values: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in to_json(table, values).items() if k not in IGNORED_IN_COMPARISON}


# --------------------------------------------------------------------- types
@dataclass(frozen=True)
class FieldDiff:
    field: str
    local: Any
    incoming: Any


@dataclass
class PlannedRecord:
    table: str
    id: str
    change_id: str
    history: list[str]
    values: dict[str, Any]
    action: str  # insert | update | skip | converge | conflict | pending | duplicate
    local_id: str | None = None  # differs from id only for shared settings matched by key
    differences: list[FieldDiff] = field(default_factory=list)
    reason: str | None = None
    label: str = ""


@dataclass(frozen=True)
class ConflictView:
    key: str  # "<table>:<id>"
    table: str
    record_id: str
    label: str
    differences: tuple[FieldDiff, ...]


@dataclass(frozen=True)
class PossibleDuplicate:
    table: str
    incoming_id: str
    incoming_label: str
    local_id: str
    local_label: str
    reason: str


@dataclass(frozen=True)
class ImportPreview:
    token: str
    file_name: str
    export_id: str
    source_device_id: str
    source_actor_name: str
    created_at: str
    encrypted: bool
    mode: str
    already_imported: bool
    counts: dict[str, int]
    by_table: dict[str, dict[str, int]]
    conflicts: tuple[ConflictView, ...]
    possible_duplicates: tuple[PossibleDuplicate, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ImportResult:
    sync_import_id: str
    export_id: str
    counts: dict[str, int]
    pending_applied: int
    pending_remaining: int
    backup: str | None


@dataclass(frozen=True)
class ExportResult:
    export_id: str
    path: Path
    file_name: str
    mode: str
    record_count: int
    event_count: int
    encrypted: bool


@dataclass(frozen=True)
class SyncHistoryEntry:
    kind: str  # export | import
    id: str
    at: datetime
    file_name: str
    detail: dict[str, Any]


@dataclass
class _Staged:
    contents: PackageContents
    file_name: str
    path: Path
    expires: float


# --------------------------------------------------------------------- helpers
def _history(connection: Connection, table: str, ids: Sequence[str]) -> dict[str, list[str]]:
    log = Base.metadata.tables["change_log"]
    out: dict[str, list[str]] = {}
    for start in range(0, len(ids), CHUNK):
        rows = connection.execute(
            select(log.c.entity_id, log.c.change_id)
            .where(log.c.entity_table == table, log.c.entity_id.in_(ids[start : start + CHUNK]))
            .order_by(log.c.seq)
        )
        for entity_id, change_id in rows:
            out.setdefault(str(entity_id), []).append(str(change_id))
    return out


def _label(table: str, values: Mapping[str, Any]) -> str:
    for key in ("name", "title", "display_name", "key", "file_name"):
        if values.get(key):
            return f"{table[:-1] if table.endswith('s') else table}: {values[key]}"
    if table == "activities":
        return f"activity: {values.get('type')}"
    return f"{table}: {values.get('id')}"


def _references(table: Table) -> list[tuple[str, str]]:
    return [
        (column.name, next(iter(column.foreign_keys)).column.table.name)
        for column in table.columns
        if column.foreign_keys
    ]


# ------------------------------------------------------------------- service
class SyncService:
    def __init__(
        self,
        database: Database,
        actor_id: str,
        actor_name: Callable[[], str],
        *,
        before_import: Callable[[], Path | None] | None = None,
        staging_dir: Path | None = None,
    ) -> None:
        self._database = database
        self._actor_id = actor_id
        self._actor_name = actor_name
        self._before_import = before_import
        self._staging = staging_dir or Path(tempfile.gettempdir()) / "tg_sales_sync_staging"
        self._staged: dict[str, _Staged] = {}
        self._lock = threading.Lock()

    @property
    def device_id(self) -> str:
        return self._database.device_id

    # ---------------------------------------------------------------- export
    def export(
        self,
        folder: Path,
        *,
        full: bool = False,
        passphrase: str | None = None,
        recipient_device_id: str | None = None,
        recipient_name: str | None = None,
    ) -> ExportResult:
        if recipient_device_id and not is_valid_id(recipient_device_id.strip()):
            raise SyncError(
                "The recipient's sync ID is not valid.",
                action="Copy it exactly from the recipient's Sync page, or leave it empty.",
            )
        exports = Base.metadata.tables["sync_exports"]
        log = Base.metadata.tables["change_log"]
        now = self._database.clock.now()
        export_id = new_id()
        records: dict[str, list[dict[str, Any]]] = {}
        with self._database.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            until = int(connection.scalar(select(func.coalesce(func.max(log.c.seq), 0))) or 0)
            since = 0
            if not full:
                previous = connection.execute(
                    select(exports.c.watermark)
                    .where(exports.c.deleted_at_utc.is_(None))
                    .order_by(exports.c.created_at_utc.desc())
                    .limit(1)
                ).scalar()
                if isinstance(previous, dict):
                    since = int(previous.get("until_seq", 0))
            for table in TABLES:
                if full:
                    ids = [str(i) for i in connection.scalars(select(table.c.id))]
                    if table.name == "settings":
                        ids = [
                            str(i)
                            for i in connection.scalars(
                                select(table.c.id).where(table.c.scope == "shared")
                            )
                        ]
                    if table.name == "resource_links":
                        ids = [
                            str(i)
                            for i in connection.scalars(
                                select(table.c.id).where(table.c.kind == "link")
                            )
                        ]
                else:
                    ids = [
                        str(i)
                        for i in connection.scalars(
                            select(log.c.entity_id)
                            .where(
                                log.c.entity_table == table.name,
                                log.c.seq > since,
                                log.c.seq <= until,
                            )
                            .distinct()
                        )
                    ]
                if not ids:
                    continue
                histories = _history(connection, table.name, ids)
                rows: list[dict[str, Any]] = []
                for start in range(0, len(ids), CHUNK):
                    for row in connection.execute(
                        select(table).where(table.c.id.in_(ids[start : start + CHUNK]))
                    ).mappings():
                        record_id = str(row["id"])
                        history = histories.get(record_id) or [
                            # Built-in rows never edited here have no history of their own.
                            f"00000000-0000-4000-8000-{record_id[-12:]}"
                        ]
                        rows.append(
                            {
                                "id": record_id,
                                "change_id": history[-1],
                                "history": history,
                                "row": to_json(table, row),
                            }
                        )
                if rows:
                    records[table.name] = rows
        total = sum(len(rows) for rows in records.values())
        if total == 0:
            raise SyncError(
                "There are no new changes since your last export.",
                action="Choose “Everything” to export all records (for a new colleague).",
            )
        events = len(records.get("activities", []))
        actor_name = self._actor_name()
        manifest: dict[str, Any] = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "schema_revision": self._database.schema_revision(),
            "app_version": __version__,
            "export_id": export_id,
            "mode": "full" if full else "delta",
            "since_seq": since,
            "until_seq": until,
            "source_device_id": self._database.device_id,
            "source_actor_id": self._actor_id,
            "source_actor_name": actor_name,
            "recipient_device_id": (recipient_device_id or "").strip() or None,
            "recipient_name": (recipient_name or "").strip() or None,
            "created_at_utc": format_utc(now),
            "counts": {table: len(rows) for table, rows in records.items()},
        }
        data = build_zip(manifest, records)
        if passphrase:
            data = seal(data, manifest, passphrase)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        file_name = f"tg_sales_sync_{person_slug(actor_name)}_{stamp}_{export_id[-8:]}.zip"
        path = write_package(folder / file_name, data)
        with self._database.engine.begin() as connection:
            connection.execute(
                insert(exports).values(
                    id=export_id,
                    file_name=file_name,
                    watermark={"since_seq": since, "until_seq": until, "mode": manifest["mode"]},
                    record_count=total - events,
                    event_count=events,
                    encrypted=bool(passphrase),
                    created_at_utc=now,
                    updated_at_utc=now,
                    created_by_device_id=self._database.device_id,
                )
            )
        logger.info(
            "Sync package exported",
            extra={
                "context": {
                    "records": total,
                    "mode": manifest["mode"],
                    "encrypted": bool(passphrase),
                }
            },
        )
        return ExportResult(
            export_id, path, file_name, manifest["mode"], total - events, events, bool(passphrase)
        )

    # --------------------------------------------------------------- import
    def stage(self, data: bytes, file_name: str, passphrase: str | None = None) -> ImportPreview:
        """Validate an uploaded package and preview what importing it would do."""
        token = new_id()
        self._staging.mkdir(parents=True, exist_ok=True)
        path = self._staging / f"{token}.zip"
        path.write_bytes(data)
        try:
            contents = read_package(path, passphrase)
            self._validate(contents)
            with self._database.engine.connect() as connection:
                plan = self._plan(connection, contents)
                preview = self._preview(token, file_name, contents, plan, connection)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        with self._lock:
            self._expire()
            self._staged[token] = _Staged(
                contents, file_name, path, time.time() + PREVIEW_TTL_SECONDS
            )
        return preview

    def discard(self, token: str) -> None:
        with self._lock:
            staged = self._staged.pop(token, None)
        if staged is not None:
            staged.path.unlink(missing_ok=True)

    def _expire(self) -> None:
        now = time.time()
        for token in [t for t, s in self._staged.items() if s.expires < now]:
            self._staged.pop(token).path.unlink(missing_ok=True)

    def _validate(self, contents: PackageContents) -> None:
        manifest = contents.manifest
        if manifest.get("schema_revision") != self._database.schema_revision():
            raise PackageError(
                "This sync package comes from a different version of tg_sales.",
                action="Make sure you and your colleague use the same tg_sales release, then "
                "export a new package.",
                detail=f"package schema {manifest.get('schema_revision')!r}",
            )
        for key in ("export_id", "source_device_id"):
            if not is_valid_id(str(manifest.get(key, ""))):
                raise PackageError(
                    "The sync package's manifest is damaged.",
                    action="Ask your colleague to export a new package.",
                    detail=key,
                )
        if manifest["source_device_id"] == self._database.device_id:
            raise SyncError(
                "This package was exported from this computer.",
                action="Import packages that colleagues exported on their computers.",
            )
        problems: list[str] = []
        for table, rows in contents.records.items():
            if table not in TABLE_BY_NAME:
                problems.append(f"unknown table {table}")
                continue
            for item in rows:
                record_id, change_id = item.get("id"), item.get("change_id")
                history, row = item.get("history"), item.get("row")
                if not (isinstance(record_id, str) and is_valid_id(record_id)):
                    problems.append(f"{table}: invalid id")
                elif not (
                    isinstance(change_id, str)
                    and isinstance(history, list)
                    and history
                    and history[-1] == change_id
                    and all(isinstance(h, str) and is_valid_id(h) for h in history)
                ):
                    problems.append(f"{table} {record_id}: invalid change history")
                elif not isinstance(row, dict) or row.get("id") != record_id:
                    problems.append(f"{table} {record_id}: invalid record")
                else:
                    try:
                        item["_values"] = from_json(TABLE_BY_NAME[table], row)
                    except _Invalid as exc:
                        problems.append(f"{table} {record_id}: {exc}")
                if len(problems) >= 20:
                    break
        if problems:
            raise PackageError(
                "The sync package contains records tg_sales cannot read.",
                action="Ask your colleague to export a new package with the same tg_sales release.",
                detail="; ".join(problems[:20]),
            )

    def _plan(
        self,
        connection: Connection,
        contents: PackageContents,
        pending: Iterable[dict[str, Any]] = (),
    ) -> list[PlannedRecord]:
        incoming: dict[str, list[dict[str, Any]]] = {
            t.name: list(contents.records.get(t.name, [])) for t in TABLES
        }
        for item in pending:
            incoming.setdefault(item["table"], []).append(item)
        will_exist: dict[str, set[str]] = {}
        plan: list[PlannedRecord] = []
        for table in TABLES:
            items = incoming.get(table.name, [])
            if not items:
                continue
            ids = [str(i["id"]) for i in items]
            local_rows: dict[str, dict[str, Any]] = {}
            for start in range(0, len(ids), CHUNK):
                for row in connection.execute(
                    select(table).where(table.c.id.in_(ids[start : start + CHUNK]))
                ).mappings():
                    local_rows[str(row["id"])] = dict(row)
            histories = _history(connection, table.name, ids)
            references = _references(table)
            for item in items:
                values: dict[str, Any] = item.get("_values") or from_json(table, item["row"])
                record = PlannedRecord(
                    table=table.name,
                    id=str(item["id"]),
                    change_id=str(item["change_id"]),
                    history=[str(h) for h in item["history"]],
                    values=values,
                    action="insert",
                    label=_label(table.name, values),
                )
                local = local_rows.get(record.id)
                if local is None and table.name == "settings":
                    local = self._shared_setting(connection, values)
                    if local is not None:
                        record.local_id = str(local["id"])
                local_history = histories.get(record.local_id or record.id, [])
                if local is not None:
                    if table.name == "activities" or record.change_id in local_history:
                        record.action = "skip"
                    elif not local_history or local_history[-1] in record.history:
                        same = _comparable(table, local) == _comparable(table, values)
                        record.action = "converge" if same else "update"
                    else:
                        diffs = [
                            FieldDiff(key, value, incoming_value)
                            for key, value in _comparable(table, local).items()
                            if key not in {"id"}
                            and (incoming_value := _comparable(table, values).get(key)) != value
                        ]
                        record.differences = diffs
                        record.action = "conflict" if diffs else "converge"
                if record.action in {"insert", "update", "conflict"}:
                    missing = self._missing_reference(connection, references, values, will_exist)
                    if missing is not None:
                        record.action = "pending"
                        record.reason = missing
                if record.action in {"insert", "update", "conflict", "converge", "skip"}:
                    will_exist.setdefault(table.name, set()).add(record.id)
                plan.append(record)
        return plan

    @staticmethod
    def _shared_setting(connection: Connection, values: Mapping[str, Any]) -> dict[str, Any] | None:
        settings = TABLE_BY_NAME["settings"]
        row = (
            connection.execute(
                select(settings).where(
                    settings.c.key == values.get("key"),
                    settings.c.scope == values.get("scope"),
                    settings.c.deleted_at_utc.is_(None),
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else dict(row)

    @staticmethod
    def _missing_reference(
        connection: Connection,
        references: list[tuple[str, str]],
        values: Mapping[str, Any],
        will_exist: dict[str, set[str]],
    ) -> str | None:
        for column, referenced in references:
            target = values.get(column)
            if target is None or str(target) in will_exist.get(referenced, set()):
                continue
            other = Base.metadata.tables[referenced]
            if connection.scalar(select(other.c.id).where(other.c.id == target)) is None:
                return f"waits for {referenced} record {target}"
        return None

    def _possible_duplicates(
        self, connection: Connection, plan: Sequence[PlannedRecord]
    ) -> list[PossibleDuplicate]:
        organizations = TABLE_BY_NAME["organizations"]
        contacts = TABLE_BY_NAME["contacts"]
        found: list[PossibleDuplicate] = []
        for record in plan:
            if record.action != "insert" or record.values.get("deleted_at_utc") is not None:
                continue
            if record.table == "organizations":
                domain = identifying_domain(record.values.get("domain"))
                conditions = [
                    organizations.c.normalized_name == record.values.get("normalized_name")
                ]
                if domain:
                    conditions.append(organizations.c.domain == domain)
                for row in connection.execute(
                    select(organizations.c.id, organizations.c.name, organizations.c.domain).where(
                        organizations.c.deleted_at_utc.is_(None),
                        organizations.c.id != record.id,
                        conditions[0] if len(conditions) == 1 else (conditions[0] | conditions[1]),
                    )
                ):
                    reason = (
                        "same website domain" if domain and row.domain == domain else "same name"
                    )
                    found.append(
                        PossibleDuplicate(
                            "organizations",
                            record.id,
                            str(record.values.get("name")),
                            str(row.id),
                            str(row.name),
                            reason,
                        )
                    )
            elif record.table == "contacts" and record.values.get("email_normalized"):
                for contact in connection.execute(
                    select(contacts.c.id, contacts.c.name).where(
                        contacts.c.deleted_at_utc.is_(None),
                        contacts.c.id != record.id,
                        contacts.c.email_normalized == record.values["email_normalized"],
                    )
                ):
                    found.append(
                        PossibleDuplicate(
                            "contacts",
                            record.id,
                            str(record.values.get("name") or "Contact"),
                            str(contact.id),
                            str(contact.name or "Contact"),
                            "same email address",
                        )
                    )
        return found

    def _preview(
        self,
        token: str,
        file_name: str,
        contents: PackageContents,
        plan: list[PlannedRecord],
        connection: Connection,
    ) -> ImportPreview:
        manifest = contents.manifest
        imports = Base.metadata.tables["sync_imports"]
        already = (
            connection.scalar(
                select(imports.c.id).where(
                    imports.c.export_id == manifest["export_id"], imports.c.deleted_at_utc.is_(None)
                )
            )
            is not None
        )
        counts: dict[str, int] = {}
        by_table: dict[str, dict[str, int]] = {}
        for record in plan:
            counts[record.action] = counts.get(record.action, 0) + 1
            table_counts = by_table.setdefault(record.table, {})
            table_counts[record.action] = table_counts.get(record.action, 0) + 1
        warnings: list[str] = []
        recipient = manifest.get("recipient_device_id")
        if recipient and recipient != self._database.device_id:
            name = manifest.get("recipient_name") or "another computer"
            warnings.append(
                f"This package was prepared for {name}, not for this computer. Import it only "
                "if you are sure it was meant for you."
            )
        if already:
            warnings.append("This package was imported before; importing it again changes nothing.")
        if counts.get("pending"):
            warnings.append(
                f"{counts['pending']} records refer to records you have not received yet. They "
                "will be added automatically when a later package brings what they need."
            )
        return ImportPreview(
            token=token,
            file_name=file_name,
            export_id=str(manifest["export_id"]),
            source_device_id=str(manifest["source_device_id"]),
            source_actor_name=str(manifest.get("source_actor_name") or "A colleague"),
            created_at=str(manifest.get("created_at_utc") or ""),
            encrypted=bool(manifest.get("encrypted")),
            mode=str(manifest.get("mode") or "delta"),
            already_imported=already,
            counts=counts,
            by_table=by_table,
            conflicts=tuple(
                ConflictView(
                    f"{r.table}:{r.id}", r.table, r.local_id or r.id, r.label, tuple(r.differences)
                )
                for r in plan
                if r.action == "conflict"
            ),
            possible_duplicates=tuple(self._possible_duplicates(connection, plan)),
            warnings=tuple(warnings),
        )

    def apply(
        self,
        token: str,
        resolutions: Mapping[str, Mapping[str, str]] | None = None,
    ) -> ImportResult:
        """Import a staged package. ``resolutions[conflict key][field]`` is local|incoming."""
        with self._lock:
            staged = self._staged.get(token)
        if staged is None:
            raise SyncError(
                "This import preview has expired.", action="Choose the package file again."
            )
        resolutions = resolutions or {}
        contents = staged.contents
        backup = self._before_import() if self._before_import else None
        sync_imports = Base.metadata.tables["sync_imports"]
        now = self._database.clock.now()
        sync_import_id = new_id()
        try:
            with self._database.engine.begin() as connection:
                connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                existing = connection.scalar(
                    select(sync_imports.c.id).where(
                        sync_imports.c.export_id == contents.manifest["export_id"],
                        sync_imports.c.deleted_at_utc.is_(None),
                    )
                )
                plan = self._plan(connection, contents)
                for record in plan:
                    if record.action == "conflict":
                        chosen = resolutions.get(f"{record.table}:{record.id}", {})
                        unresolved = [
                            d.field
                            for d in record.differences
                            if chosen.get(d.field) not in {"local", "incoming"}
                        ]
                        if unresolved:
                            raise SyncError(
                                "Some conflicts have not been resolved.",
                                action="Choose which value to keep for every highlighted field, "
                                "then import again.",
                                detail=f"{record.table} {record.id}: {unresolved}",
                            )
                if existing is None:
                    connection.execute(
                        insert(sync_imports).values(
                            id=sync_import_id,
                            export_id=contents.manifest["export_id"],
                            source_device_id=contents.manifest["source_device_id"],
                            file_name=staged.file_name[:255],
                            file_sha256=contents.sha256,
                            status="applying",
                            imported_at_utc=None,
                            counts={},
                            created_at_utc=now,
                            updated_at_utc=now,
                            created_by_device_id=self._database.device_id,
                        )
                    )
                else:
                    sync_import_id = str(existing)
                counts: dict[str, int] = {}
                for record in plan:
                    self._apply_record(connection, record, resolutions, sync_import_id, now)
                    counts[record.action] = counts.get(record.action, 0) + 1
                applied, remaining = self._retry_pending(connection, now)
                counts["pending_applied"] = applied
                if existing is None:
                    connection.execute(
                        update(sync_imports)
                        .where(sync_imports.c.id == sync_import_id)
                        .values(
                            status="applied", imported_at_utc=now, counts=counts, updated_at_utc=now
                        )
                    )
        except IntegrityError as exc:
            raise SyncError(
                "The package could not be imported because it conflicts with your data in a "
                "way tg_sales cannot resolve automatically. Nothing was changed.",
                action="Send the tg_sales log file to your support contact.",
                detail=repr(exc.orig),
            ) from exc
        self.discard(token)
        logger.info("Sync package imported", extra={"context": {"counts": counts}})
        return ImportResult(
            sync_import_id,
            str(contents.manifest["export_id"]),
            counts,
            applied,
            remaining,
            str(backup) if backup else None,
        )

    def _log_history(
        self, connection: Connection, record: PlannedRecord, ids: Iterable[str]
    ) -> None:
        log = Base.metadata.tables["change_log"]
        known = set(
            _history(connection, record.table, [record.local_id or record.id]).get(
                record.local_id or record.id, []
            )
        )
        now = self._database.clock.now()
        for change_id in ids:
            if change_id in known:
                continue
            connection.execute(
                insert(log).values(
                    entity_table=record.table,
                    entity_id=record.local_id or record.id,
                    change_id=change_id,
                    device_id=None,
                    origin="sync",
                    changed_at_utc=now,
                )
            )
            known.add(change_id)

    def _apply_record(
        self,
        connection: Connection,
        record: PlannedRecord,
        resolutions: Mapping[str, Mapping[str, str]],
        sync_import_id: str,
        now: datetime,
    ) -> None:
        table = TABLE_BY_NAME[record.table]
        target_id = record.local_id or record.id
        set_change = text("SELECT set_config('tg_sales.applying_change_id', :c, true)")
        if record.action in {"insert", "update"}:
            self._log_history(connection, record, record.history[:-1])
            connection.execute(set_change, {"c": record.change_id})
            values = dict(record.values)
            if record.action == "insert":
                try:
                    with connection.begin_nested():
                        connection.execute(insert(table).values(**values))
                except IntegrityError:
                    # Same natural key as an existing record (e.g. the same Steam game
                    # saved on both computers); keep ours and report it.
                    record.action = "duplicate"
            else:
                values.pop("id", None)
                connection.execute(update(table).where(table.c.id == target_id).values(**values))
            connection.execute(set_change, {"c": ""})
            if record.action != "duplicate":
                self._log_history(connection, record, [record.change_id])
        elif record.action == "converge":
            self._log_history(connection, record, record.history)
        elif record.action == "conflict":
            self._log_history(connection, record, record.history)
            chosen = resolutions.get(f"{record.table}:{record.id}", {})
            merged = {
                d.field: record.values[d.field]
                for d in record.differences
                if chosen.get(d.field) == "incoming"
            }
            merged["updated_at_utc"] = now
            connection.execute(update(table).where(table.c.id == target_id).values(**merged))
            conflicts = Base.metadata.tables["conflicts"]
            for diff in record.differences:
                connection.execute(
                    insert(conflicts).values(
                        id=new_id(),
                        sync_import_id=sync_import_id,
                        entity_table=record.table,
                        entity_id=target_id,
                        field=diff.field,
                        local_value={"value": diff.local},
                        incoming_value={"value": diff.incoming},
                        status="resolved",
                        resolution=chosen.get(diff.field),
                        resolved_at_utc=now,
                        resolved_by_actor_id=self._actor_id,
                        created_at_utc=now,
                        updated_at_utc=now,
                        created_by_device_id=self._database.device_id,
                    )
                )
        elif record.action == "pending":
            pending = Base.metadata.tables["sync_pending"]
            exists = connection.scalar(
                select(pending.c.id).where(
                    pending.c.entity_table == record.table,
                    pending.c.entity_id == record.id,
                    pending.c.change_id == record.change_id,
                )
            )
            if exists is None:
                connection.execute(
                    insert(pending).values(
                        id=new_id(),
                        sync_import_id=sync_import_id,
                        entity_table=record.table,
                        entity_id=record.id,
                        change_id=record.change_id,
                        record={
                            "table": record.table,
                            "id": record.id,
                            "change_id": record.change_id,
                            "history": record.history,
                            "row": to_json(table, record.values),
                        },
                        reason=record.reason or "",
                        created_at_utc=now,
                        updated_at_utc=now,
                        created_by_device_id=self._database.device_id,
                    )
                )

    def _retry_pending(self, connection: Connection, now: datetime) -> tuple[int, int]:
        pending = Base.metadata.tables["sync_pending"]
        applied = 0
        while True:
            rows = connection.execute(
                select(pending.c.id, pending.c.record).where(pending.c.deleted_at_utc.is_(None))
            ).all()
            if not rows:
                return applied, 0
            plan = self._plan(connection, PackageContents({}, {}), [dict(r.record) for r in rows])
            planned_by_key = {(p.table, p.id, p.change_id): p for p in plan}
            progress = False
            for pending_id, stored in rows:
                planned = planned_by_key.get((stored["table"], stored["id"], stored["change_id"]))
                if planned is None or planned.action == "pending":
                    continue
                if planned.action == "conflict":
                    # Needs a person: keep it pending with an explanation.
                    connection.execute(
                        update(pending)
                        .where(pending.c.id == pending_id)
                        .values(
                            reason="changed on both computers; ask for a new export to review it",
                            updated_at_utc=now,
                        )
                    )
                    continue
                self._apply_record(connection, planned, {}, "", now)
                connection.execute(pending.delete().where(pending.c.id == pending_id))
                applied += 1
                progress = True
            if not progress:
                remaining = connection.scalar(
                    select(func.count())
                    .select_from(pending)
                    .where(pending.c.deleted_at_utc.is_(None))
                )
                return applied, int(remaining or 0)

    # --------------------------------------------------------------- history
    def history(self, limit: int = 50) -> list[SyncHistoryEntry]:
        exports = Base.metadata.tables["sync_exports"]
        imports = Base.metadata.tables["sync_imports"]
        entries: list[SyncHistoryEntry] = []
        with self._database.engine.connect() as connection:
            for row in connection.execute(
                select(exports).order_by(exports.c.created_at_utc.desc()).limit(limit)
            ).mappings():
                entries.append(
                    SyncHistoryEntry(
                        "export",
                        str(row["id"]),
                        row["created_at_utc"],
                        str(row["file_name"]),
                        {
                            "records": row["record_count"],
                            "events": row["event_count"],
                            "encrypted": row["encrypted"],
                            "mode": (row["watermark"] or {}).get("mode"),
                        },
                    )
                )
            for row in connection.execute(
                select(imports).order_by(imports.c.created_at_utc.desc()).limit(limit)
            ).mappings():
                entries.append(
                    SyncHistoryEntry(
                        "import",
                        str(row["id"]),
                        row["imported_at_utc"] or row["created_at_utc"],
                        str(row["file_name"]),
                        {
                            "status": row["status"],
                            "counts": row["counts"],
                            "source_device_id": row["source_device_id"],
                        },
                    )
                )
        return sorted(entries, key=lambda e: e.at, reverse=True)[:limit]

    def pending_count(self) -> int:
        pending = Base.metadata.tables["sync_pending"]
        with self._database.engine.connect() as connection:
            return int(
                connection.scalar(
                    select(func.count())
                    .select_from(pending)
                    .where(pending.c.deleted_at_utc.is_(None))
                )
                or 0
            )
