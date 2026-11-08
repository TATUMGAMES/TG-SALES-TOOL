"""Regenerate the synthetic import fixtures in this folder.

Run from the repository root:  python tests/fixtures/imports/make_fixtures.py

All names, people and domains are invented (reserved ``.example`` domains).
The files are committed so tests and the user guide can use them directly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Semicolon-separated, UTF-8 with BOM, CRLF line endings; messy on purpose:
# duplicate rows, blank rows, non-English names, a formula typed as text, a
# malformed and an ambiguous date, checkmark flags, two emails in one cell,
# a row without a studio name, and the same studio on two rows.
MESSY_CSV = [
    "Studio;Website;Contact;Email;Job Title;Contacted;Game;Release Date;LinkedIn;Tags",
    "Pixel Forge Studios;https://www.pixelforge.example;Ana Ruiz;ana@pixelforge.example;"
    "Producer;✓;Sky Rails;2027-03-14;https://www.linkedin.com/in/ana-ruiz-example;indie, vr",
    "Pixel Forge Studios;pixelforge.example;Bo Lind;bo@pixelforge.example;Art Director;no;"
    "Sky Rails;2027-03-14;;indie",
    "Moon Owl Games;moonowl.example;Chloé Dubois;chloe@moonowl.example;CEO;yes;Owl Quest;Q3 2027;;",
    "Moon Owl Games;moonowl.example;Chloé Dubois;chloe@moonowl.example;CEO;yes;Owl Quest;Q3 2027;;",
    ";;;;;;;;;",
    "株式会社サクラ;sakura-games.example;山田 太郎;taro@sakura-games.example;Producer;;"
    "Hanami;March 2027;;mobile",
    "Éclair Jeux;eclair.example;Luc; luc@eclair.example ;;maybe;Crème Run;31/02/2027;;",
    'Northwind Interactive;northwind.example;Dee Kay;=HYPERLINK("http://evil.example");'
    "Lead;☐;Fjord;03/04/2027;;",
    ";orphan.example;No Studio;nobody@orphan.example;;;;;;",
    'Twin Peaks Games;twinpeaks.example;"Eve Moss; Finn Hale";"eve@twinpeaks.example; '
    'finn@twinpeaks.example";;;;;;',
    "Solo Dev Co;solodev.example;Gil Park;gil@solodev.example, gil.park@solodev.example;;;;;;",
    "",
]

TAB_TXT = [
    "Company\tWebsite\tEmail\tReached out",
    "Harbor Lights Studio\tharborlights.example\tmia@harborlights.example\tx",
    "Crimson Tide Games\tcrimsontide.example\tnoah@crimsontide.example\t",
    "",
]

KEY_VALUE_TXT = [
    "Studio: Glass Fern Games",
    "Website: glassfern.example",
    "Email: ivy@glassfern.example",
    "Contacted: no",
    "",
    "Studio: Iron Lantern",
    "Website: https://ironlantern.example",
    "Contacted: yes",
    "",
]

# Windows-1252 encoded (not UTF-8): accented names must survive the fallback.
CP1252_CSV = [
    "Company,Website,Contact Name",
    "Café Byte,cafebyte.example,José Núñez",
    "Señor Pixel,senorpixel.example,Zoë Brontë",
    "",
]


def write_text_files() -> None:
    (HERE / "messy_prospects.csv").write_bytes(
        b"\xef\xbb\xbf" + "\r\n".join(MESSY_CSV).encode("utf-8")
    )
    (HERE / "studios_tab.txt").write_bytes("\n".join(TAB_TXT).encode("utf-8"))
    (HERE / "studios_key_value.txt").write_bytes("\n".join(KEY_VALUE_TXT).encode("utf-8"))
    (HERE / "studios_cp1252.csv").write_bytes("\r\n".join(CP1252_CSV).encode("cp1252"))


def write_workbook() -> None:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Notes"
    sheet.append(["This sheet only has notes for the sales team."])
    prospects = workbook.create_sheet("Prospects")
    prospects.append(
        [
            "Studio",
            "Website",
            "Contact Name",
            "Email",
            "Role",
            "Twitter",
            "Contacted",
            "Game",
            "Release Date",
            "Platform",
        ]
    )
    rows = [
        [
            "Aurora Bay Games",
            "aurorabay.example",
            "Kim Lee",
            "kim@aurorabay.example",
            "Studio Head",
            "https://x.com/aurorabay_example",
            True,
            "Northern Drift",
            date(2027, 5, 20),
            "PC",
        ],
        [
            "Aurora Bay Games",
            "aurorabay.example",
            "Raj Patel",
            "raj@aurorabay.example",
            "Business Development",
            None,
            "✔",
            "Northern Drift",
            date(2027, 5, 20),
            "PC",
        ],
        [
            "Quill & Quest",
            "https://quillquest.example",
            "Sam Ortiz",
            "sam@quillquest.example",
            "Founder",
            None,
            "no",
            "Inkbound",
            "Q4 2027",
            "Switch",
        ],
        [
            "Velvet Moth Studio",
            "velvetmoth.example",
            None,
            None,
            None,
            None,
            None,
            "Moth Light",
            "TBA",
            "PC, PS5",
        ],
        [
            "Formula Row Ltd",
            "formula.example",
            "Ty Gray",
            "ty@formula.example",
            None,
            None,
            None,
            None,
            None,
            None,
        ],
    ]
    for row in rows:
        prospects.append(row)
    prospects["J7"] = "=1+1"  # a formula cell: must be read as text, never calculated
    workbook.save(HERE / "sample_prospects.xlsx")


if __name__ == "__main__":
    write_text_files()
    write_workbook()
