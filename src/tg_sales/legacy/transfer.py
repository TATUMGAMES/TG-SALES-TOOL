# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Transfer a desktop (SQLite) tg_sales database into PostgreSQL, then verify it.

Guarantees:

* **The original file is never changed.** A verified copy is upgraded to the
  last desktop schema and read (see :mod:`tg_sales.legacy.sqlite_database`).
* **Identifiers and history are preserved**: every row keeps its id, its
  created/updated/deleted timestamps and its creating device id; activity
  events are copied as-is (they stay immutable).
* **Repeatable and idempotent**: rows already present with identical values
  are counted as ``already_present``; running the transfer again inserts
  nothing. A row present with *different* values is never overwritten; it is
  reported as a conflict. (Exception: built-in pipeline stages that this
  installation has never edited take the desktop names and order.)
* **Nothing is silently dropped**: a row that cannot be converted (malformed
  timestamp, JSON, enum value, missing referenced record) is reported with
  its table, id, column and original value, and saved in the report.
* **Atomic**: everything is written in one transaction; any failure leaves the
  PostgreSQL database unchanged.
* **Same computer identity**: when the PostgreSQL database is new, it adopts
  the desktop installation's device id and current salesperson, so sync
  history and authorship continue seamlessly.

Verification re-reads both databases and compares, table by table, the set of
ids and every column value (after the same normalization), plus activity
counts per type and the ordered stage history of every opportunity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Date, Integer, MetaData, Table, func, select, text, update
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import JSON, TypeDecorator

from tg_sales.db.database import DEVICE_ID_KEY, Database
from tg_sales.db.models import Base
from tg_sales.db.types import UTCDateTime
from tg_sales.domain.enums import ActivityType
from tg_sales.domain.lanes import TATUM_GAMES_LANES, label_for_key, lane_id
from tg_sales.domain.time import format_utc, parse_utc
from tg_sales.legacy.sqlite_database import create_sqlite_engine, prepare_copy
from tg_sales.services.identity import CURRENT_ACTOR_KEY

logger = logging.getLogger(__name__)

SYSTEM_DEVICE_ID = "00000000-0000-0000-0000-000000000000"
# Data tables that only the new version has (the desktop schema lacks them).
NEW_ONLY_TABLES = frozenset({"change_log", "report_records", "resource_links"})
# Tables whose rows say nothing about the user's own data; a database whose other
# tables are empty counts as "new".
SEED_TABLES = frozenset({"pipeline_stages", "settings", "actors", "sales_lanes"})


class TransferError(Exception):
    pass


@dataclass
class TableResult:
    source: int = 0
    inserted: int = 0
    already_present: int = 0
    updated_seed: int = 0
    conflicts: int = 0
    invalid: int = 0
    skipped_device_settings: int = 0


