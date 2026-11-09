# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""The local user's identity: this computer's actor record.

Each installation has one current actor (the salesperson using this computer),
remembered in a device-scoped setting. A neutral default display name is used
until the user enters their own, so no operating-system account name is ever
shared through sync packages.
"""

from __future__ import annotations

from tg_sales.db.database import Database
from tg_sales.domain.enums import SettingScope
from tg_sales.repositories.actors import ActorRepository
from tg_sales.repositories.settings import SettingsRepository

CURRENT_ACTOR_KEY = "current_actor_id"
DEFAULT_ACTOR_NAME = "Salesperson"


def ensure_local_actor(database: Database) -> str:
    """Return this computer's actor id, creating the actor on first run."""
    with database.session() as session:
        settings = SettingsRepository(session)
        actors = ActorRepository(session)
        actor_id = settings.get(CURRENT_ACTOR_KEY, SettingScope.DEVICE)
        if isinstance(actor_id, str) and actors.get(actor_id) is not None:
            return actor_id
        actor = actors.add(DEFAULT_ACTOR_NAME)
        settings.set(CURRENT_ACTOR_KEY, actor.id, SettingScope.DEVICE)
        return actor.id
