"""Read access to SQLite databases written by the earlier desktop version.

:func:`prepare_copy` never touches the original file. It copies the database
with SQLite's online backup API, checks the copy's integrity, and upgrades the
copy to the last desktop schema revision with the desktop migration chain (run
in one transaction with foreign-key enforcement suspended, SQLite's documented
procedure for table rebuilds). The transfer tool then reads only the copy.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, create_engine, event

from tg_sales.errors import TgSalesError
from tg_sales.legacy import sqlite_migrations

MIGRATIONS_DIR = Path(sqlite_migrations.__file__).resolve().parent
BUSY_TIMEOUT_MS = 5000


class LegacyDatabaseError(TgSalesError):
    """The desktop database could not be read (damaged, unknown, or newer)."""


def _configure_connection(dbapi_connection: sqlite3.Connection, _record: Any) -> None:
    dbapi_connection.isolation_level = None  # SQLAlchemy issues BEGIN itself
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def create_sqlite_engine(database_file: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{database_file.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_MS / 1000},
    )
    event.listen(engine, "connect", _configure_connection)
    event.listen(engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
    return engine


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def legacy_head() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:  # pragma: no cover - the chain is bundled
        raise RuntimeError("legacy migration chain is empty")
    return head


def copy_database(source_file: Path, target_file: Path) -> Path:
    """Copy with SQLite's online backup API (safe while the file is open) and verify."""
    if not source_file.is_file():
        raise LegacyDatabaseError(
            f"The desktop database file was not found:\n{source_file}",
            action="Choose the tg_sales.db file from the desktop version's data folder.",
        )
    target_file.parent.mkdir(parents=True, exist_ok=True)
    partial = target_file.with_name(target_file.name + ".partial")
    try:
        with (
            closing(sqlite3.connect(f"file:{source_file.as_posix()}?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(partial)) as dst,
        ):
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise LegacyDatabaseError(
                "The desktop database is damaged and cannot be transferred.",
                action="Choose a backup copy of the desktop database instead.",
                detail=str(result),
            )
        partial.replace(target_file)
    except sqlite3.DatabaseError as exc:
        raise LegacyDatabaseError(
            "The chosen file is not a readable tg_sales desktop database.",
            action="Choose the tg_sales.db file from the desktop version's data folder.",
            detail=repr(exc),
        ) from exc
    finally:
        partial.unlink(missing_ok=True)
    return target_file


def schema_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def prepare_copy(source_file: Path, work_dir: Path) -> tuple[Path, str | None]:
    """Copy ``source_file`` into ``work_dir`` and upgrade the copy to the last desktop schema.

    Returns the copy's path and the original's schema revision.
    """
    copy = copy_database(source_file, work_dir / "legacy_copy.db")
    engine = create_sqlite_engine(copy)
    try:
        original_revision = schema_revision(engine)
        if original_revision is None:
            raise LegacyDatabaseError(
                "The chosen file is not a tg_sales desktop database.",
                action="Choose the tg_sales.db file from the desktop version's data folder.",
            )
        config = alembic_config()
        try:
            ScriptDirectory.from_config(config).get_revision(original_revision)
        except CommandError as exc:
            raise LegacyDatabaseError(
                "The desktop database comes from an unknown tg_sales version.",
                action="Contact your support person with the database file's version.",
                detail=f"revision {original_revision!r}",
            ) from exc
        if original_revision != legacy_head():
            with engine.connect() as connection:
                driver = connection.connection.driver_connection
                if not isinstance(driver, sqlite3.Connection):  # pragma: no cover
                    raise TypeError("expected a sqlite3 connection")
                driver.execute("PRAGMA foreign_keys = OFF")
                try:
                    with connection.begin():
                        config.attributes["connection"] = connection
                        command.upgrade(config, "head")
                finally:
                    driver.execute("PRAGMA foreign_keys = ON")
    finally:
        engine.dispose()
    return copy, original_revision
