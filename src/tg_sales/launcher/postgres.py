# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""A private PostgreSQL server for one Windows user, run from portable binaries.

The official PostgreSQL Windows binaries (a zip, no installer and no
administrator rights) are kept in a ``runtime`` folder. The database cluster
itself lives in the per-user data folder, never in the program folder, so
replacing the application during an update cannot touch sales records.

Safety properties:

* The server listens on the loopback interface only (``127.0.0.1``); the
  ``pg_hba.conf`` written here accepts loopback connections only, always with
  SCRAM-SHA-256 passwords, and rejects everything else.
* Passwords are random, generated on first run, and stored in
  ``credentials.json`` inside the per-user data folder (readable only through
  the user's Windows account). Nothing is hard-coded.
* Two roles are created: an administrator used only for setup and backups,
  and the application role that owns the application database.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from tg_sales.errors import TgSalesError

logger = logging.getLogger(__name__)

ADMIN_ROLE = "tg_admin"
APP_ROLE = "tg_sales"
APP_DATABASE = "tg_sales"
DEFAULT_PORT = 54329
LOOPBACK = "127.0.0.1"
START_TIMEOUT_SECONDS = 90
CREDENTIALS_FILE = "credentials.json"
BIN_ENV_VAR = "TG_SALES_PG_BIN"

_HBA = """\
# Written by tg_sales. Loopback-only, password (SCRAM) authentication.
# TYPE  DATABASE  USER  ADDRESS        METHOD
host    all       all   127.0.0.1/32   scram-sha-256
host    all       all   ::1/128        scram-sha-256
"""

_CONF = """
# ---- tg_sales settings (appended on first run) ----
listen_addresses = '127.0.0.1'
port = {port}
password_encryption = 'scram-sha-256'
max_connections = 40
shared_buffers = 128MB
timezone = 'UTC'
log_timezone = 'UTC'
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%a.log'
log_truncate_on_rotation = on
log_rotation_age = 1d
log_rotation_size = 0
log_min_duration_statement = -1
"""


class PostgresRuntimeError(TgSalesError):
    """The local PostgreSQL server could not be found, set up, started or stopped."""


@dataclass(frozen=True)
class Credentials:
    admin_password: str
    app_password: str
    port: int = DEFAULT_PORT

    def app_url(self, host: str = LOOPBACK, database: str = APP_DATABASE) -> str:
        return f"postgresql+psycopg://{APP_ROLE}:{self.app_password}@{host}:{self.port}/{database}"

    def admin_url(self, host: str = LOOPBACK, database: str = "postgres") -> str:
        return (
            f"postgresql+psycopg://{ADMIN_ROLE}:{self.admin_password}@{host}:{self.port}/{database}"
        )


def find_binaries(search_roots: list[Path]) -> Path | None:
    """Return a ``bin`` folder containing ``pg_ctl.exe`` (or ``pg_ctl``).

    ``TG_SALES_PG_BIN`` wins; otherwise each root is searched for
    ``runtime/pg*/bin`` and ``runtime/postgresql/bin`` (newest version first).
    """
    explicit = os.environ.get(BIN_ENV_VAR, "").strip()
    candidates: list[Path] = [Path(explicit)] if explicit else []
    for root in search_roots:
        runtime = root / "runtime"
        if runtime.is_dir():
            found = sorted(runtime.glob("pg*/bin"), reverse=True)
            candidates += [runtime / "postgresql" / "bin", *found]
    for candidate in candidates:
        if (candidate / "pg_ctl.exe").is_file() or (candidate / "pg_ctl").is_file():
            return candidate
    return None


def port_is_free(port: int, host: str = LOOPBACK) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) != 0


