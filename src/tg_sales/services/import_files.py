# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Reading prospect files (CSV, Excel .xlsx, plain text) safely.

Files are treated as untrusted data:

* Size limits are enforced before reading; large files produce a warning.
* Excel files must be genuine ``.xlsx`` packages. Password-protected
  (encrypted) workbooks, legacy ``.xls``, binary ``.xlsb`` and macro-enabled
  files are refused. The package is checked for ZIP bombs before opening.
* Workbooks are read with formulas kept as their text; nothing is ever
  calculated, executed or followed (external links are not loaded).
* Text files are decoded as UTF-8 (with or without BOM), UTF-16 with a BOM,
  or Windows-1252 as a fallback, which is reported to the user.
* Text that cannot be split into consistent columns is reported as "cannot
  be read reliably" rather than guessed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Any

from tg_sales.cancellation import CancelToken
from tg_sales.domain.importing import CellValue, suggest_mapping
from tg_sales.domain.normalization import normalize_email, normalize_url
from tg_sales.errors import TgSalesError

MAX_FILE_BYTES = 50 * 1024 * 1024
WARN_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000
WARN_ROWS = 20_000
MAX_COLUMNS = 200
MAX_XLSX_UNCOMPRESSED_BYTES = 400 * 1024 * 1024
MAX_XLSX_COMPRESSION_RATIO = 200
SNIFF_BYTES = 64 * 1024
CONSISTENCY_THRESHOLD = 0.9

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_SIGNATURE = b"PK\x03\x04"


