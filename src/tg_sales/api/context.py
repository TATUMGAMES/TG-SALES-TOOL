# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Composition root of the web server: opens the database and builds the services.

The context owns everything long-lived: the PostgreSQL connection pool, the
use-case services, background jobs, staged import files and the automatic
backup schedule. :meth:`AppContext.reopen` rebuilds the database-dependent
parts after a restore or a desktop-database transfer.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy.engine import make_url

from tg_sales import __version__
from tg_sales.api.jobs import JobManager
from tg_sales.api.settings import ConfigurationError, ServerSettings
from tg_sales.config import AppPaths
from tg_sales.db.database import Database
from tg_sales.domain.time import Clock, SystemClock
from tg_sales.errors import TgSalesError
from tg_sales.integrations.cache import JsonFileCache
from tg_sales.integrations.http import HttpClient
from tg_sales.integrations.steam import SteamStoreAdapter
from tg_sales.integrations.website_contacts import WebsiteContactFinder
from tg_sales.reports.generator import ReportLibrary
from tg_sales.services.app_settings import AppSettings, SettingsService
from tg_sales.services.backups import BackupError, BackupManager, PgTools
from tg_sales.services.branding import BrandingService, BrandingStore, LogoStore
from tg_sales.services.custom_fields import CustomFieldService
from tg_sales.services.discovery import DiscoveryService
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.imports import ImportService
from tg_sales.services.kpis import KpiService
from tg_sales.services.lanes import LaneService
from tg_sales.services.pipeline import PipelineService
from tg_sales.services.playbook import PlaybookService
from tg_sales.services.prospects import ProspectService
from tg_sales.services.resources import ResourceService
from tg_sales.services.snapshots import SnapshotService
from tg_sales.sync.engine import SyncService

logger = logging.getLogger(__name__)

SCHEDULER_TICK_SECONDS = 600


@dataclass
class Services:
    prospects: ProspectService
    imports: ImportService
    pipeline: PipelineService
    lanes: LaneService
    custom_fields: CustomFieldService
    kpis: KpiService
    discovery: DiscoveryService
    playbook: PlaybookService
    snapshots: SnapshotService
    settings: SettingsService
    branding: BrandingService
    resources: ResourceService
    sync: SyncService


