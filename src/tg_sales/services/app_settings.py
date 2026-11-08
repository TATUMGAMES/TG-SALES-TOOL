"""Application settings: the salesperson's name, appearance, backups, imports,
discovery, privacy and regional options.

Settings describe one installation (how *this* computer behaves), so they are
stored as a single device-scoped setting that never travels in sync packages.
The salesperson's display name is the actor record itself, so it does travel
with the records that person authored.
"""

from __future__ import annotations

from enum import StrEnum
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from tg_sales.db.database import Database
from tg_sales.domain.enums import SettingScope
from tg_sales.domain.normalization import DateOrder
from tg_sales.errors import TgSalesError
from tg_sales.repositories.actors import ActorRepository
from tg_sales.repositories.settings import SettingsRepository
from tg_sales.services.identity import DEFAULT_ACTOR_NAME

SETTINGS_KEY = "app_settings"
MAX_NAME_LENGTH = 80


class Theme(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class SettingsError(TgSalesError):
    """A setting value is not valid."""


class AppSettings(BaseModel):
    """Validated settings; unknown keys from newer versions are ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    theme: Theme = Theme.SYSTEM
    locale: str = Field(default="en-US", pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")
    time_zone: str | None = None  # None: this computer's time zone
    backup_interval_hours: int = Field(default=24, ge=0, le=24 * 30)
    backup_keep_latest: int = Field(default=10, ge=1, le=100)
    backup_keep_monthly: int = Field(default=6, ge=0, le=36)
    import_date_order: DateOrder = DateOrder.AUTO
    discovery_cache_hours: int = Field(default=24, ge=1, le=24 * 14)
    discovery_upcoming_days: int = Field(default=90, ge=1, le=365)
    discovery_recent_days: int = Field(default=150, ge=1, le=730)
    show_onboarding: bool = True

    @field_validator("time_zone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in available_timezones():
            raise ValueError(f"unknown time zone {value!r}")
        return value

    def zone(self) -> ZoneInfo | None:
        return ZoneInfo(self.time_zone) if self.time_zone else None


class SettingsService:
    def __init__(self, database: Database, actor_id: str) -> None:
        self._database = database
        self._actor_id = actor_id

    def get(self) -> AppSettings:
        with self._database.session() as session:
            raw = SettingsRepository(session).get(SETTINGS_KEY, SettingScope.DEVICE)
        if not isinstance(raw, dict):
            return AppSettings()
        try:
            return AppSettings.model_validate(raw)
        except ValidationError:
            return AppSettings()

    def update(self, changes: dict[str, object]) -> AppSettings:
        current = self.get().model_dump(mode="json")
        try:
            updated = AppSettings.model_validate({**current, **changes})
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first.get("loc", ()))
            raise SettingsError(
                f"The setting “{field}” is not valid: {first.get('msg', '')}.",
                action="Correct the value and save again.",
            ) from exc
        with self._database.session() as session:
            SettingsRepository(session).set(
                SETTINGS_KEY, updated.model_dump(mode="json"), SettingScope.DEVICE
            )
        return updated

    def display_name(self) -> str:
        with self._database.session() as session:
            actor = ActorRepository(session).get(self._actor_id)
            return actor.display_name if actor else DEFAULT_ACTOR_NAME

    def set_display_name(self, name: str) -> str:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise SettingsError(
                "Your name cannot be empty.", action="Enter the name colleagues know you by."
            )
        if len(cleaned) > MAX_NAME_LENGTH:
            raise SettingsError(
                f"Your name can be at most {MAX_NAME_LENGTH} characters.",
                action="Enter a shorter name.",
            )
        with self._database.session() as session:
            actor = ActorRepository(session).get(self._actor_id)
            if actor is None:  # pragma: no cover - created at startup
                raise SettingsError("Your user record is missing.", action="Restart tg_sales.")
            actor.display_name = cleaned
        return cleaned

    @property
    def is_first_run(self) -> bool:
        return self.display_name() == DEFAULT_ACTOR_NAME and self.get().show_onboarding
