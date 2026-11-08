"""Server for the browser end-to-end tests (web/e2e).

Serves the built web app and the real API on 127.0.0.1 with a throwaway
PostgreSQL database and the synthetic Steam store (no network access). With
``--database-url`` and ``--data-dir`` it reuses an existing database, which the
restart/persistence test uses to start a second server on the same data.

    python tests/e2e_server.py --port 8799 [--database-url URL --data-dir DIR] [--info-file F]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from tests.integration.steam_fake import FakeSteam  # noqa: E402
from tests.pg import start_test_server  # noqa: E402

from tg_sales.api.app import create_app  # noqa: E402
from tg_sales.api.context import AppContext  # noqa: E402
from tg_sales.api.settings import Environment, ServerSettings  # noqa: E402
from tg_sales.config import AppPaths  # noqa: E402
from tg_sales.integrations.http import HttpClient  # noqa: E402
from tg_sales.launcher.postgres import find_binaries  # noqa: E402


def stop_stale(scratch: Path) -> None:
    data = scratch / "pg" / "data"
    binaries = find_binaries([ROOT])
    if (data / "postmaster.pid").exists() and binaries is not None:
        subprocess.run(  # noqa: S603 - bundled pg_ctl
            [str(binaries / "pg_ctl.exe"), "stop", "-D", str(data), "-m", "immediate", "-w"],
            capture_output=True,
            check=False,
            timeout=60,
        )
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--database-url")
    parser.add_argument("--admin-url")
    parser.add_argument("--data-dir")
    parser.add_argument("--info-file", help="write the database URL and data folder here")
    parser.add_argument("--stop-only", action="store_true", help="stop the test database and exit")
    args = parser.parse_args()
    if args.stop_only:
        stop_stale(ROOT / "web" / ".e2e" / "run")
        return 0

    server = None
    if args.database_url:
        scratch = Path(tempfile.mkdtemp(prefix="tg_sales_e2e_"))
        url, admin = args.database_url, args.admin_url
        bin_dir = None
    else:
        # A fixed folder: a cluster left running by an interrupted run is stopped and replaced.
        scratch = ROOT / "web" / ".e2e" / "run"
        stop_stale(scratch)
        server = start_test_server(scratch)
        if server is None:
            sys.stderr.write("PostgreSQL binaries not found (runtime/pg*/bin).\n")
            return 1
        url = server.create_database().render_as_string(hide_password=False)
        admin = server.url_for("postgres").render_as_string(hide_password=False)
        bin_dir = server.runtime.bin_dir if server.runtime else None
    data_dir = Path(args.data_dir) if args.data_dir else scratch / "data folder é"
    paths = AppPaths(root=data_dir, custom=True)
    paths.ensure()
    if args.info_file:
        Path(args.info_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.info_file).write_text(
            json.dumps({"database_url": url, "admin_url": admin, "data_dir": str(data_dir)}),
            encoding="utf-8",
        )
    settings = ServerSettings(
        environment=Environment.TEST,
        database_url=SecretStr(url),
        admin_database_url=SecretStr(admin) if admin else None,
        port=args.port,
        data_dir=data_dir,
        static_dir=ROOT / "web" / "dist",
        pg_bin=bin_dir,
    )
    steam = FakeSteam()
    http = HttpClient(transport=steam.transport(), min_interval=0, sleep=lambda _s: None)
    context = AppContext(settings, paths, http=http)
    app = create_app(context)
    os.environ.pop("TG_SALES_DESKTOP", None)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        if server is not None:
            server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
