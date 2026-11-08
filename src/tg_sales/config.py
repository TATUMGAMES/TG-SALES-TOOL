"""Filesystem locations for user data and bundled read-only assets.

User data lives in a per-user writable directory, separate from the program
files, so that replacing the application folder during an update never touches
sales records:

* Default: ``%LOCALAPPDATA%\\TatumGames\\tg_sales`` (via platformdirs).
* Portable / custom location (explicit opt-in only): the ``--data-dir``
  command-line option, or the ``TG_SALES_DATA_DIR`` environment variable.
  The command-line option wins when both are given.

A custom data directory may not be placed inside the installed application
folder, because updates replace that folder.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from tg_sales import APP_AUTHOR, APP_NAME
from tg_sales.errors import DataDirectoryError

DATA_DIR_ENV_VAR = "TG_SALES_DATA_DIR"
DATABASE_FILENAME = "tg_sales.db"
PREFERENCES_FILENAME = "preferences.json"

_PACKAGE_DIR = Path(__file__).resolve().parent


def is_frozen() -> bool:
    """Return True when running from a packaged (PyInstaller) executable."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path | None:
    """Return the folder containing the packaged executable, or None in development."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return None


def resource_path(*parts: str) -> Path:
    """Return the path of a bundled, read-only static asset.

    Works both from source and from the packaged executable, where package
    data files are collected alongside the frozen modules.
    """
    return _PACKAGE_DIR.joinpath("resources", *parts)


def default_data_root() -> Path:
    """Return the default per-user data directory (``%LOCALAPPDATA%`` on Windows)."""
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR, roaming=False))


@dataclass(frozen=True)
class AppPaths:
    """Writable per-user locations used by the application."""

    root: Path
    custom: bool = False

    @property
    def database_dir(self) -> Path:
        return self.root / "data"

    @property
    def database_file(self) -> Path:
        return self.database_dir / DATABASE_FILENAME

    @property
    def preferences_file(self) -> Path:
        return self.root / PREFERENCES_FILENAME

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def snapshots_dir(self) -> Path:
        return self.root / "snapshots"

    @property
    def attachments_dir(self) -> Path:
        return self.root / "attachments"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def user_assets_dir(self) -> Path:
        return self.root / "assets"

    def all_dirs(self) -> tuple[Path, ...]:
        return (
            self.database_dir,
            self.backups_dir,
            self.logs_dir,
            self.snapshots_dir,
            self.attachments_dir,
            self.cache_dir,
            self.exports_dir,
            self.reports_dir,
            self.user_assets_dir,
        )

    @classmethod
    def resolve(
        cls,
        cli_data_dir: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> AppPaths:
        """Determine the data root from CLI option, environment, or default."""
        env = os.environ if environ is None else environ
        raw = cli_data_dir or env.get(DATA_DIR_ENV_VAR, "").strip() or None
        if raw is None:
            return cls(root=default_data_root(), custom=False)

        root = Path(raw).expanduser()
        if not root.is_absolute():
            raise DataDirectoryError(
                f"The data folder must be a full path, but '{raw}' is relative.",
                action="Specify a complete folder path, for example D:\\tg_sales_data.",
            )
        root = root.resolve()
        app_dir = install_dir()
        if app_dir is not None and root.is_relative_to(app_dir):
            raise DataDirectoryError(
                "The data folder cannot be inside the tg_sales program folder, "
                "because updating the app replaces that folder.",
                action="Choose a data folder outside the program folder.",
                detail=f"data_root={root} install_dir={app_dir}",
            )
        return cls(root=root, custom=True)

    def ensure(self) -> None:
        """Create all data directories and confirm the root is writable."""
        try:
            for directory in self.all_dirs():
                directory.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".write_test"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            raise DataDirectoryError(
                f"tg_sales cannot write to its data folder:\n{self.root}",
                action=(
                    "Check that the folder exists, that the disk is not full, and that "
                    "your Windows account has permission to write there."
                ),
                detail=repr(exc),
            ) from exc
