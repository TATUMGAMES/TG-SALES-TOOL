# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""PostgreSQL engine configuration and session bookkeeping.

Connections use psycopg 3 with a small connection pool, are checked before use
(so a restarted server is handled transparently), work in UTC, and tell the
database which computer is writing (``tg_sales.device_id``, used by the change
log that powers offline sync).

Sessions created by :func:`make_session_factory` automatically fill in the
bookkeeping columns of new rows, refresh ``updated_at_utc`` on changes, and
refuse to modify or delete immutable activity events (the database enforces
the same rule with a trigger).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from tg_sales.db.models import Activity, EntityMixin
from tg_sales.domain.ids import new_id
from tg_sales.domain.time import Clock

SESSION_CLOCK = "clock"
SESSION_DEVICE_ID = "device_id"
STATEMENT_TIMEOUT_MS = 120_000


class ImmutableRecordError(Exception):
    """Raised when code attempts to change or delete an immutable activity event."""


def normalize_url(url: str | URL) -> URL:
    """Return ``url`` using the psycopg 3 driver (``postgresql://`` is accepted)."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("tg_sales needs a PostgreSQL database URL (postgresql://…).")
    return parsed.set(drivername="postgresql+psycopg")


def create_pg_engine(url: str | URL, *, pool_size: int = 5, echo: bool = False) -> Engine:
    """Create an engine for the PostgreSQL database at ``url``."""
    return create_engine(
        normalize_url(url),
        pool_size=pool_size,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=echo,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c timezone=UTC -c statement_timeout={STATEMENT_TIMEOUT_MS}",
            "application_name": "tg_sales",
        },
    )


def tag_connections(engine: Engine, device_id: str) -> None:
    """Make every pooled connection report ``device_id`` to the change-log triggers."""

    def _set(dbapi_connection: Any, _record: Any) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SELECT set_config('tg_sales.device_id', %s, false)", (device_id,))
        dbapi_connection.commit()

    event.listen(engine, "connect", _set)
    engine.dispose()  # connections opened before the listener existed are replaced


def _stamp_and_guard(session: Session, _flush_context: Any, _instances: Any) -> None:
    clock: Clock = session.info[SESSION_CLOCK]
    device_id: str = session.info[SESSION_DEVICE_ID]
    now = clock.now()
    for obj in session.new:
        if isinstance(obj, EntityMixin):
            if not obj.id:
                obj.id = new_id()
            # Unset mapped attributes read as None on new objects despite their annotations.
            if getattr(obj, "created_at_utc", None) is None:
                obj.created_at_utc = now
            if getattr(obj, "updated_at_utc", None) is None:
                obj.updated_at_utc = obj.created_at_utc
            if not obj.created_by_device_id:
                obj.created_by_device_id = device_id
    for obj in session.dirty:
        if isinstance(obj, Activity) and session.is_modified(obj):
            raise ImmutableRecordError(
                "Activity events cannot be changed; record a correction event instead."
            )
        if isinstance(obj, EntityMixin) and session.is_modified(obj):
            obj.updated_at_utc = now
    for obj in session.deleted:
        if isinstance(obj, Activity):
            raise ImmutableRecordError("Activity events cannot be deleted.")


def make_session_factory(engine: Engine, clock: Clock, device_id: str) -> sessionmaker[Session]:
    """Return a session factory that stamps rows with ``clock`` and ``device_id``."""
    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        info={SESSION_CLOCK: clock, SESSION_DEVICE_ID: device_id},
    )
    event.listen(factory, "before_flush", _stamp_and_guard)
    return factory
