# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

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