class FileKind(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    TXT = "txt"


SUPPORTED_EXTENSIONS = {".csv": FileKind.CSV, ".xlsx": FileKind.XLSX, ".txt": FileKind.TXT}
REFUSED_EXTENSIONS = {
    ".xls": "Old Excel (.xls) files are not supported. Open the file in Excel and save it "
    "as an Excel Workbook (.xlsx) or CSV, then import that file.",
    ".xlsm": "Macro-enabled workbooks (.xlsm) are refused for safety. Save a copy as an "
    "Excel Workbook (.xlsx) without macros, then import that file.",
    ".xlsb": "Binary workbooks (.xlsb) are not supported. Save a copy as an Excel Workbook "
    "(.xlsx) or CSV, then import that file.",
    ".xltm": "Macro-enabled templates are refused for safety. Save a copy as an Excel "
    "Workbook (.xlsx), then import that file.",
}


class ImportFileError(TgSalesError):
    """The file cannot be imported."""


@dataclass(frozen=True)
class SourceFile:
    path: Path
    name: str
    size_bytes: int
    sha256: str
    kind: FileKind
    sheet_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class RawTable:
    """Cells read from a file, before any interpretation."""

    headers: list[str]
    rows: list[list[CellValue]]
    row_numbers: list[int]
    description: str
    notes: list[str] = field(default_factory=list)
    reliable: bool = True
    problem: str | None = None
    sheet_name: str | None = None


def _refuse(message: str, action: str, detail: str | None = None) -> ImportFileError:
    return ImportFileError(message, action=action, detail=detail)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_xlsx_package(path: Path) -> None:
    with path.open("rb") as handle:
        signature = handle.read(8)
    if signature.startswith(OLE_SIGNATURE):
        raise _refuse(
            "This Excel file is password-protected or uses the old .xls format.",
            "Remove the password (or save as .xlsx) in Excel, then import the new file.",
        )
    if not signature.startswith(ZIP_SIGNATURE):
        raise _refuse(
            "This file is not a valid Excel workbook.",
            "Open it in Excel and save it as an Excel Workbook (.xlsx), or export it as CSV.",
        )
    try:
        with zipfile.ZipFile(path) as package:
            entries = package.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise _refuse(
            "This Excel file is damaged and cannot be read.",
            "Open it in Excel and save a new copy, or export it as CSV.",
            repr(exc),
        ) from exc
    names = {entry.filename.lower() for entry in entries}
    if "xl/workbook.xml" not in names or "[content_types].xml" not in names:
        raise _refuse(
            "This file is not a valid Excel workbook.",
            "Open it in Excel and save it as an Excel Workbook (.xlsx), or export it as CSV.",
        )
    if any(name.endswith("vbaproject.bin") for name in names):
        raise _refuse(
            "This workbook contains macros and is refused for safety.",
            "Save a copy as an Excel Workbook (.xlsx) without macros, then import that file.",
        )
    total = sum(entry.file_size for entry in entries)
    compressed = sum(entry.compress_size for entry in entries) or 1
    if total > MAX_XLSX_UNCOMPRESSED_BYTES or total / compressed > MAX_XLSX_COMPRESSION_RATIO:
        raise _refuse(
            "This workbook expands to an unsafe size and was not opened.",
            "Export the sheet you need as CSV and import that file instead.",
            f"uncompressed={total} compressed={compressed}",
        )


def _xlsx_sheet_names(path: Path) -> tuple[str, ...]:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except Exception as exc:  # openpyxl raises many types for malformed packages
        raise _refuse(
            "This Excel file could not be opened.",
            "Open it in Excel and save a new copy as .xlsx, or export it as CSV.",
            repr(exc),
        ) from exc
    try:
        return tuple(ws.title for ws in workbook.worksheets)
    finally:
        workbook.close()


def inspect_file(path: Path) -> SourceFile:
    """Validate a file chosen for import and collect its metadata."""
    extension = path.suffix.lower()
    if extension in REFUSED_EXTENSIONS:
        raise _refuse(
            "This file type cannot be imported.",
            REFUSED_EXTENSIONS[extension],
        )
    kind = SUPPORTED_EXTENSIONS.get(extension)
    if kind is None:
        raise _refuse(
            "This file type cannot be imported.",
            "Choose a CSV (.csv), Excel (.xlsx) or text (.txt) file.",
        )
    try:
        if not path.is_file():
            raise _refuse("The file was not found.", "Check the file location and try again.")
        size = path.stat().st_size
    except OSError as exc:
        raise _refuse(
            "The file could not be read.",
            "Check that the file exists and is not open in another program.",
            repr(exc),
        ) from exc
    if size == 0:
        raise _refuse("The file is empty.", "Choose a file that contains your prospect list.")
    if size > MAX_FILE_BYTES:
        raise _refuse(
            f"The file is too large to import ({size / 1024 / 1024:.0f} MB; the limit is "
            f"{MAX_FILE_BYTES // 1024 // 1024} MB).",
            "Split the list into smaller files and import them one at a time.",
        )
    warnings = []
    if size > WARN_FILE_BYTES:
        warnings.append(
            f"This is a large file ({size / 1024 / 1024:.0f} MB). Reading it may take a "
            "little while."
        )
    sheets: tuple[str, ...] = ()
    try:
        if kind is FileKind.XLSX:
            _check_xlsx_package(path)
            sheets = _xlsx_sheet_names(path)
            if not sheets:
                raise _refuse(
                    "This workbook has no worksheets.", "Choose a workbook that contains data."
                )
        digest = _sha256(path)
    except OSError as exc:
        raise _refuse(
            "The file could not be read.",
            "Check that the file is not open in another program, then try again.",
            repr(exc),
        ) from exc
    return SourceFile(path, path.name, size, digest, kind, sheets, tuple(warnings))


# -- text decoding --------------------------------------------------------------


def decode_text(data: bytes) -> tuple[str, str, list[str]]:
    """Decode text; return (text, encoding name, notes)."""
    notes: list[str] = []
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "UTF-8", notes
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "UTF-16", notes
        except UnicodeDecodeError as exc:
            raise _refuse(
                "The text in this file could not be decoded.",
                "Save the file as UTF-8 text or CSV, then import it again.",
                repr(exc),
            ) from exc
    if b"\x00" in data[:SNIFF_BYTES]:
        raise _refuse(
            "This file does not look like a text or CSV file.",
            "Choose a CSV, Excel (.xlsx) or plain text file.",
        )
    try:
        return data.decode("utf-8"), "UTF-8", notes
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp1252")
        encoding = "Windows-1252"
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        encoding = "Latin-1"
    notes.append(
        f"The file is not UTF-8, so it was read as {encoding}. Check that accented "
        "characters look right in the preview; if not, save the file as UTF-8 and import it "
        "again."
    )
    return text, encoding, notes


# -- delimited text ---------------------------------------------------------------

_DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "vertical bar"}
_KEY_VALUE = re.compile(r"^\s*([^:=\t]{1,60}?)\s*[:=]\s*(.*)$")


def _consistent_rows(rows: list[list[str]]) -> tuple[bool, int]:
    """Whether non-blank rows mostly share the header's width; also the width."""
    filled = [r for r in rows if any(cell.strip() for cell in r)]
    if not filled:
        return True, 0
    width = len(filled[0])
    matching = sum(1 for r in filled if len(r) == width)
    return matching / len(filled) >= CONSISTENCY_THRESHOLD, width


def _split(text: str, delimiter: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=False))