@dataclass
class Issue:
    table: str
    record_id: str | None
    kind: str  # invalid | conflict
    column: str | None
    message: str
    original: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransferReport:
    source_file: str
    source_sha256: str
    source_revision: str | None
    started_at: str
    finished_at: str | None = None
    dry_run: bool = False
    adopted_device_id: str | None = None
    tables: dict[str, TableResult] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    files_copied: dict[str, int] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues and bool(self.verification.get("ok"))

    def to_json(self) -> str:
        data = asdict(self)
        data["ok"] = self.ok
        return json.dumps(data, indent=2, default=str)

    def to_markdown(self) -> str:
        lines = [
            "# Desktop database transfer report",
            "",
            f"- Source: `{self.source_file}` (sha256 `{self.source_sha256[:16]}…`, "
            f"schema {self.source_revision})",
            f"- Started: {self.started_at}  Finished: {self.finished_at}",
            f"- Dry run: {'yes' if self.dry_run else 'no'}",
            f"- Device id adopted: {self.adopted_device_id or 'no'}",
            f"- Result: **{'OK' if self.ok else 'NEEDS ATTENTION'}**",
            "",
            "| Table | Source rows | Inserted | Already present | Seed updated | Conflicts "
            "| Invalid | Device settings kept |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for name, r in self.tables.items():
            lines.append(
                f"| {name} | {r.source} | {r.inserted} | {r.already_present} | "
                f"{r.updated_seed} | {r.conflicts} | {r.invalid} | {r.skipped_device_settings} |"
            )
        lines += ["", "## Verification", ""]
        for key, value in self.verification.items():
            lines.append(f"- {key}: {value}")
        if self.files_copied:
            lines += ["", "## Files copied", ""]
            lines += [f"- {k}: {v}" for k, v in self.files_copied.items()]
        lines += ["", f"## Issues ({len(self.issues)})", ""]
        for issue in self.issues[:500]:
            lines.append(
                f"- [{issue.kind}] {issue.table} {issue.record_id} "
                f"{issue.column or ''}: {issue.message}"
            )
        return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _target_tables() -> list[Table]:
    return [t for t in Base.metadata.sorted_tables if t.name not in NEW_ONLY_TABLES]


class _Invalid(Exception):  # noqa: N818 - internal signal
    def __init__(self, column: str, message: str) -> None:
        super().__init__(message)
        self.column = column
        self.message = message


def _convert(table: Table, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one SQLite row to Python values for ``table``; raise _Invalid on bad data."""
    out: dict[str, Any] = {}
    for column in table.columns:
        name = column.name
        if name not in raw:
            if column.nullable or column.default is not None or column.server_default is not None:
                continue
            raise _Invalid(name, "column missing in the desktop database")
        value = raw[name]
        column_type = column.type
        if isinstance(column_type, TypeDecorator) and isinstance(column_type, UTCDateTime):
            if value is None:
                out[name] = None
                continue
            try:
                out[name] = parse_utc(str(value))
            except ValueError as exc:
                raise _Invalid(name, f"malformed timestamp {value!r}") from exc
            continue
        if value is None:
            out[name] = None
            continue
        if isinstance(column_type, JSON) or getattr(column_type, "impl", None) is JSON:
            if isinstance(value, (bytes, str)):
                try:
                    out[name] = json.loads(value)
                except ValueError as exc:
                    raise _Invalid(name, "malformed JSON") from exc
            else:
                out[name] = value
            continue
        if isinstance(column_type, Boolean):
            out[name] = bool(value)
            continue
        if isinstance(column_type, Date):
            try:
                out[name] = value if isinstance(value, date) else date.fromisoformat(str(value))
            except ValueError as exc:
                raise _Invalid(name, f"malformed date {value!r}") from exc
            continue
        if isinstance(column_type, SqlEnum):
            allowed = set(column_type.enums)
            if str(value) not in allowed:
                raise _Invalid(name, f"unknown value {value!r}")
            out[name] = str(value)
            continue
        if isinstance(column_type, Integer) and isinstance(value, str):
            try:
                out[name] = int(value)
            except ValueError as exc:
                raise _Invalid(name, f"not a number {value!r}") from exc
            continue
        out[name] = value
    return out


def _comparable(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return value.value  # enums
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _row_key(table: Table, row: Mapping[Any, Any]) -> dict[str, Any]:
    return {c.name: _comparable(row.get(c.name)) for c in table.columns}


def _jsonable(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        k: (v if isinstance(v, (str, int, float, bool, type(None))) else repr(v))
        for k, v in raw.items()
    }


def _read_source(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    """Read every row as raw SQLite values (no type processing, so bad data can be reported)."""
    meta = MetaData()
    meta.reflect(engine)
    data: dict[str, list[dict[str, Any]]] = {}
    with engine.connect() as connection:
        for table in _target_tables():
            if table.name not in meta.tables:
                data[table.name] = []
                continue
            result = connection.exec_driver_sql(f'SELECT * FROM "{table.name}"')  # noqa: S608
            names = list(result.keys())
            data[table.name] = [dict(zip(names, row, strict=True)) for row in result]
    return data


def _is_new(connection: Connection) -> bool:
    for table in _target_tables():
        if table.name in SEED_TABLES:
            continue
        if connection.scalar(select(text("1")).select_from(table).limit(1)) is not None:
            return False
    return True


def _adopt_identity(
    connection: Connection,
    source: dict[str, list[dict[str, Any]]],
    report: TransferReport,
    now: datetime,
) -> None:
    """Take over the desktop installation's device id and current salesperson."""
    settings = Base.metadata.tables["settings"]
    by_key = {
        (row.get("key"), row.get("scope")): row
        for row in source.get("settings", [])
        if row.get("deleted_at_utc") is None
    }
    device = by_key.get((DEVICE_ID_KEY, "device"))
    actor = by_key.get((CURRENT_ACTOR_KEY, "device"))
    if device is None:
        return
    current_actor = connection.scalar(
        select(settings.c.value).where(
            settings.c.key == CURRENT_ACTOR_KEY,
            settings.c.scope == "device",
            settings.c.deleted_at_utc.is_(None),
        )
    )
    # Device-scoped settings are replaced by the desktop ones (same computer, same identity).
    connection.execute(
        settings.delete().where(
            settings.c.scope == "device",
            settings.c.key.in_([DEVICE_ID_KEY, CURRENT_ACTOR_KEY]),
        )
    )
    report.adopted_device_id = str(json.loads(device["value"]))
    if actor is not None and current_actor is not None:
        # The placeholder salesperson created on first start is unused in a new database.
        actors = Base.metadata.tables["actors"]
        connection.execute(
            update(actors)
            .where(actors.c.id == str(current_actor), actors.c.deleted_at_utc.is_(None))
            .values(deleted_at_utc=now, updated_at_utc=now)
        )


def _copy_files(legacy_root: Path, new_root: Path, report: TransferReport) -> None:
    """Copy snapshots, reports and the company logo, skipping files that already exist."""
    for folder in ("snapshots", "reports", "assets"):
        source = legacy_root / folder
        if not source.is_dir():
            continue
        copied = 0
        for path in source.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            target = new_root / folder / path.relative_to(source)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
        report.files_copied[folder] = copied


def transfer(
    source_file: Path,
    target: Database,
    *,
    data_root: Path | None = None,
    dry_run: bool = False,
    copy_files: bool = True,
) -> TransferReport:
    """Transfer ``source_file`` into ``target`` and verify. See the module docstring."""
    report = TransferReport(
        source_file=str(source_file),
        source_sha256=_sha256(source_file) if source_file.is_file() else "",
        source_revision=None,
        started_at=format_utc(target.clock.now()),
        dry_run=dry_run,
    )
    with tempfile.TemporaryDirectory(prefix="tg_sales_legacy_") as scratch:
        copy, revision = prepare_copy(source_file, Path(scratch))
        report.source_revision = revision
        engine = create_sqlite_engine(copy)
        try:
            source = _read_source(engine)
        finally:
            engine.dispose()

    known: dict[str, set[str]] = {}
    with target.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            if _is_new(connection):
                _adopt_identity(connection, source, report, target.clock.now())
            for table in _target_tables():
                rows = source.get(table.name, [])
                result = report.tables.setdefault(table.name, TableResult())
                result.source = len(rows)
                converted: list[tuple[dict[str, Any], dict[str, Any]]] = []
                for raw in rows:
                    record_id = str(raw.get("id")) if raw.get("id") is not None else None
                    try:
                        converted.append((_convert(table, raw), raw))
                    except _Invalid as bad:
                        result.invalid += 1
                        report.issues.append(
                            Issue(
                                table.name,
                                record_id,
                                "invalid",
                                bad.column,
                                bad.message,
                                _jsonable(raw),
                            )
                        )
                existing_ids = set(connection.scalars(select(table.c.id)))
                for values, raw in _drop_orphans(table, converted, existing_ids, known, report):
                    _insert(connection, table, values, result, report, raw)
                    known.setdefault(table.name, set()).add(str(values["id"]))
                known.setdefault(table.name, set()).update(str(i) for i in existing_ids)
            _ensure_lanes(connection, target.clock.now())
            _check_references(connection, report)
            if dry_run:
                transaction.rollback()
            else:
                transaction.commit()
        except BaseException:
            if transaction.is_active:
                transaction.rollback()
            raise

    if not dry_run:
        report.verification = verify(source, target)
        if copy_files and data_root is not None:
            _copy_files(source_file.parent.parent, data_root, report)
    report.finished_at = format_utc(target.clock.now())
    logger.info(
        "Desktop database transfer finished",
        extra={"context": {"ok": report.ok, "dry_run": dry_run, "issues": len(report.issues)}},
    )
    return report


def _insert(
    connection: Connection,
    table: Table,
    values: dict[str, Any],
    result: TableResult,
    report: TransferReport,
    raw: Mapping[str, Any],
) -> None:
    pk = table.c.id
    existing = connection.execute(select(table).where(pk == values["id"])).mappings().first()
    if existing is None:
        statement = pg_insert(table).values(**values).on_conflict_do_nothing().returning(table.c.id)
        inserted = connection.execute(statement).first() is not None
        if inserted:
            result.inserted += 1
        elif table.name == "settings" and values.get("scope") == "device":
            # This installation keeps its own per-computer settings.
            result.skipped_device_settings += 1
        else:  # a different row already holds a unique key
            result.conflicts += 1
            report.issues.append(
                Issue(
                    table.name,
                    str(values["id"]),
                    "conflict",
                    None,
                    "another record with the same unique key already exists",
                    _jsonable(raw),
                )
            )
        return
    # Compare only the columns the desktop version had; newer columns keep their values.
    incoming = {k: v for k, v in _row_key(table, values).items() if k in values}
    current = {k: v for k, v in _row_key(table, existing).items() if k in incoming}
    if current == incoming:
        result.already_present += 1
        return
    untouched_seed = (
        table.name == "pipeline_stages"
        and existing.get("created_by_device_id") == SYSTEM_DEVICE_ID
        and existing.get("updated_at_utc") == existing.get("created_at_utc")
    )
    if untouched_seed:
        connection.execute(update(table).where(pk == values["id"]).values(**values))
        result.updated_seed += 1
        return
    differing = sorted(k for k in incoming if incoming[k] != current.get(k))
    result.conflicts += 1
    report.issues.append(
        Issue(
            table.name,
            str(values["id"]),
            "conflict",
            ",".join(differing),
            "already exists with different values; kept the existing values",
            _jsonable(raw),
        )
    )


def _drop_orphans(
    table: Table,
    rows: list[tuple[dict[str, Any], dict[str, Any]]],
    existing_ids: set[str],
    known: dict[str, set[str]],
    report: TransferReport,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Report (and leave out) rows that refer to records that exist nowhere."""
    references = [
        (column.name, next(iter(column.foreign_keys)).column.table.name)
        for column in table.columns
        if column.foreign_keys
    ]
    kept = list(rows)
    changed = True
    while changed:  # self-references (corrections of corrections) need a fixed point
        changed = False
        own = existing_ids | {str(values["id"]) for values, _raw in kept}
        survivors = []
        for values, raw in kept:
            problem = None
            for column, referenced in references:
                value = values.get(column)
                if value is None:
                    continue
                pool = own if referenced == table.name else known.get(referenced, set())
                if str(value) not in pool:
                    problem = (column, f"refers to a missing {referenced} record {value}")
                    break
            if problem is None:
                survivors.append((values, raw))
                continue
            changed = True
            report.tables[table.name].invalid += 1
            report.issues.append(
                Issue(
                    table.name, str(values["id"]), "invalid", problem[0], problem[1], _jsonable(raw)
                )
            )
        kept = survivors
    return kept


def _ensure_lanes(connection: Connection, now: datetime) -> None:
    """Give every lane key used by transferred records a lane (the desktop lanes were fixed)."""
    lanes = Base.metadata.tables["sales_lanes"]
    opportunities = Base.metadata.tables["opportunities"]
    stages = Base.metadata.tables["pipeline_stages"]
    used = set(connection.scalars(select(opportunities.c.product_lane).distinct()))
    used |= set(
        connection.scalars(
            select(stages.c.product_lane).where(stages.c.product_lane.is_not(None)).distinct()
        )
    )
    present = set(connection.scalars(select(lanes.c.key)))
    presets = {lane.key: lane for lane in TATUM_GAMES_LANES}
    order = connection.scalar(select(func.max(lanes.c.sort_order))) or 0
    for key in sorted(used - present):
        order += 10
        preset = presets.get(key)
        connection.execute(
            pg_insert(lanes)
            .values(
                id=lane_id(key),
                key=key,
                name=preset.name if preset else label_for_key(key),
                description=preset.description if preset else None,
                color=preset.color if preset else None,
                sort_order=order,
                technical_handoff=preset.technical_handoff if preset else False,
                created_at_utc=now,
                updated_at_utc=now,
                created_by_device_id=SYSTEM_DEVICE_ID,
            )
            .on_conflict_do_nothing()
        )


def _check_references(connection: Connection, report: TransferReport) -> None:
    """Fail fast (before COMMIT) with a readable message if references are broken."""
    try:
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    except Exception as exc:
        raise TransferError(
            "Some records refer to records that are missing; nothing was transferred. "
            f"Details: {getattr(exc, 'orig', exc)!r}"
        ) from exc


def _normalized_source(table: Table, rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for raw in rows:
        try:
            values = _convert(table, raw)
        except _Invalid:
            continue
        # Only columns the desktop version had; newer columns keep their defaults.
        out[str(values["id"])] = {k: v for k, v in _row_key(table, values).items() if k in raw}
    return out


def verify(source: dict[str, list[dict[str, Any]]], target: Database) -> dict[str, Any]:
    """Compare every transferred row, activity counts and stage history (see module docstring)."""
    result: dict[str, Any] = {"ok": True}
    mismatches: list[str] = []
    with target.engine.connect() as connection:
        for table in _target_tables():
            expected = _normalized_source(table, source.get(table.name, []))
            if table.name == "settings":
                # Per-computer settings stay with the installation that owns them.
                expected = {k: v for k, v in expected.items() if v.get("scope") != "device"}
            if not expected:
                continue
            rows = connection.execute(
                select(table).where(table.c.id.in_(list(expected)))
            ).mappings()
            actual = {str(row["id"]): _row_key(table, row) for row in rows}
            missing = set(expected) - set(actual)
            differing = [
                key
                for key in expected
                if key in actual
                and any(actual[key].get(column) != value for column, value in expected[key].items())
            ]
            if table.name == "pipeline_stages":
                differing = [
                    k for k in differing if actual[k]["created_by_device_id"] != SYSTEM_DEVICE_ID
                ]
            if missing:
                mismatches.append(f"{table.name}: {len(missing)} missing")
            if differing:
                mismatches.append(f"{table.name}: {len(differing)} differ")
        activities = Base.metadata.tables["activities"]
        source_types = Counter(str(r["type"]) for r in source.get("activities", []))
        target_types = Counter(
            str(t)
            for t in connection.scalars(
                select(activities.c.type).where(
                    activities.c.id.in_([str(r["id"]) for r in source.get("activities", [])])
                )
            )
        )
        result["activity_counts_by_type_match"] = source_types == target_types
        stage_types = {ActivityType.STAGE_CHANGE.value, ActivityType.OPPORTUNITY_CREATED.value}

        def history(rows: Iterable[Mapping[Any, Any]]) -> dict[str, list[str]]:
            ordered: dict[str, list[tuple[str, str]]] = {}
            for row in rows:
                if str(row["type"]) in stage_types and row.get("opportunity_id"):
                    occurred = row["occurred_at_utc"]
                    stamp = occurred if isinstance(occurred, str) else format_utc(occurred)
                    ordered.setdefault(str(row["opportunity_id"]), []).append(
                        (stamp, str(row["id"]))
                    )
            return {k: [i for _t, i in sorted(v)] for k, v in ordered.items()}

        target_rows = (
            connection.execute(
                select(activities).where(
                    activities.c.id.in_([str(r["id"]) for r in source.get("activities", [])])
                )
            )
            .mappings()
            .all()
        )
        result["stage_history_matches"] = history(source.get("activities", [])) == history(
            target_rows
        )
    result["row_mismatches"] = mismatches
    result["ok"] = (
        not mismatches
        and result["activity_counts_by_type_match"]
        and result["stage_history_matches"]
    )
    return result


def write_report(report: TransferReport, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("-", "").replace(".", "")
    json_path = folder / f"legacy_transfer_{stamp}.json"
    md_path = folder / f"legacy_transfer_{stamp}.md"
    json_path.write_text(report.to_json(), encoding="utf-8")
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, md_path
