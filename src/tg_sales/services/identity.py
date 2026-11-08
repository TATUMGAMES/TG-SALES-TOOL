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