class AppContext:
    def __init__(
        self,
        server: ServerSettings,
        paths: AppPaths,
        *,
        http: HttpClient | None = None,
        clock: Clock | None = None,
    ) -> None:
        if server.database_url is None:
            raise ConfigurationError(
                "No database is configured.",
                action="Start tg_sales with launch.bat, or set TG_SALES_DATABASE_URL.",
            )
        self.server = server
        self.paths = paths
        self._clock: Clock = clock or SystemClock()
        self.jobs = JobManager()
        self.logo = LogoStore(paths.user_assets_dir)
        self.branding_store = BrandingStore(paths.user_assets_dir)
        self.reports = ReportLibrary(paths.reports_dir)
        self._http_override = http
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._scheduler: threading.Thread | None = None
        self.tools = PgTools.find(server.pg_bin)
        self.database: Database
        self.actor_id: str
        self.services: Services
        self.backups: BackupManager | None
        self._http: HttpClient | None = None
        self._open()

    # ------------------------------------------------------------- lifecycle
    @property
    def url(self) -> str:
        if self.server.database_url is None:  # checked in __init__
            raise ConfigurationError("No database is configured.", action="Use launch.bat.")
        return self.server.database_url.get_secret_value()

    def _make_backups(self, retention: AppSettings | None = None) -> BackupManager | None:
        if self.tools is None:
            return None
        admin = self.server.admin_database_url
        manager = BackupManager(
            self.tools,
            make_url(self.url),
            self.paths.backups_dir,
            self._clock,
            admin_url=make_url(admin.get_secret_value()) if admin else None,
        )
        if retention is not None:
            manager.keep_latest = retention.backup_keep_latest
            manager.keep_monthly = retention.backup_keep_monthly
        return manager

    def _open(self) -> None:
        backups = self._make_backups()

        def pre_upgrade(old: str, new: str) -> Path:
            if backups is None:
                raise BackupError(
                    "tg_sales cannot back up the database before upgrading it, because the "
                    "PostgreSQL backup programs were not found.",
                    action="Run setup.bat again, then start tg_sales.",
                )
            return self.paths.backups_dir / backups.create("pre-migration").name

        self.database = Database.open(self.url, clock=self._clock, pre_upgrade_backup=pre_upgrade)
        self.actor_id = ensure_local_actor(self.database)
        settings_service = SettingsService(self.database, self.actor_id)
        app_settings = settings_service.get()
        self.backups = self._make_backups(app_settings)
        zone = app_settings.zone()
        http = self._http_override or HttpClient()
        self._http = None if self._http_override else http
        steam = SteamStoreAdapter(
            http,
            JsonFileCache(self.paths.cache_dir / "discovery" / "steam"),
            self.database.clock,
            cache_ttl=timedelta(hours=app_settings.discovery_cache_hours),
        )
        self.services = Services(
            prospects=ProspectService(self.database, self.actor_id),
            imports=ImportService(self.database, self.actor_id),
            pipeline=PipelineService(self.database, self.actor_id),
            lanes=LaneService(self.database, self.actor_id),
            custom_fields=CustomFieldService(self.database),
            kpis=KpiService(self.database, zone=zone),
            discovery=DiscoveryService(
                self.database,
                self.actor_id,
                {steam.name: steam},
                WebsiteContactFinder(http),
                zone=zone,
            ),
            playbook=PlaybookService(self.database, self.actor_id),
            snapshots=SnapshotService(self.database, self.paths.snapshots_dir),
            settings=settings_service,
            branding=BrandingService(self.database, self.branding_store),
            resources=ResourceService(self.database),
            sync=SyncService(
                self.database,
                self.actor_id,
                settings_service.display_name,
                before_import=self._backup_before("pre-sync"),
                staging_dir=self.paths.cache_dir / "sync_staging",
            ),
        )

    def _backup_before(self, reason: str) -> Callable[[], Path | None]:
        def run() -> Path | None:
            if self.backups is None:
                logger.warning("Skipping automatic backup: backup programs not found")
                return None
            return self.paths.backups_dir / self.backups.create(reason).name

        return run

    def backup_before(self, reason: str) -> Path | None:
        return self._backup_before(reason)()

    def reopen(self) -> None:
        """Rebuild database-dependent services (after restore or a desktop transfer)."""
        with self._lock:
            self.database.dispose()
            if self._http is not None:
                self._http.close()
            self._open()

    def close(self) -> None:
        self._stop.set()
        self.jobs.shutdown()
        if self._http is not None:
            self._http.close()
        self.database.dispose()

    # ------------------------------------------------------------- schedule
    def start_scheduler(self) -> None:
        """Automatic backups at the configured interval (checked every few minutes)."""

        def loop() -> None:
            while not self._stop.wait(30 if self._scheduler is None else SCHEDULER_TICK_SECONDS):
                try:
                    self.run_scheduled_backup()
                except TgSalesError as exc:
                    logger.warning(
                        "Scheduled backup failed", extra={"context": {"detail": exc.detail}}
                    )
                except Exception:
                    logger.exception("Scheduled backup crashed")

        self._scheduler = threading.Thread(target=loop, name="tg_sales_scheduler", daemon=True)
        self._scheduler.start()

    def run_scheduled_backup(self) -> bool:
        settings = self.services.settings.get()
        if self.backups is None or settings.backup_interval_hours == 0:
            return False
        latest = self.backups.list()
        now = self.database.clock.now()
        if latest and now - latest[0].created_at < timedelta(hours=settings.backup_interval_hours):
            return False
        self.backups.keep_latest = settings.backup_keep_latest
        self.backups.keep_monthly = settings.backup_keep_monthly
        self.backups.create("scheduled")
        return True

    # --------------------------------------------------------------- desktop
    @property
    def desktop_integration(self) -> bool:
        """True when the server runs on the user's own computer (open folders, etc.)."""
        return self.server.environment != "test" and os.environ.get(
            "TG_SALES_DESKTOP", ""
        ).lower() in {"1", "true", "yes"}

    def open_path(self, path: Path) -> None:
        """Open a file or folder with the default program on this computer."""
        if not self.desktop_integration:
            raise TgSalesError(
                "Opening folders is only available when tg_sales runs on your own computer.",
                action="Download the file instead.",
            )
        if not path.exists():
            raise TgSalesError("That file or folder no longer exists.", action="Refresh the page.")
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - trusted path
        else:  # pragma: no cover - development on other systems
            subprocess.run(["xdg-open", str(path)], check=False)  # noqa: S603, S607

    @property
    def version(self) -> str:
        return __version__
