# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""An API client backed by a fresh PostgreSQL database and a fake Steam store."""

from __future__ import annotations

import json as jsonlib
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import URL
from tests.integration.conftest import FakeClock
from tests.integration.steam_fake import FakeSteam
from tests.pg import PgTestServer

from tg_sales.api.app import create_app
from tg_sales.api.context import AppContext
from tg_sales.api.settings import Environment, ServerSettings
from tg_sales.config import AppPaths
from tg_sales.integrations.http import HttpClient

HEADERS = {"X-TG-Sales": "1"}


class Api:
    """Thin helper: JSON calls with the anti-forgery header, and job polling."""

    def __init__(self, client: TestClient, context: AppContext) -> None:
        self.client = client
        self.context = context

    def get(self, path: str, **kwargs: Any) -> Any:
        response = self.client.get(f"/api{path}", **kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    def call(self, method: str, path: str, expect: int = 200, **kwargs: Any) -> Any:
        response = self.client.request(method, f"/api{path}", headers=HEADERS, **kwargs)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    def post(self, path: str, json: Any = None, expect: int = 200, **kwargs: Any) -> Any:
        return self.call("POST", path, expect, json=json, **kwargs)

    def wait(self, ref: dict[str, Any], timeout: float = 60) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.get(f"/jobs/{ref['job_id']}")
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(0.05)
        raise AssertionError(f"job {ref} did not finish")

    def run(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        job = self.wait(self.post(path, json, **kwargs))
        assert job["status"] == "succeeded", jsonlib.dumps(job, default=str)
        return job["result"]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 20, 15, 0, tzinfo=UTC))


@pytest.fixture
def fake_steam() -> FakeSteam:
    return FakeSteam()


@pytest.fixture
def api(
    pg_url: URL,
    pg_server: PgTestServer,
    data_root: Path,
    fake_steam: FakeSteam,
    clock: FakeClock,
) -> Iterator[Api]:
    paths = AppPaths(root=data_root, custom=True)
    paths.ensure()
    server = ServerSettings(
        environment=Environment.TEST,
        database_url=SecretStr(pg_url.render_as_string(hide_password=False)),
        admin_database_url=SecretStr(
            pg_server.url_for("postgres").render_as_string(hide_password=False)
        ),
        data_dir=data_root,
        pg_bin=pg_server.runtime.bin_dir if pg_server.runtime else None,
    )
    http = HttpClient(transport=fake_steam.transport(), min_interval=0, sleep=lambda _s: None)
    context = AppContext(server, paths, http=http, clock=clock)
    context.services.lanes.apply_preset("tatum_games")  # the lanes most tests use
    app = create_app(context)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield Api(client, context)