class PostgresRuntime:
    """Controls one PostgreSQL cluster stored in ``home`` (``home/data``)."""

    def __init__(self, bin_dir: Path, home: Path, *, port: int = DEFAULT_PORT) -> None:
        self.bin_dir = bin_dir
        self.home = home
        self.data_dir = home / "data"
        self.log_file = home / "server.log"
        self._default_port = port

    # ------------------------------------------------------------------ helpers
    def _exe(self, name: str) -> str:
        exe = self.bin_dir / (f"{name}.exe" if os.name == "nt" else name)
        if not exe.is_file():
            raise PostgresRuntimeError(
                "The PostgreSQL program files are missing or incomplete.",
                action="Run setup.bat again to reinstall the database runtime.",
                detail=f"missing {exe}",
            )
        return str(exe)

    def _run(
        self, *args: str, timeout: float = 120, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("PGPASSWORD", None)
        env["PGTZ"] = "UTC"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Output goes to a temporary file, not a pipe: the server started by
        # ``pg_ctl start`` inherits the handles, and a pipe would then never close.
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as output:
            completed = subprocess.run(  # noqa: S603 - fixed executables from the runtime folder
                list(args),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                env=env,
                check=False,
                creationflags=creationflags,
            )
            output.seek(0)
            text = output.read()
        result = subprocess.CompletedProcess(completed.args, completed.returncode, text, "")
        if check and result.returncode != 0:
            raise PostgresRuntimeError(
                "The local database server reported an error.",
                action=f"See {self.log_file} for details, then run launch.bat again.",
                detail=f"{Path(args[0]).name} exited {result.returncode}: "
                f"{result.stdout.strip()[-2000:]}",
            )
        return result

    @property
    def credentials_file(self) -> Path:
        return self.home / CREDENTIALS_FILE

    # -------------------------------------------------------------- credentials
    def load_credentials(self) -> Credentials | None:
        try:
            data = json.loads(self.credentials_file.read_text(encoding="utf-8"))
            return Credentials(
                admin_password=str(data["admin_password"]),
                app_password=str(data["app_password"]),
                port=int(data.get("port", self._default_port)),
            )
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PostgresRuntimeError(
                "The local database settings file is damaged.",
                action="Restore it from a backup, or contact your support person.",
                detail=f"{self.credentials_file}: {exc!r}",
            ) from exc

    def _save_credentials(self, credentials: Credentials) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        partial = self.credentials_file.with_suffix(".partial")
        partial.write_text(json.dumps(asdict(credentials), indent=2), encoding="utf-8")
        partial.replace(self.credentials_file)

    # ------------------------------------------------------------------- state
    @property
    def initialized(self) -> bool:
        return (self.data_dir / "PG_VERSION").is_file()

    def is_running(self) -> bool:
        if not self.initialized:
            return False
        result = self._run(self._exe("pg_ctl"), "status", "-D", str(self.data_dir), check=False)
        return result.returncode == 0

    # --------------------------------------------------------------- lifecycle
    def initialize(self) -> Credentials:
        """Create the cluster with random passwords (first run only)."""
        if self.initialized:
            existing = self.load_credentials()
            if existing is None:
                raise PostgresRuntimeError(
                    "The local database exists but its settings file is missing.",
                    action="Restore credentials.json from a backup of the data folder.",
                    detail=str(self.credentials_file),
                )
            return existing
        port = self._default_port
        credentials = Credentials(
            admin_password=secrets.token_urlsafe(24),
            app_password=secrets.token_urlsafe(24),
            port=port,
        )
        if self.data_dir.exists():
            # An earlier, interrupted initdb: the folder is ours and unusable.
            shutil.rmtree(self.data_dir)
        self.home.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as scratch:
            pwfile = Path(scratch) / "pw"
            pwfile.write_text(credentials.admin_password, encoding="utf-8")
            self._run(
                self._exe("initdb"),
                "-D",
                str(self.data_dir),
                "-U",
                ADMIN_ROLE,
                "--auth=scram-sha-256",
                f"--pwfile={pwfile}",
                "--encoding=UTF8",
                "--locale=C",
                timeout=300,
            )
        (self.data_dir / "pg_hba.conf").write_text(_HBA, encoding="utf-8")
        with (self.data_dir / "postgresql.conf").open("a", encoding="utf-8") as conf:
            conf.write(_CONF.format(port=port))
        self._save_credentials(credentials)
        logger.info("Created local PostgreSQL cluster", extra={"context": {"home": str(self.home)}})
        return credentials

    def start(self) -> None:
        if self.is_running():
            return
        credentials = self.load_credentials()
        port = credentials.port if credentials else self._default_port
        if not port_is_free(port):
            raise PostgresRuntimeError(
                f"Another program is already using port {port}, which tg_sales needs for its "
                "database.",
                action="Close the other program, or restart Windows, then run launch.bat again.",
            )
        # A stale postmaster.pid after a power cut is handled by pg_ctl itself.
        self._run(
            self._exe("pg_ctl"),
            "start",
            "-D",
            str(self.data_dir),
            "-l",
            str(self.log_file),
            "-w",
            "-t",
            str(START_TIMEOUT_SECONDS),
            timeout=START_TIMEOUT_SECONDS + 30,
        )
        logger.info("Local PostgreSQL started", extra={"context": {"port": port}})

    def stop(self) -> None:
        if not self.is_running():
            return
        self._run(self._exe("pg_ctl"), "stop", "-D", str(self.data_dir), "-m", "fast", "-w")
        logger.info("Local PostgreSQL stopped")

    def ensure_app_database(self, credentials: Credentials) -> None:
        """Create the application role and database if they are missing (idempotent)."""
        import psycopg
        from psycopg import sql

        with (
            psycopg.connect(
                host=LOOPBACK,
                port=credentials.port,
                user=ADMIN_ROLE,
                password=credentials.admin_password,
                dbname="postgres",
                autocommit=True,
                connect_timeout=10,
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(APP_ROLE), sql.Literal(credentials.app_password)
                    )
                )
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_DATABASE,))
            if cursor.fetchone() is None:
                create = sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0")
                cursor.execute(
                    create.format(sql.Identifier(APP_DATABASE), sql.Identifier(APP_ROLE))
                )
            with contextlib.suppress(psycopg.Error):
                cursor.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                        sql.Identifier(APP_DATABASE)
                    )
                )

    def tool(self, name: str) -> str:
        """Path of a client tool such as ``pg_dump`` or ``pg_restore``."""
        return self._exe(name)
