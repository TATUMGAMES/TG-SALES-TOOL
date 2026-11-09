# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Structured local logging with sensitive-field redaction.

Logs are written as one JSON object per line to a size-rotated file in the
user's logs folder. Before a record is written, email addresses,
international phone numbers, and secret-looking ``key=value`` pairs are
redacted from the message, exception text, and structured context.

Attach structured context with ``logger.info("msg", extra={"context": {...}})``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_FILENAME = "tg_sales.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 5

REDACTED = "[REDACTED]"

QUIET_LIBRARY_LOGGERS = ("alembic", "sqlalchemy", "httpx", "httpcore")

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "passphrase",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "email",
        "phone",
    }
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
# Only international-format numbers (leading "+") are treated as phone numbers,
# so dates, IDs and counts are never mangled.
_PHONE_RE = re.compile(r"\+\d[\d\s().\-]{6,}\d")
_SECRET_PAIR_RE = re.compile(
    r"(?i)\b(password|passwd|passphrase|secret|token|api[_-]?key|authorization)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)

# Credentials embedded in URLs, e.g. postgresql://user:password@host/db
_URL_CREDENTIALS_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^:/\s@]+:)[^@\s/]+@")

_HANDLER_MARKER = "_tg_sales_handler"


def redact_text(text: str) -> str:
    """Redact emails (keeping the domain), phone numbers, URL passwords and secret values."""
    text = _URL_CREDENTIALS_RE.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    text = _SECRET_PAIR_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    text = _EMAIL_RE.sub(lambda m: f"***@{m.group(1)}", text)
    return _PHONE_RE.sub(REDACTED, text)


def redact_value(value: Any) -> Any:
    """Recursively redact strings, mappings and sequences."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_value(item) for item in value]
    return value


def redact_mapping(data: Mapping[Any, Any]) -> dict[str, Any]:
    """Redact a mapping, fully masking values whose key names are sensitive."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        name = str(key)
        if name.lower() in SENSITIVE_KEYS:
            result[name] = REDACTED
        else:
            result[name] = redact_value(value)
    return result


class RedactionFilter(logging.Filter):
    """Redact the fully formatted message and any structured context in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = None
        context = getattr(record, "context", None)
        if isinstance(context, Mapping):
            record.context = redact_mapping(context)
        return True


class JsonFormatter(logging.Formatter):
    """Format records as single-line JSON objects with UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        context = getattr(record, "context", None)
        if context:
            payload["context"] = context
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(log_dir: Path, *, debug: bool = False) -> Path:
    """Install the rotating JSON file handler on the root logger.

    Safe to call more than once: handlers previously installed by this
    function are replaced rather than duplicated. Returns the log file path.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILENAME

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root.removeHandler(existing)
            existing.close()

    handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    setattr(handler, _HANDLER_MARKER, True)

    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    # Third-party libraries log routine details at INFO; tg_sales logs the outcomes.
    for noisy in QUIET_LIBRARY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.DEBUG if debug else logging.WARNING)
    return log_file
