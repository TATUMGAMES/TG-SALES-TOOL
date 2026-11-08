from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from tg_sales.cancellation import CancelToken, OperationCancelledError
from tg_sales.services import import_files
from tg_sales.services.import_files import (
    FileKind,
    ImportFileError,
    inspect_file,
    read_table,
)

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def write(path: Path, data: bytes | str) -> Path:
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def table_of(path: Path, sheet: str | None = None) -> import_files.RawTable:
    return read_table(inspect_file(path), sheet)


# --- inspection and refusal ------------------------------------------------------------


def test_inspect_collects_metadata() -> None:
    source = inspect_file(FIXTURES / "messy_prospects.csv")
    assert source.kind is FileKind.CSV
    assert source.name == "messy_prospects.csv"
    assert len(source.sha256) == 64
    assert source.size_bytes > 0
    workbook = inspect_file(FIXTURES / "sample_prospects.xlsx")
    assert workbook.sheet_names == ("Notes", "Prospects")


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("list.xls", "Old Excel"),
        ("list.xlsm", "Macro-enabled"),
        ("list.xlsb", "Binary workbooks"),
        ("list.exe", "Choose a CSV"),
        ("list.json", "Choose a CSV"),
    ],
)
def test_unsupported_types_are_refused(tmp_path: Path, name: str, message: str) -> None:
    path = write(tmp_path / name, "Studio\nA\n")
    with pytest.raises(ImportFileError) as info:
        inspect_file(path)
    assert message in info.value.suggested_action


def test_empty_and_missing_files(tmp_path: Path) -> None:
    with pytest.raises(ImportFileError, match="empty"):
        inspect_file(write(tmp_path / "empty.csv", b""))
    with pytest.raises(ImportFileError, match="not found"):
        inspect_file(tmp_path / "missing.csv")


def test_size_limit_and_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path / "big.csv", "Studio\n" + "A Studio\n" * 200)
    monkeypatch.setattr(import_files, "WARN_FILE_BYTES", 100)
    assert inspect_file(path).warnings
    monkeypatch.setattr(import_files, "MAX_FILE_BYTES", 500)
    with pytest.raises(ImportFileError, match="too large"):
        inspect_file(path)


def test_password_protected_or_legacy_workbook_refused(tmp_path: Path) -> None:
    path = write(tmp_path / "locked.xlsx", import_files.OLE_SIGNATURE + b"\x00" * 600)
    with pytest.raises(ImportFileError, match="password-protected"):
        inspect_file(path)


def test_fake_workbook_refused(tmp_path: Path) -> None:
    with pytest.raises(ImportFileError, match="not a valid Excel"):
        inspect_file(write(tmp_path / "fake.xlsx", "Studio,Website\nA,a.example\n"))
    other_zip = tmp_path / "other.xlsx"
    with zipfile.ZipFile(other_zip, "w") as package:
        package.writestr("readme.txt", "not a workbook")
    with pytest.raises(ImportFileError, match="not a valid Excel"):
        inspect_file(other_zip)


