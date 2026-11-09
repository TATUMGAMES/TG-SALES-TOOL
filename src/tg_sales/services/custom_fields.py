# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Managing custom field definitions (the values live on prospects and contacts).

A field's key and type never change once created, so stored values always
match their type. The label and description can be edited. Archiving a field
hides it from forms, imports and exports but keeps every stored value;
restoring it brings them back.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tg_sales.db.database import Database
from tg_sales.db.models import CustomField
from tg_sales.domain.custom_fields import (
    MAX_DESCRIPTION_LENGTH,
    MAX_FIELDS_PER_RECORD_TYPE,
    MAX_KEY_LENGTH,
    MAX_LABEL_LENGTH,
    CustomFieldInfo,
    FieldType,
    RecordType,
    custom_field_id,
    key_from_label,
)
from tg_sales.domain.importing import FIELD_SPECS, custom_header_key
from tg_sales.errors import TgSalesError
from tg_sales.services.lanes import shared_bookkeeping


class CustomFieldError(TgSalesError):
    """A custom field cannot be created or changed."""


@dataclass(frozen=True)
class CustomFieldDraft:
    label: str
    field_type: FieldType = FieldType.TEXT
    record_type: RecordType = RecordType.PROSPECT
    description: str | None = None


# Built-in field names a custom field may not repeat (it would be confusing in imports).
_BUILT_IN_LABELS = {custom_header_key(spec.label) for spec in FIELD_SPECS} | {
    custom_header_key(word)
    for word in ("name", "website", "notes", "tags", "email", "review date", "source")
}


def _info(row: CustomField) -> CustomFieldInfo:
    return CustomFieldInfo(
        id=row.id,
        record_type=RecordType(row.record_type),
        key=row.key,
        label=row.label,
        field_type=FieldType(row.field_type),
        description=row.description,
        sort_order=row.sort_order,
        archived=row.archived_at_utc is not None,
    )


def _clean_label(label: str) -> str:
    cleaned = " ".join(label.split())
    if not cleaned or len(cleaned) > MAX_LABEL_LENGTH:
        raise CustomFieldError(
            f"A custom field needs a name of 1 to {MAX_LABEL_LENGTH} characters.",
            action="Enter a short name such as “Account tier”.",
        )
    if custom_header_key(cleaned) in _BUILT_IN_LABELS:
        raise CustomFieldError(
            f"“{cleaned}” is already a built-in field.",
            action="Choose the built-in field in the list, or give the custom field another name.",
        )
    return cleaned


def _clean_description(text: str | None) -> str | None:
    cleaned = (text or "").strip() or None
    if cleaned and len(cleaned) > MAX_DESCRIPTION_LENGTH:
        raise CustomFieldError(
            "The description is too long.",
            action=f"Keep it under {MAX_DESCRIPTION_LENGTH} characters.",
        )
    return cleaned


def fields_in(
    session: Session, record_type: RecordType | None = None, *, include_archived: bool = True
) -> list[CustomFieldInfo]:
    query = select(CustomField).where(CustomField.deleted_at_utc.is_(None))
    if record_type is not None:
        query = query.where(CustomField.record_type == record_type.value)
    if not include_archived:
        query = query.where(CustomField.archived_at_utc.is_(None))
    rows = session.scalars(
        query.order_by(CustomField.record_type, CustomField.sort_order, CustomField.label)
    )
    return [_info(row) for row in rows]


class CustomFieldService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list(
        self, record_type: RecordType | None = None, *, include_archived: bool = True
    ) -> builtins.list[CustomFieldInfo]:
        with self._database.session() as session:
            return fields_in(session, record_type, include_archived=include_archived)

    def by_key(
        self, record_type: RecordType, *, include_archived: bool = False
    ) -> dict[str, CustomFieldInfo]:
        return {f.key: f for f in self.list(record_type, include_archived=include_archived)}

    def create(self, draft: CustomFieldDraft) -> CustomFieldInfo:
        label = _clean_label(draft.label)
        description = _clean_description(draft.description)
        with self._database.session() as session:
            existing = fields_in(session, draft.record_type)
            if len([f for f in existing if not f.archived]) >= MAX_FIELDS_PER_RECORD_TYPE:
                raise CustomFieldError(
                    f"There can be at most {MAX_FIELDS_PER_RECORD_TYPE} custom fields per "
                    "record type.",
                    action="Archive fields you no longer use.",
                )
            for other in existing:
                if custom_header_key(other.label) == custom_header_key(label):
                    raise CustomFieldError(
                        f"There is already a custom field called “{other.label}”"
                        + (" (archived)." if other.archived else "."),
                        action="Use it, restore it, or choose another name.",
                    )
            base = key_from_label(label)
            key, suffix = base, 2
            while True:
                row = session.get(CustomField, custom_field_id(draft.record_type, key))
                if row is None or row.deleted_at_utc is not None:
                    break
                key = f"{base[: MAX_KEY_LENGTH - len(str(suffix)) - 1]}_{suffix}"
                suffix += 1
            order = (
                session.scalar(
                    select(func.max(CustomField.sort_order)).where(
                        CustomField.record_type == draft.record_type.value
                    )
                )
                or 0
            ) + 10
            if row is None:
                row = CustomField(
                    id=custom_field_id(draft.record_type, key),
                    record_type=draft.record_type.value,
                    key=key,
                    **shared_bookkeeping(),
                )
                session.add(row)
            elif row.field_type != draft.field_type.value:
                # A deleted field with this key stored another type: use a fresh key so
                # old values are never read as the new type.
                raise CustomFieldError(  # pragma: no cover - deletion is not offered
                    "A removed field used this name with another type.",
                    action="Choose a different name.",
                )
            row.deleted_at_utc = None
            row.archived_at_utc = None
            row.label = label
            row.field_type = draft.field_type.value
            row.description = description
            row.sort_order = order
            session.flush()
            return _info(row)

    def _get(self, session: Session, field_id: str) -> CustomField:
        row = session.get(CustomField, field_id)
        if row is None or row.deleted_at_utc is not None:
            raise CustomFieldError("That custom field no longer exists.", action="Refresh.")
        return row

    def update(self, field_id: str, label: str, description: str | None) -> CustomFieldInfo:
        cleaned = _clean_label(label)
        with self._database.session() as session:
            row = self._get(session, field_id)
            for other in fields_in(session, RecordType(row.record_type)):
                if other.id != row.id and custom_header_key(other.label) == custom_header_key(
                    cleaned
                ):
                    raise CustomFieldError(
                        f"There is already a custom field called “{other.label}”.",
                        action="Choose another name.",
                    )
            row.label = cleaned
            row.description = _clean_description(description)
            session.flush()
            return _info(row)

    def set_archived(self, field_id: str, archived: bool) -> CustomFieldInfo:
        with self._database.session() as session:
            row = self._get(session, field_id)
            if archived and row.archived_at_utc is None:
                row.archived_at_utc = self._database.clock.now()
            elif not archived:
                row.archived_at_utc = None
            session.flush()
            return _info(row)
