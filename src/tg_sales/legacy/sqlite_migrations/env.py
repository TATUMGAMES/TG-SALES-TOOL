"""Alembic environment for the desktop version's SQLite schema (legacy, upgrade only).

Run only by :func:`tg_sales.legacy.sqlite_database.prepare_copy` on a copy of
a desktop database, with an open connection in ``config.attributes``. Batch
mode is used so that table alterations work on SQLite.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

connection = context.config.attributes.get("connection")
if not isinstance(connection, Connection):
    raise RuntimeError("tg_sales migrations must be run with an open database connection.")

context.configure(connection=connection, target_metadata=None, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
