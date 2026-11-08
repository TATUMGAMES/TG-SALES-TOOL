"""Opening, migrating and checking the tg_sales PostgreSQL database.

Opening a database:

1. Read its schema revision. A database written by a newer tg_sales version,
   or a database containing other tables, is refused.
2. If an existing database needs upgrading, the caller-supplied backup
   function (a verified ``pg_dump``) runs first.
3. Apply migrations in a single transaction (PostgreSQL DDL is
   transactional); a failed upgrade leaves the database unchanged.
4. Make sure this installation has a persistent device id, and tag every
   connection with it for the change log.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from tg_sales.db import migrations_pg
from tg_sales.db.engine import create_pg_engine, make_session_factory, tag_connections
from tg_sales.db.models import Setting
from tg_sales.domain.enums import SettingScope
from tg_sales.domain.ids import new_id
from tg_sales.domain.time import Clock, SystemClock
from tg_sales.errors import TgSalesError

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(migrations_pg.__file__).resolve().parent
DEVICE_ID_KEY = "device_id"

# Called with (from_revision, to_revision) before an upgrade; returns the backup path.
PreUpgradeBackup = Callable[[str, str], Path]


class DatabaseOpenError(TgSalesError):
    """The database could not be reached or opened."""


class DatabaseCorruptError(TgSalesError):
    """The database is damaged or is not a tg_sales database."""


class DatabaseVersionError(TgSalesError):
    """The database was created by a newer version of tg_sales."""


class MigrationError(TgSalesError):
    """Upgrading the database schema failed; the database was left unchanged."""


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    problems: tuple[str, ...]
    checked_at: datetime
    full: bool


def alembic_config(migrations_dir: Path = MIGRATIONS_DIR) -> Config:
    config = Config()
    config.set_main_option("script_location", str(migrations_dir))
    return config


def head_revision(migrations_dir: Path = MIGRATIONS_DIR) -> str:
    head = ScriptDirectory.from_config(alembic_config(migrations_dir)).get_current_head()
    if head is None:  # pragma: no cover - the chain is bundled
        raise RuntimeError("migration chain is empty")
    return head


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _user_tables(engine: Engine) -> list[str]:
    return [name for name in inspect(engine).get_table_names() if name != "alembic_version"]


def migrate(
    engine: Engine,
    *,
    pre_upgrade_backup: PreUpgradeBackup | None = None,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> Path | None:
    """Upgrade the schema to the latest revision; return the safety backup path, if any."""
    config = alembic_config(migrations_dir)
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    current = current_revision(engine)
    if current == head:
        return None

    if current is not None:
        try:
            script.get_revision(current)
        except CommandError as exc:
            raise DatabaseVersionError(
                "This tg_sales database was created by a newer version of tg_sales.",
                action="Install the latest tg_sales release, then open the app again.",
                detail=f"database revision {current!r}, application head {head!r}",
            ) from exc
    elif _user_tables(engine):
        raise DatabaseCorruptError(
            "The configured PostgreSQL database already contains tables that do not belong "
            "to tg_sales.",
            action="Point tg_sales at an empty database, or at its own database.",
        )

    backup: Path | None = None
    if current is not None and head is not None and pre_upgrade_backup is not None:
        backup = pre_upgrade_backup(current, head)
        logger.info(
            "Database backed up before upgrade",
            extra={"context": {"from": current, "to": head, "backup": str(backup)}},
        )

    unchanged = "Your data was not changed."
    if backup is not None:
        unchanged += f" A backup was also saved to {backup}."
    try:
        with engine.connect() as connection, connection.begin():
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except Exception as exc:
        logger.exception("Database upgrade failed and was rolled back")
        raise MigrationError(
            "The database could not be upgraded to this version of tg_sales.",
            action=f"{unchanged} Please send the tg_sales log file to your support contact.",
            detail=repr(exc),
        ) from exc
    logger.info("Database schema upgraded", extra={"context": {"from": current, "to": head}})
    return backup


def _ensure_device_id(engine: Engine, clock: Clock) -> str:
    with Session(engine) as session, session.begin():
        existing = session.scalar(
            select(Setting).where(
                Setting.key == DEVICE_ID_KEY,
                Setting.scope == SettingScope.DEVICE,
                Setting.deleted_at_utc.is_(None),
            )
        )
        if existing is not None:
            return str(existing.value)
        device_id = new_id()
        now = clock.now()
        session.add(
            Setting(
                id=new_id(),
                key=DEVICE_ID_KEY,
                scope=SettingScope.DEVICE,
                value=device_id,
                created_at_utc=now,
                updated_at_utc=now,
                created_by_device_id=device_id,
            )
        )
        logger.info("Created device identity for this installation")
        return device_id


def translate_error(exc: DBAPIError) -> TgSalesError:
    """A user-facing error for a failure to reach or use the database."""
    message = str(exc.orig).lower()
    if "password authentication failed" in message or "authentication" in message:
        return DatabaseOpenError(
            "tg_sales could not sign in to its database.",
            action="Run launch.bat again; if the problem continues, contact your support person.",
            detail=repr(exc.orig),
        )
    if "does not exist" in message:
        return DatabaseOpenError(
            "The tg_sales database does not exist on the database server.",
            action="Run launch.bat, which creates it automatically.",
            detail=repr(exc.orig),
        )
    if isinstance(exc, OperationalError):
        return DatabaseOpenError(
            "tg_sales could not connect to its database server.",
            action="Close tg_sales and start it again with launch.bat.",
            detail=repr(exc.orig),
        )
    return DatabaseOpenError(
        "tg_sales could not open its database.",
        action="Close tg_sales and start it again with launch.bat.",
        detail=repr(exc.orig),
    )


class Database:
    """An open, migrated tg_sales database."""

    def __init__(
        self,
        engine: Engine,
        device_id: str,
        clock: Clock,
        pre_migration_backup: Path | None = None,
    ) -> None:
        self._engine = engine
        self._device_id = device_id
        self._clock = clock
        self._sessions: sessionmaker[Session] = make_session_factory(engine, clock, device_id)
        self.pre_migration_backup = pre_migration_backup

    @classmethod
    def open(
        cls,
        url: str | URL,
        *,
        clock: Clock | None = None,
        pre_upgrade_backup: PreUpgradeBackup | None = None,
        migrations_dir: Path = MIGRATIONS_DIR,
        pool_size: int = 5,
    ) -> Database:
        """Connect to the database at ``url``, upgrading its schema if needed."""
        clock = clock or SystemClock()
        engine = create_pg_engine(url, pool_size=pool_size)
        try:
            backup = migrate(
                engine, pre_upgrade_backup=pre_upgrade_backup, migrations_dir=migrations_dir
            )
            device_id = _ensure_device_id(engine, clock)
        except TgSalesError:
            engine.dispose()
            raise
        except DBAPIError as exc:
            engine.dispose()
            raise translate_error(exc) from exc
        tag_connections(engine, device_id)
        return cls(engine, device_id, clock, backup)

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def url(self) -> URL:
        return self._engine.url

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def clock(self) -> Clock:
        return self._clock

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A unit of work: commits on success, rolls back on any exception."""
        with self._sessions() as session, session.begin():
            yield session

    def schema_revision(self) -> str | None:
        return current_revision(self._engine)

    def check_integrity(self, *, full: bool = False) -> IntegrityReport:
        """Check the database answers, the schema is current and safeguards are in place.

        The full check also confirms every foreign key and check constraint is
        validated and counts rows in every table (which reads every page).
        """
        problems: list[str] = []
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                if current_revision(self._engine) != head_revision():
                    problems.append("schema revision is not current")
                triggers = set(
                    connection.scalars(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
                )
                if "trg_activities_immutable" not in triggers:
                    problems.append("activity immutability trigger is missing")
                unvalidated = list(
                    connection.scalars(
                        text("SELECT conname FROM pg_constraint WHERE NOT convalidated")
                    )
                )
                problems += [f"constraint not validated: {name}" for name in unvalidated]
                if full:
                    for table in _user_tables(self._engine):
                        connection.execute(text(f'SELECT count(*) FROM "{table}"'))  # noqa: S608
        except DBAPIError as exc:
            problems.append(f"database error: {exc.orig!r}")
        report = IntegrityReport(not problems, tuple(problems), self._clock.now(), full)
        if report.ok:
            logger.info("Database integrity check passed", extra={"context": {"full": full}})
        else:
            logger.error(
                "Database integrity check found problems",
                extra={"context": {"full": full, "problems": problems[:20]}},
            )
        return report

    def dispose(self) -> None:
        self._engine.dispose()
