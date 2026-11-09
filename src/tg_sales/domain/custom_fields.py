# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""User-defined (custom) fields for prospects and contacts.

A custom field has a permanent ``key``, a renamable ``label`` and a type. Its
values live in the record's ``custom_fields`` JSON object under the key, in a
JSON-friendly form per type:

======== ================================= ==========================
Type     Stored as                         Example
======== ================================= ==========================
text     string (up to 10,000 characters)  ``"Tier 1"``
number   number                            ``125000.5``
date     ISO date string                   ``"2026-03-14"``
url      http(s) address, kept exactly     ``"https://x.example/?q=1"``
boolean  true / false                      ``true``
======== ================================= ==========================

Values are validated the same way when typed in a form and when imported.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from tg_sales.domain.enums import ReleasePrecision
from tg_sales.domain.ids import stable_id
from tg_sales.domain.normalization import DateOrder, Flag, exact_url, parse_date, parse_flag

MAX_KEY_LENGTH = 64
MAX_LABEL_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 500
MAX_TEXT_LENGTH = 10_000
MAX_FIELDS_PER_RECORD_TYPE = 200


class RecordType(StrEnum):
    PROSPECT = "prospect"  # an organization
    CONTACT = "contact"


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    URL = "url"
    BOOLEAN = "boolean"


RECORD_TYPE_LABELS: dict[RecordType, str] = {
    RecordType.PROSPECT: "Prospect",
    RecordType.CONTACT: "Contact",
}
FIELD_TYPE_LABELS: dict[FieldType, str] = {
    FieldType.TEXT: "Text",
    FieldType.NUMBER: "Number",
    FieldType.DATE: "Date",
    FieldType.URL: "Web address (URL)",
    FieldType.BOOLEAN: "Yes / no",
}


def custom_field_id(record_type: RecordType, key: str) -> str:
    """Record id of a custom field (the same on every computer, so sync merges them)."""
    return stable_id(f"custom_field:{record_type.value}:{key}")


def key_from_label(label: str) -> str:
    """A field key derived from its label: ``"Account Tier"`` → ``"account_tier"``."""
    ascii_text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    return key[:MAX_KEY_LENGTH].rstrip("_") or "field"


@dataclass(frozen=True)
class CustomFieldInfo:
    id: str
    record_type: RecordType
    key: str
    label: str
    field_type: FieldType
    description: str | None
    sort_order: int
    archived: bool

    @property
    def target(self) -> str:
        """The import mapping target for this field, e.g. ``custom:prospect:account_tier``."""
        return f"custom:{self.record_type.value}:{self.key}"


class InvalidValueError(ValueError):
    """A value does not fit the field's type; the message explains why."""


_NUMBER_JUNK = re.compile(r"[\s,$€£¥]")


def _parse_number(text: str) -> float | int:
    cleaned = _NUMBER_JUNK.sub("", text)
    if cleaned.endswith("%"):
        raise InvalidValueError("Percentages are not numbers here; enter 0.25 for 25%.")
    try:
        number = float(cleaned)
    except ValueError as exc:
        raise InvalidValueError("Not a number.") from exc
    if not math.isfinite(number):
        raise InvalidValueError("Not a number.")
    return int(number) if number.is_integer() and abs(number) < 2**53 else number


def parse_value(
    field_type: FieldType,
    value: object,
    *,
    date_order: DateOrder = DateOrder.AUTO,
) -> object | None:
    """Validate ``value`` for a field of ``field_type``; return the stored form.

    Blank values return None (meaning "no value"). Invalid values raise
    :class:`InvalidValueError` with a short explanation; they are never
    silently changed into something else.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace("\x00", "").strip()
        if not text:
            return None
    else:
        text = str(value).strip()

    if field_type is FieldType.TEXT:
        if len(text) > MAX_TEXT_LENGTH:
            raise InvalidValueError(f"Longer than {MAX_TEXT_LENGTH:,} characters.")
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return text
    if field_type is FieldType.NUMBER:
        if isinstance(value, bool):
            raise InvalidValueError("Not a number.")
        if isinstance(value, int | float):
            if not math.isfinite(float(value)):
                raise InvalidValueError("Not a number.")
            return value
        return _parse_number(text)
    if field_type is FieldType.DATE:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        parsed = parse_date(text, date_order)
        if parsed.ambiguous:
            raise InvalidValueError(
                "Could be day/month or month/day; choose the date order to read it."
            )
        if parsed.value is None:
            raise InvalidValueError("Not a recognized date.")
        if parsed.precision is not ReleasePrecision.DAY:
            raise InvalidValueError("Not a full date (day, month and year).")
        return parsed.value.isoformat()
    if field_type is FieldType.URL:
        url = exact_url(text)
        if url is None:
            raise InvalidValueError("Not a valid web address (http or https).")
        return url
    if field_type is FieldType.BOOLEAN:
        if isinstance(value, bool):
            return value
        flag, recognized = parse_flag(value)
        if not recognized or flag is Flag.UNKNOWN:
            raise InvalidValueError("Use yes or no.")
        return flag is Flag.YES
    raise InvalidValueError("Unknown field type.")  # pragma: no cover - exhaustive


def clean_values(
    fields: Mapping[str, CustomFieldInfo],
    values: Mapping[str, Any],
) -> dict[str, object | None]:
    """Validate form values by field key; None means "clear the value".

    Raises :class:`InvalidValueError` naming the field for the first bad value.
    Unknown keys are refused so typos never create hidden data.
    """
    cleaned: dict[str, object | None] = {}
    for key, raw in values.items():
        info = fields.get(key)
        if info is None:
            raise InvalidValueError(f"There is no custom field “{key}”.")
        try:
            cleaned[key] = parse_value(info.field_type, raw, date_order=DateOrder.AUTO)
        except InvalidValueError as exc:
            raise InvalidValueError(f"{info.label}: {exc}") from exc
    return cleaned


def merged(existing: Mapping[str, Any], changes: Mapping[str, object | None]) -> dict[str, Any]:
    """``existing`` with ``changes`` applied (None removes a value; other keys are kept)."""
    result = dict(existing)
    for key, value in changes.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def display_value(field_type: FieldType, value: object) -> str:
    """A value as plain text for exports."""
    if value is None:
        return ""
    if field_type is FieldType.BOOLEAN:
        return "yes" if value is True else "no" if value is False else str(value)
    if field_type is FieldType.NUMBER and isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
