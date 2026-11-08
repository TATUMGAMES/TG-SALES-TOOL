"""A throwaway PostgreSQL server for the test session.

Uses ``TG_SALES_TEST_DATABASE_URL`` (an administrator URL, e.g. in CI) when
set; otherwise starts a private cluster from the portable binaries in
``runtime/`` inside a temporary folder. Each test gets a fresh database cloned
from a migrated template (``CREATE DATABASE … TEMPLATE``), so tests are
isolated and fast. The real per-user data folder is never touched.
"""

from __future__ import annotations

import itertools
import os
import socket
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from tg_sales.db.database import migrate
from tg_sales.db.engine import create_pg_engine
from tg_sales.launcher.postgres import Credentials, PostgresRuntime, find_binaries

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "tg_test_template"
URL_ENV_VAR = "TG_SALES_TEST_DATABASE_URL"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class PgTestServer:
    admin: URL
    runtime: PostgresRuntime | None = None

    def __post_init__(self) -> None:
        self._counter = itertools.count(1)
        self._prefix = f"tg_test_{os.getpid()}_"

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(
            host=self.admin.host,
            port=self.admin.port,
            user=self.admin.username,
            password=self.admin.password,
            dbname=self.admin.database or "postgres",
            autocommit=True,
        )

    def url_for(self, name: str) -> URL:
        return self.admin.set(database=name, drivername="postgresql+psycopg")

    def prepare_template(self) -> None:
        with self._connect() as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEMPLATE))
            )
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEMPLATE)))
        engine = create_pg_engine(self.url_for(TEMPLATE), pool_size=1)
        try:
            migrate(engine)  # schema and seed data only; each clone gets its own device id
        finally:
            engine.dispose()

    def create_database(self) -> URL:
        name = f"{self._prefix}{next(self._counter)}"
        with self._connect() as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(name), sql.Identifier(TEMPLATE)
                )
            )
        return self.url_for(name)

    def drop_database(self, url: URL) -> None:
        with self._connect() as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(str(url.database))
                )
            )

    def stop(self) -> None:
        if self.runtime is not None:
            self.runtime.stop()


def start_test_server(scratch: Path) -> PgTestServer | None:
    """Return a running server, or None when PostgreSQL is unavailable."""
    explicit = os.environ.get(URL_ENV_VAR, "").strip()
    if explicit:
        server = PgTestServer(make_url(explicit))
    else:
        binaries = find_binaries([ROOT])
        if binaries is None:
            return None
        runtime = PostgresRuntime(binaries, scratch / "pg", port=_free_port())
        credentials: Credentials = runtime.initialize()
        runtime.start()
        admin = make_url(credentials.admin_url())
        server = PgTestServer(admin, runtime)
    server.prepare_template()
    return server
