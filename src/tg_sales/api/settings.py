# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Server configuration from environment variables (prefix ``TG_SALES_``).

Nothing here is hard-coded to localhost except safe defaults. For the local
Windows app the launcher fills in the database URL of the private PostgreSQL
server; a future hosted deployment sets the same variables (see
``deploy/.env.example``).

Security rule: the server only listens on a loopback address unless
``TG_SALES_ALLOW_REMOTE`` is set, and even then refuses to start while
authentication is not configured — the CRM must never be reachable from a
network without sign-in and HTTPS.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tg_sales.errors import TgSalesError


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class ConfigurationError(TgSalesError):
    """The server configuration is incomplete or unsafe."""


def is_loopback(host: str) -> bool:
    if host in {"localhost", "localhost."}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TG_SALES_", extra="ignore")

    environment: Environment = Environment.PRODUCTION
    database_url: SecretStr | None = None
    # Administrator connection (create/rename databases) — needed only for restore.
    admin_database_url: SecretStr | None = None
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path | None = None
    static_dir: Path | None = None  # the built web app (web/dist)
    allowed_origins: list[str] = Field(default_factory=list)
    log_level: str = "INFO"
    allow_remote: bool = False
    # Inside a container the server must listen on the container's interface; the
    # compose file then publishes the port on the host's 127.0.0.1 only.
    container_local_only: bool = False
    pg_bin: Path | None = None
    time_zone: str | None = None  # IANA name; default: this computer's zone
    open_browser: bool = False
    # Scheduled automatic backups (hours; 0 disables).
    backup_interval_hours: int = Field(default=24, ge=0, le=24 * 30)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def check_safe(self) -> None:
        if is_loopback(self.host) or self.container_local_only:
            return
        raise ConfigurationError(
            f"tg_sales is configured to listen on {self.host}, which other computers could reach.",
            action=(
                "Use 127.0.0.1. Network access needs sign-in, permissions and HTTPS, which are "
                "not part of this version (see docs/DEPLOYMENT.md)."
            ),
        )

    @property
    def local_origins(self) -> list[str]:
        """Origins of this server itself (what a browser sends for same-origin requests)."""
        return [f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"]
