"""CSV files that are safe to open in spreadsheet software.

Cells that a spreadsheet could interpret as a formula (starting with ``=``,
``+``, ``-``, ``@``, tab or carriage return) are prefixed with an apostrophe so
they display as text and never run (CSV/formula injection). Files are written
as UTF-8 with a byte-order mark so Excel detects the encoding, and replace the
target only once complete.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from tg_sales.domain.normalization import looks_like_formula
from tg_sales.errors import TgSalesError


class ExportError(TgSalesError):
    """A file could not be written."""


def safe_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return f"'{text}" if looks_like_formula(text) else text


def write_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence[object]]) -> int:
    """Write ``rows`` to ``path``; return the number of data rows written."""
    partial = path.with_name(path.name + ".partial")
    count = 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with partial.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)
            writer.writerow([safe_cell(h) for h in headers])
            for row in rows:
                writer.writerow([safe_cell(v) for v in row])
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        partial.replace(path)
    except OSError as exc:
        raise ExportError(
            f"The file could not be saved:\n{path}",
            action="Choose a folder you can write to, close the file if it is open in "
            "another program, and try again.",
            detail=repr(exc),
        ) from exc
    finally:
        partial.unlink(missing_ok=True)
    return count
