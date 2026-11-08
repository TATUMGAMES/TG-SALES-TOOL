"""Start and stop TG Sales CRM on this computer (used by launch.bat and stop.bat).

``start``:

1. Make sure only one copy runs: if tg_sales is already running, open the
   browser at it and exit.
2. Find the bundled PostgreSQL programs, create the private database server on
   first run (random passwords), start it and create the application database.
3. Open the database, which applies pending schema upgrades after a verified
   backup.
4. Serve the API and the web app on ``127.0.0.1`` (first free port from 8765)
   and open the default browser.
5. On Ctrl+C, closing the window or ``stop``: stop the web server, then the
   database server.

``stop`` asks a running copy to shut down (using a secret written to the lock
file, so web pages cannot do it) and stops the database server.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from pydantic import SecretStr

from tg_sales import APP_DISPLAY_NAME, __version__
from tg_sales.config import AppPaths, install_dir, is_frozen
from tg_sales.errors import TgSalesError
from tg_sales.launcher.postgres import PostgresRuntime, find_binaries, port_is_free
from tg_sales.logging_setup import configure_logging

logger = logging.getLogger(__name__)

LOCK_FILE = "server.lock.json"
FIRST_PORT = 8765
PORT_ATTEMPTS = 20
EXIT_ERROR = 1
STOP_HEADER = "X-TG-Sales-Stop"


def project_roots() -> list[Path]:
    """Folders that may contain ``runtime/`` and ``web/``: the install folder or the source tree."""
    roots = []
    folder = install_dir()
    if folder is not None:
        roots.append(folder)
    roots.append(Path(__file__).resolve().parents[3])
    return roots


def find_static() -> Path | None:
    for root in project_roots():
        for candidate in (root / "web" / "dist", root / "web"):
            if (candidate / "index.html").is_file():
                return candidate
    return None


def say(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def _read_lock(paths: AppPaths) -> dict[str, object] | None:
    try:
        data = json.loads((paths.root / LOCK_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _choose_port() -> int:
    for port in range(FIRST_PORT, FIRST_PORT + PORT_ATTEMPTS):
        if port_is_free(port):
            return port
    raise TgSalesError(
        "No free network port was found for tg_sales on this computer.",
        action="Restart Windows, then run launch.bat again.",
    )


def _runtime(paths: AppPaths) -> PostgresRuntime:
    binaries = find_binaries(project_roots())
    if binaries is None:
        raise TgSalesError(
            "The PostgreSQL database programs were not found.",
            action="Run setup.bat (or extract the complete release ZIP again), then launch.bat.",
        )
    return PostgresRuntime(binaries, paths.root / "postgres")


def start(args: argparse.Namespace) -> int:
    paths = AppPaths.resolve(args.data_dir)
    paths.ensure()
    configure_logging(paths.logs_dir, debug=args.debug)
    lock = _read_lock(paths)
    running_port = lock.get("port") if lock else None
    if isinstance(running_port, int) and _alive(running_port):
        url = f"http://127.0.0.1:{running_port}/"
        say(f"{APP_DISPLAY_NAME} is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    say(f"Starting {APP_DISPLAY_NAME} {__version__}...")
    runtime = _runtime(paths)
    say("Starting the database...")
    credentials = runtime.initialize()
    runtime.start()
    runtime.ensure_app_database(credentials)

    import uvicorn

    from tg_sales.api.app import create_app
    from tg_sales.api.context import AppContext
    from tg_sales.api.settings import ServerSettings

    port = args.port or _choose_port()
    os.environ.setdefault("TG_SALES_DESKTOP", "1")
    server_settings = ServerSettings(
        database_url=SecretStr(credentials.app_url()),
        admin_database_url=SecretStr(credentials.admin_url()),
        port=port,
        data_dir=paths.root,
        static_dir=find_static(),
        pg_bin=runtime.bin_dir,
    )
    server_settings.check_safe()
    if server_settings.static_dir is None:
        say("Note: the web app is not built (web/dist). Only the API is available.")
    say("Opening the database (upgrading it if needed)...")
    context = AppContext(server_settings, paths)
    app = create_app(context, start_scheduler=True)
    stop_secret = secrets.token_urlsafe(24)
    app.state.stop_secret = stop_secret

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", access_log=False, lifespan="on"
    )
    server = uvicorn.Server(config)
    app.state.request_stop = lambda: setattr(server, "should_exit", True)
    lock_path = paths.root / LOCK_FILE
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "port": port, "stop": stop_secret, "version": __version__}),
        encoding="utf-8",
    )
    url = f"http://127.0.0.1:{port}/"

    def announce() -> None:
        for _ in range(200):
            if _alive(port):
                say(f"\n{APP_DISPLAY_NAME} is running at {url}")
                say("Keep this window open while you use tg_sales. To quit, close this window")
                say("or run stop.bat.")
                if not args.no_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.1)

    threading.Thread(target=announce, daemon=True).start()
    try:
        server.run()
    finally:
        try:
            if not args.keep_database:
                say("Stopping the database...")
                runtime.stop()
        finally:
            # Removed last: stop.bat waits for it, so the database is down by then.
            lock_path.unlink(missing_ok=True)
        logger.info("tg_sales stopped")
    return 0


def stop(args: argparse.Namespace) -> int:
    paths = AppPaths.resolve(args.data_dir)
    lock = _read_lock(paths)
    if lock and isinstance(lock.get("port"), int):
        request = urllib.request.Request(
            f"http://127.0.0.1:{lock['port']}/api/system/shutdown",
            method="POST",
            headers={STOP_HEADER: str(lock.get("stop", "")), "X-TG-Sales": "1"},
        )
        try:
            urllib.request.urlopen(request, timeout=5).close()  # noqa: S310
            say("Asked tg_sales to stop.")
            for _ in range(300):
                if not (paths.root / LOCK_FILE).exists():
                    break
                time.sleep(0.1)
        except (urllib.error.URLError, OSError):
            (paths.root / LOCK_FILE).unlink(missing_ok=True)
    try:
        runtime = _runtime(paths)
        if runtime.is_running():
            try:
                runtime.stop()
            except TgSalesError:
                if runtime.is_running():  # not just a stop that was already under way
                    raise
            say("Database stopped.")
    except TgSalesError as exc:
        say(exc.display_text())
        return EXIT_ERROR
    say(f"{APP_DISPLAY_NAME} is stopped.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tg_sales", description=f"{APP_DISPLAY_NAME} launcher")
    parser.add_argument("command", nargs="?", default="start", choices=["start", "stop"])
    parser.add_argument("--data-dir", default=None, help="custom data folder")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--keep-database", action="store_true", help="leave PostgreSQL running")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    try:
        return start(args) if args.command == "start" else stop(args)
    except TgSalesError as exc:
        say("")
        say(exc.display_text())
        logger.error("Launcher error", extra={"context": {"detail": exc.detail}})
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    _ = is_frozen
    raise SystemExit(main())