def _sniff_delimiter(text: str, candidates: str) -> str | None:
    sample = text[:SNIFF_BYTES]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=candidates)
    except csv.Error:
        dialect = None
    if dialect is not None and dialect.delimiter in candidates:
        rows = _split(sample, dialect.delimiter)
        consistent, width = _consistent_rows(rows[:-1] or rows)
        if consistent and width > 1:
            return str(dialect.delimiter)
    best: tuple[int, str] | None = None
    sample_rows = sample.splitlines()[:50]
    for delimiter in candidates:
        rows = _split("\n".join(sample_rows), delimiter)
        consistent, width = _consistent_rows(rows)
        if consistent and width > 1 and (best is None or width > best[0]):
            best = (width, delimiter)
    return best[1] if best else None


def _looks_like_data(cells: list[str]) -> bool:
    return any(normalize_email(c) or ("://" in c and normalize_url(c)) for c in cells)


def _table_from_rows(
    rows: list[list[str]], description: str, notes: list[str], *, header_row: bool = True
) -> RawTable:
    numbered = [(i + 1, r) for i, r in enumerate(rows) if any(c.strip() for c in r)]
    if not numbered:
        raise _refuse("The file has no data.", "Choose a file that contains your prospect list.")
    consistent, _ = _consistent_rows([r for _, r in numbered])
    first_number, first = numbered[0]
    if header_row and _looks_like_data(first):
        header_row = False
        notes.append("The first row looks like data, so columns were named Column 1, Column 2 ….")
    width = max(len(r) for _, r in numbered)
    if width > MAX_COLUMNS:
        raise _refuse(
            f"The file has {width} columns; at most {MAX_COLUMNS} are supported.",
            "Remove unneeded columns and import the file again.",
        )
    if header_row:
        headers = [h.strip() for h in first] + [""] * (width - len(first))
        body = numbered[1:]
    else:
        headers = [f"Column {i + 1}" for i in range(width)]
        body = numbered
    headers = [h or f"Column {i + 1}" for i, h in enumerate(headers)]
    table = RawTable(
        headers=headers,
        rows=[[c for c in r] + [None] * (width - len(r)) for _, r in body],
        row_numbers=[n for n, _ in body],
        description=description,
        notes=notes,
    )
    if not consistent:
        table.reliable = False
        table.problem = (
            "Rows have different numbers of columns, so this file cannot be read reliably. "
            "Open it in a spreadsheet program, check the columns, and save it as CSV or .xlsx."
        )
    del first_number
    return table


def _key_value_table(text: str, notes: list[str]) -> RawTable | None:
    """Records written as ``Key: value`` lines separated by blank lines."""
    blocks: list[list[tuple[int, str, str]]] = []
    current: list[tuple[int, str, str]] = []
    total_lines = 0
    matched = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        total_lines += 1
        m = _KEY_VALUE.match(line)
        if m is None or m[1].strip().lower() in {"http", "https"}:
            return None
        matched += 1
        current.append((number, m[1].strip(), m[2].strip()))
    if current:
        blocks.append(current)
    if len(blocks) < 1 or matched != total_lines:
        return None
    headers: list[str] = []
    for block in blocks:
        for _, key, _ in block:
            if key not in headers:
                headers.append(key)
    if len(headers) > MAX_COLUMNS:
        return None
    rows: list[list[CellValue]] = []
    numbers: list[int] = []
    for block in blocks:
        values: dict[str, str] = {}
        for _, key, value in block:
            values[key] = f"{values[key]}; {value}" if key in values else value
        rows.append([values.get(h) for h in headers])
        numbers.append(block[0][0])
    notes.append("Read as records of “Field: value” lines separated by blank lines.")
    return RawTable(headers, rows, numbers, "Text file with “Field: value” records", notes)


def read_delimited(data: bytes, kind: FileKind) -> RawTable:
    text, encoding, notes = decode_text(data)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise _refuse("The file has no data.", "Choose a file that contains your prospect list.")
    if kind is FileKind.CSV:
        delimiter = _sniff_delimiter(text, ",;\t|") or ","
        rows = _split(text, delimiter)
        return _table_from_rows(
            rows, f"CSV ({_DELIMITER_NAMES[delimiter]}-separated, {encoding})", notes
        )
    text_delimiter = _sniff_delimiter(text, "\t,;|")
    if text_delimiter is not None:
        rows = _split(text, text_delimiter)
        return _table_from_rows(
            rows, f"Text ({_DELIMITER_NAMES[text_delimiter]}-separated, {encoding})", notes
        )
    key_values = _key_value_table(text, notes)
    if key_values is not None:
        return key_values
    lines = text.split("\n")
    filled = [line for line in lines if line.strip()]
    if filled and all(len(line) <= 300 for line in filled):
        rows = [[line.strip()] for line in lines]
        # A plain list has no header unless its first line is a known column name.
        has_header = suggest_mapping([filled[0].strip()])[0].field is not None
        table = _table_from_rows(
            rows, f"Text (one value per line, {encoding})", notes, header_row=has_header
        )
        table.notes.append("Each line was read as one value. Choose what the column holds.")
        return table
    return RawTable(
        headers=[],
        rows=[],
        row_numbers=[],
        description=f"Text ({encoding})",
        notes=notes,
        reliable=False,
        problem=(
            "tg_sales cannot reliably read this text file: it has no consistent separator "
            "(tab, comma, semicolon) and is not in “Field: value” form. Save the list as CSV "
            "or Excel and import that file."
        ),
    )


