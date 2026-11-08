"""Globally unique identifiers.

Records get UUIDv7 identifiers (RFC 9562): 48 bits of Unix milliseconds
followed by 74 random bits. They are unique across computers without
coordination, and roughly time-ordered, which keeps SQLite indexes compact.

Built-in records that every installation must share (such as the default
pipeline stages) use deterministic UUIDv5 identifiers instead, so that two
computers never create different copies of the same default record.
"""

from __future__ import annotations

import secrets
import time
import uuid

# Fixed namespace for deterministic identifiers of built-in records.
TG_SALES_NAMESPACE = uuid.UUID("5f0b6d0e-8c1a-4c3e-9a57-3b0d2f9c7e41")

_MAX_TIMESTAMP_MS = (1 << 48) - 1


def uuid7(timestamp_ms: int | None = None) -> uuid.UUID:
    """Return a version 7 UUID for ``timestamp_ms`` (default: now)."""
    ms = time.time_ns() // 1_000_000 if timestamp_ms is None else timestamp_ms
    if not 0 <= ms <= _MAX_TIMESTAMP_MS:
        raise ValueError("timestamp out of range for UUIDv7")
    random_bits = int.from_bytes(secrets.token_bytes(10), "big")
    rand_a = random_bits >> 68  # 12 bits
    rand_b = random_bits & ((1 << 62) - 1)  # 62 bits
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def new_id() -> str:
    """Return a new record identifier as canonical text."""
    return str(uuid7())


def stable_id(name: str) -> str:
    """Return the deterministic identifier for a built-in record called ``name``."""
    return str(uuid.uuid5(TG_SALES_NAMESPACE, name))


def is_valid_id(value: str) -> bool:
    """True if ``value`` is a canonical lowercase UUID string."""
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def uuid7_timestamp_ms(value: str) -> int:
    """Return the millisecond timestamp embedded in a UUIDv7 string."""
    parsed = uuid.UUID(value)
    if parsed.version != 7:
        raise ValueError("not a UUIDv7")
    return parsed.int >> 80
