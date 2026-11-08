from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tg_sales.logging_setup import (
    LOG_FILENAME,
    REDACTED,
    configure_logging,
    redact_mapping,
    redact_text,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("contact jane.doe+sales@studio.example now", "contact ***@studio.example now"),
        ("password=hunter2 ok", f"password={REDACTED} ok"),
        ("API_KEY: abc123", f"API_KEY: {REDACTED}"),
        ('token = "a b c"', f"token = {REDACTED}"),
        ("call +1 (555) 010-9999 today", f"call {REDACTED} today"),
        ("imported 1234567 rows on 2026-10-25 10:00", "imported 1234567 rows on 2026-10-25 10:00"),
        ("no sensitive content", "no sensitive content"),
    ],
)
def test_redact_text(raw: str, expected: str) -> None:
    assert redact_text(raw) == expected


def test_redact_mapping_masks_sensitive_keys_recursively() -> None:
    data = {
        "Email": "a@example.com",
        "rows": 3,
        "nested": {"passphrase": "x", "note": "mail me at x@example.org"},
        "items": ["ok", "y@example.net"],
    }
    assert redact_mapping(data) == {
        "Email": REDACTED,
        "rows": 3,
        "nested": {"passphrase": REDACTED, "note": "mail me at ***@example.org"},
        "items": ["ok", "***@example.net"],
    }


def _read_records(log_file: Path) -> list[dict[str, object]]:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


def test_configure_logging_writes_redacted_json(tmp_path: Path) -> None:
    log_file = configure_logging(tmp_path / "logs")
    assert log_file == tmp_path / "logs" / LOG_FILENAME

    log = logging.getLogger("tg_sales.test")
    log.info("Imported contact %s", "lead@studio.example", extra={"context": {"token": "t"}})
    try:
        raise ValueError("bad secret=shh")
    except ValueError:
        log.exception("Failed for owner@studio.example")
    log.debug("debug hidden at INFO level")

    records = _read_records(log_file)
    assert len(records) == 2
    first, second = records
    assert first["level"] == "INFO"
    assert first["msg"] == "Imported contact ***@studio.example"
    assert first["context"] == {"token": REDACTED}
    assert str(first["ts"]).endswith("+00:00")
    assert second["msg"] == "Failed for ***@studio.example"
    assert "shh" not in str(second["exc"])
    assert "ValueError" in str(second["exc"])


def test_configure_logging_is_idempotent_and_supports_debug(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    log_file = configure_logging(tmp_path, debug=True)
    logging.getLogger("tg_sales.test").debug("once")
    records = _read_records(log_file)
    assert [r["msg"] for r in records] == ["once"]
