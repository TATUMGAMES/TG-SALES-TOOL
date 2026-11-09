# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""The schema documentation must describe every table and column."""

from __future__ import annotations

import re
from pathlib import Path

from tg_sales.db.models import ENTITY_MODELS, Base

DOC = Path(__file__).resolve().parents[2] / "docs" / "DATA_MODEL.md"
BOOKKEEPING = {"id", "created_at_utc", "updated_at_utc", "created_by_device_id", "deleted_at_utc"}


def sections() -> dict[str, str]:
    text = DOC.read_text(encoding="utf-8")
    parts = re.split(r"^### `([a-z_]+)`\s*$", text, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_every_table_is_documented() -> None:
    documented = set(sections())
    tables = {table.name for table in Base.metadata.sorted_tables}
    assert tables == documented


def test_every_column_is_documented() -> None:
    docs = sections()
    missing = {
        table.name: sorted(
            column.name
            for column in table.columns
            if (column.name not in BOOKKEEPING or table.name == "change_log")
            and f"`{column.name}`" not in docs[table.name]
        )
        for table in Base.metadata.sorted_tables
    }
    assert {name: cols for name, cols in missing.items() if cols} == {}


def test_documented_revision_matches_latest_migration() -> None:
    from alembic.script import ScriptDirectory

    from tg_sales.db.database import alembic_config

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert f"**Schema revision: `{head}`**" in DOC.read_text(encoding="utf-8")


def test_entity_model_list_is_complete() -> None:
    infrastructure = {"change_log"}  # written by triggers; no bookkeeping columns
    assert {m.__tablename__ for m in ENTITY_MODELS} == {  # type: ignore[attr-defined]
        t.name for t in Base.metadata.sorted_tables
    } - infrastructure
