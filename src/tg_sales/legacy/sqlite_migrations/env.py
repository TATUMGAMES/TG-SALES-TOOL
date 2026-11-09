# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

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
