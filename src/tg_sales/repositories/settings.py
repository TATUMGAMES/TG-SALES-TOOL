"""Key/value settings stored in the database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tg_sales.db.models import Setting
from tg_sales.domain.enums import SettingScope


class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _find(self, key: str, scope: SettingScope) -> Setting | None:
        return self._session.scalar(
            select(Setting).where(
                Setting.key == key,
                Setting.scope == scope,
                Setting.deleted_at_utc.is_(None),
            )
        )

    def get(self, key: str, scope: SettingScope = SettingScope.SHARED, default: Any = None) -> Any:
        setting = self._find(key, scope)
        return default if setting is None else setting.value

    def set(self, key: str, value: Any, scope: SettingScope = SettingScope.SHARED) -> None:
        setting = self._find(key, scope)
        if setting is None:
            self._session.add(Setting(key=key, scope=scope, value=value))
        elif setting.value != value:
            setting.value = value
