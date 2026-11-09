# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""One-line, human-readable summaries of activity events for timelines.

Logged interactions are described as logged ("Email logged"), never as sent,
because tg_sales does not send messages.
"""

from __future__ import annotations

from tg_sales.db.models import Activity
from tg_sales.domain.enums import ActivityType, RecordSource
from tg_sales.domain.opportunities import ACTIVITY_LABELS, LOGGABLE_TYPES

_ENTITY_NAMES = {
    "contacts": "Contact",
    "opportunities": "Opportunity",
    "pipeline_stages": "Stage",
    "games": "Game",
    "tasks": "Task",
}


def summarize(activity: Activity, stage_names: dict[str, str]) -> str:
    payload = activity.payload
    note = str(payload.get("note") or "").strip()
    match activity.type:
        case ActivityType.ORGANIZATION_CREATED:
            via = " by import" if activity.source is RecordSource.IMPORT else ""
            return f"Prospect created{via}"
        case ActivityType.NOTE:
            return f"Note: {payload.get('text', '')}"
        case ActivityType.FIELD_CHANGE:
            changes = payload.get("changes", {})
            entity = _ENTITY_NAMES.get(str(payload.get("entity")), "Prospect")
            fields = ", ".join(sorted(str(name).replace("_", " ") for name in changes))
            if set(changes) == {"archived_at_utc"}:
                archived = changes["archived_at_utc"].get("new") is not None
                return f"{entity} {'archived' if archived else 'restored'}"
            return f"{entity} updated: {fields}" if fields else f"{entity} updated"
        case ActivityType.OPPORTUNITY_CREATED:
            lane = str(payload.get("product_lane", "")).replace("_", " ")
            stage = stage_names.get(str(payload.get("stage_id")))
            return f"Opportunity created ({lane})" + (f" in {stage}" if stage else "")
        case ActivityType.STAGE_CHANGE:
            stage = stage_names.get(str(payload.get("to_stage_id")), "another stage")
            reason = payload.get("reason")
            return f"Moved to {stage}" + (f" — {reason}" if reason else "")
        case ActivityType.IMPORT_COMMITTED:
            return f"Imported from {payload.get('file_name', 'a file')}"
        case ActivityType.CORRECTION:
            return f"Correction: {payload.get('reason', '')}"
        case ActivityType.TASK_CREATED:
            return f"Task added: {payload.get('title', '')}"
        case ActivityType.TASK_COMPLETED:
            return f"Task completed: {payload.get('title', '')}"
        case ActivityType.TECHNICAL_HANDOFF:
            text = "Technical handoff draft prepared (copied for manual sending)"
            return f"{text}: {note}" if note else text
        case kind if kind in LOGGABLE_TYPES:
            text = f"{ACTIVITY_LABELS[kind]} logged"
            return f"{text}: {note}" if note else text
        case _:
            return ACTIVITY_LABELS.get(
                activity.type, activity.type.value.replace("_", " ").capitalize()
            )
