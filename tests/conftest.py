# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Shared pytest configuration.

Tests never touch the real per-user data folder. Database tests run against a
throwaway PostgreSQL server (see tests/pg.py); each test gets its own database.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy.engine import URL
from tests.pg import PgTestServer, start_test_server

from tg_sales.db.database import Database
from tg_sales.domain.time import Clock
from tg_sales.services.lanes import LaneService


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TG_SALES_DATA_DIR", raising=False)


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """A writable data folder whose path contains spaces and non-ASCII text."""
    root = tmp_path / "Données de vente ñ 販売"
    root.mkdir()
    return root


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgTestServer]:
    server = start_test_server(tmp_path_factory.mktemp("postgres"))
    if server is None:
        pytest.skip("PostgreSQL is not available (run scripts/setup_dev.ps1 or set the test URL)")
    yield server
    server.stop()


@pytest.fixture
def pg_url(pg_server: PgTestServer) -> Iterator[URL]:
    """A fresh, migrated, empty database (no device id yet)."""
    url = pg_server.create_database()
    yield url
    pg_server.drop_database(url)


@pytest.fixture
def make_database(pg_server: PgTestServer) -> Iterator[Callable[..., Database]]:
    """Factory for independent databases, e.g. one per simulated computer."""
    opened: list[tuple[Database, URL]] = []

    def factory(clock: Clock | None = None, *, lane_preset: str | None = "tatum_games") -> Database:
        """``lane_preset``: lanes to add (most tests use the original Tatum Games lanes;
        None keeps the defaults of a brand-new installation)."""
        url = pg_server.create_database()
        database = Database.open(url, clock=clock, pool_size=2)
        opened.append((database, url))
        if lane_preset is not None:
            LaneService(database, None).apply_preset(lane_preset)
        return database

    yield factory
    for database, url in opened:
        database.dispose()
        pg_server.drop_database(url)
