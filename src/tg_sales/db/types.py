"""Custom column types that behave the same on PostgreSQL and SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine

from tg_sales.domain.time import UTC_TEXT_LENGTH, ensure_utc, format_utc, parse_utc


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetime.

    PostgreSQL stores ``timestamp with time zone``; SQLite (legacy databases
    only) stores fixed-width, sortable UTC text. Naive datetimes are rejected
    on write, and values are always returned in UTC.
    """

    impl = String(UTC_TEXT_LENGTH)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TIMESTAMP(timezone=True))
        return dialect.type_descriptor(String(UTC_TEXT_LENGTH))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return ensure_utc(value)
        return format_utc(value)

    def process_result_value(self, value: Any | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return parse_utc(str(value))


def json_type() -> TypeEngine[Any]:
    """JSON stored as JSONB on PostgreSQL and as JSON text elsewhere."""
    return JSON().with_variant(JSONB(), "postgresql")