def _workbook(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    workbook.active.append(["Studio"])
    workbook.active.append(["A"])
    workbook.save(path)
    return path


def test_macro_workbook_with_xlsx_extension_refused(tmp_path: Path) -> None:
    path = _workbook(tmp_path / "macro.xlsx")
    with zipfile.ZipFile(path, "a") as package:
        package.writestr("xl/vbaProject.bin", b"\x00" * 32)
    with pytest.raises(ImportFileError, match="macros"):
        inspect_file(path)


def test_zip_bomb_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _workbook(tmp_path / "bomb.xlsx")
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("xl/media/padding.bin", b"\x00" * 2_000_000)
    monkeypatch.setattr(import_files, "MAX_XLSX_COMPRESSION_RATIO", 50)
    with pytest.raises(ImportFileError, match="unsafe size"):
        inspect_file(path)


# --- text files ------------------------------------------------------------------------


def test_messy_csv_fixture() -> None:
    table = table_of(FIXTURES / "messy_prospects.csv")
    assert table.reliable
    assert table.description.startswith("CSV (semicolon-separated, UTF-8")
    assert table.headers[:3] == ["Studio", "Website", "Contact"]
    assert table.row_numbers[0] == 2
    assert 6 not in table.row_numbers  # the blank line is skipped, numbering is kept
    assert any(row[0] == "株式会社サクラ" for row in table.rows)


@pytest.mark.parametrize(
    ("content", "delimiter_name"),
    [
        ("Studio,Website\nA,a.example\nB,b.example\n", "comma"),
        ("Studio;Website\nA;a.example\nB;b.example\n", "semicolon"),
        ("Studio\tWebsite\nA\ta.example\nB\tb.example\n", "tab"),
        ("Studio|Website\nA|a.example\nB|b.example\n", "vertical bar"),
        ('Studio,Notes\n"A, Inc.","said ""hi"""\nB,x\n', "comma"),
    ],
)
def test_csv_dialects(tmp_path: Path, content: str, delimiter_name: str) -> None:
    table = table_of(write(tmp_path / "list.csv", content))
    assert delimiter_name in table.description
    assert table.headers[0] == "Studio"
    assert len(table.rows) == 2


def test_encodings(tmp_path: Path) -> None:
    cp1252 = table_of(FIXTURES / "studios_cp1252.csv")
    assert "Windows-1252" in cp1252.description
    assert cp1252.rows[0][0] == "Café Byte"
    assert any("not UTF-8" in note for note in cp1252.notes)
    utf16 = table_of(
        write(tmp_path / "u16.csv", "Studio,Site\nÉclair,e.example\n".encode("utf-16"))
    )
    assert utf16.rows[0][0] == "Éclair"
    bom = table_of(write(tmp_path / "bom.csv", b"\xef\xbb\xbfStudio\nA\n"))
    assert bom.headers == ["Studio"]


def test_binary_content_refused(tmp_path: Path) -> None:
    with pytest.raises(ImportFileError, match="does not look like"):
        table_of(write(tmp_path / "x.csv", b"Studio\x00\x01\x02" * 10))


def test_header_only_and_inconsistent_rows(tmp_path: Path) -> None:
    header_only = table_of(write(tmp_path / "h.csv", "Studio,Website\n"))
    assert not header_only.reliable
    assert "no data rows" in (header_only.problem or "")
    ragged = table_of(
        write(tmp_path / "r.csv", "Studio,Website\nA,a.example,x,y\nB\nC,c.example,z\nD\n")
    )
    assert not ragged.reliable
    assert "cannot be read reliably" in (ragged.problem or "")


def test_first_row_looking_like_data_gets_generated_headers(tmp_path: Path) -> None:
    table = table_of(write(tmp_path / "n.csv", "A,a@a.example\nB,b@b.example\n"))
    assert table.headers == ["Column 1", "Column 2"]
    assert len(table.rows) == 2


def test_txt_formats(tmp_path: Path) -> None:
    tab = table_of(FIXTURES / "studios_tab.txt")
    assert "tab-separated" in tab.description
    key_value = table_of(FIXTURES / "studios_key_value.txt")
    assert key_value.headers == ["Studio", "Website", "Email", "Contacted"]
    assert key_value.rows[1][:2] == ["Iron Lantern", "https://ironlantern.example"]
    assert key_value.row_numbers == [1, 6]
    lines = table_of(write(tmp_path / "l.txt", "Studio A\nStudio B\n\nStudio C\n"))
    assert "one value per line" in lines.description
    assert lines.headers == ["Column 1"]
    assert [r[0] for r in lines.rows] == ["Studio A", "Studio B", "Studio C"]
    assert lines.row_numbers == [1, 2, 4]
    with_header = table_of(write(tmp_path / "h.txt", "Studio\nStudio A\nStudio B\n"))
    assert with_header.headers == ["Studio"]
    assert len(with_header.rows) == 2


def test_unparseable_txt_is_reported(tmp_path: Path) -> None:
    prose = ("This is a long paragraph of prose without any structure at all. " * 8 + "\n") * 3
    table = table_of(write(tmp_path / "p.txt", prose))
    assert not table.reliable
    assert "cannot reliably read" in (table.problem or "")


def test_row_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path / "many.csv", "Studio\n" + "".join(f"S{i}\n" for i in range(30)))
    monkeypatch.setattr(import_files, "WARN_ROWS", 10)
    assert any("30 rows" in n for n in table_of(path).notes)
    monkeypatch.setattr(import_files, "MAX_ROWS", 20)
    with pytest.raises(ImportFileError, match="at most 20"):
        table_of(path)


def test_file_changed_after_selection(tmp_path: Path) -> None:
    path = write(tmp_path / "c.csv", "Studio\nA\n")
    source = inspect_file(path)
    write(path, "Studio\nB\n")
    with pytest.raises(ImportFileError, match="changed"):
        read_table(source)


# --- Excel -----------------------------------------------------------------------------


def test_workbook_fixture_sheet_selection_and_formulas() -> None:
    source = inspect_file(FIXTURES / "sample_prospects.xlsx")
    first = read_table(source)  # defaults to the first sheet
    assert first.sheet_name == "Notes"
    table = read_table(source, "Prospects")
    assert table.sheet_name == "Prospects"
    assert table.headers[0] == "Studio"
    # Excel date cells keep their type (workbooks store dates without a time zone).
    assert table.rows[0][8] == datetime(2027, 5, 20)  # noqa: DTZ001
    assert table.rows[0][6] is True
    assert [c for r in table.rows for c in r if isinstance(c, str) and c.startswith("=")] == [
        "=1+1"
    ]
    assert any("never calculated" in n for n in table.notes)


def test_empty_sheet_refused(tmp_path: Path) -> None:
    workbook = openpyxl.Workbook()
    workbook.active.title = "Blank"
    path = tmp_path / "blank.xlsx"
    workbook.save(path)
    with pytest.raises(ImportFileError, match="has no data"):
        table_of(path)


def test_workbook_read_can_be_cancelled(tmp_path: Path) -> None:
    workbook = openpyxl.Workbook()
    for i in range(1200):
        workbook.active.append([f"Studio {i}"])
    path = tmp_path / "long.xlsx"
    workbook.save(path)
    token = CancelToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        read_table(inspect_file(path), None, token)
