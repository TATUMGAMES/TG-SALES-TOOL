# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Alembic environment for the PostgreSQL schema.

Migrations are only ever run through :mod:`tg_sales.db.database`, which passes
an open connection in ``config.attributes["connection"]`` and wraps the whole
upgrade in one transaction (PostgreSQL DDL is transactional, so a failed
upgrade leaves the database unchanged).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from tg_sales.db.models import Base

connection = context.config.attributes.get("connection")
if not isinstance(connection, Connection):
    raise RuntimeError("tg_sales migrations must be run with an open database connection.")

context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    compare_type=True,
    transaction_per_migration=False,
)
with context.begin_transaction():
    context.run_migrations()