# -- Excel ------------------------------------------------------------------------


def _xlsx_cell(value: Any) -> CellValue:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, datetime | date):
        return value
    if isinstance(value, time):
        return value.isoformat()
    return str(value)


def read_xlsx(path: Path, sheet: str | None, token: CancelToken | None = None) -> RawTable:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except Exception as exc:  # openpyxl raises many types for malformed packages
        raise _refuse(
            "This Excel file could not be opened.",
            "Open it in Excel and save a new copy as .xlsx, or export it as CSV.",
            repr(exc),
        ) from exc
    try:
        names = [ws.title for ws in workbook.worksheets]
        name = sheet if sheet in names else names[0]
        worksheet = workbook[name]
        rows: list[tuple[int, list[CellValue]]] = []
        formula_cells = 0
        for number, values in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if token is not None and number % 500 == 0:
                token.raise_if_cancelled()
            cells = [_xlsx_cell(v) for v in values[: MAX_COLUMNS + 1]]
            if len(values) > MAX_COLUMNS and any(v is not None for v in values[MAX_COLUMNS:]):
                raise _refuse(
                    f"The sheet has more than {MAX_COLUMNS} columns.",
                    "Remove unneeded columns and import the file again.",
                )
            formula_cells += sum(1 for c in cells if isinstance(c, str) and c.startswith("="))
            if any(c is not None and str(c).strip() for c in cells):
                rows.append((number, cells))
                if len(rows) > MAX_ROWS + 1:
                    raise _refuse(
                        f"The sheet has more than {MAX_ROWS:,} rows.",
                        "Split the list into smaller files and import them one at a time.",
                    )
    finally:
        workbook.close()
    if not rows:
        raise _refuse(
            f"The sheet “{name}” has no data.",
            "Choose another sheet, or a file that contains your prospect list.",
        )
    width = max(len(r) for _, r in rows)
    while width > 0 and all(len(r) < width or r[width - 1] is None for _, r in rows):
        width -= 1
    rows = [(n, (r + [None] * width)[:width]) for n, r in rows]
    notes = []
    if formula_cells:
        notes.append(
            f"{formula_cells} cell(s) contain spreadsheet formulas. They were read as text "
            "and never calculated."
        )
    header_number, header_cells = rows[0]
    header_texts = ["" if c is None else str(c).strip() for c in header_cells]
    if _looks_like_data(header_texts):
        headers = [f"Column {i + 1}" for i in range(width)]
        body = rows
        notes.append("The first row looks like data, so columns were named Column 1, Column 2 ….")
    else:
        headers = [h or f"Column {i + 1}" for i, h in enumerate(header_texts)]
        body = rows[1:]
    del header_number
    return RawTable(
        headers=headers,
        rows=[r for _, r in body],
        row_numbers=[n for n, _ in body],
        description=f"Excel workbook, sheet “{name}”",
        notes=notes,
        sheet_name=name,
    )


def read_table(
    source: SourceFile,
    sheet: str | None = None,
    token: CancelToken | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> RawTable:
    """Read the rows of ``source`` (one sheet for Excel files)."""
    if progress is not None:
        progress(5, "Reading the file…")
    try:
        if source.kind is FileKind.XLSX:
            table = read_xlsx(source.path, sheet, token)
        else:
            data = source.path.read_bytes()
            if hashlib.sha256(data).hexdigest() != source.sha256:
                raise _refuse(
                    "The file changed after it was selected.",
                    "Choose the file again to import its current contents.",
                )
            table = read_delimited(data, source.kind)
    except OSError as exc:
        raise _refuse(
            "The file could not be read.",
            "Check that the file is not open in another program, then try again.",
            repr(exc),
        ) from exc
    if len(table.rows) > MAX_ROWS:
        raise _refuse(
            f"The file has {len(table.rows):,} rows; at most {MAX_ROWS:,} can be imported at once.",
            "Split the list into smaller files and import them one at a time.",
        )
    if len(table.rows) > WARN_ROWS:
        table.notes.append(
            f"This file has {len(table.rows):,} rows. Checking and importing them may take a "
            "minute."
        )
    if table.reliable and not table.rows:
        table.reliable = False
        table.problem = "The file has a header row but no data rows."
    if progress is not None:
        progress(100, "File read.")
    return table
