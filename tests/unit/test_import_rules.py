from __future__ import annotations

from datetime import date

import pytest

from tg_sales.domain.enums import ContactStatus, OrganizationType, ReleasePrecision
from tg_sales.domain.importing import (
    ColumnMapping,
    ImportField,
    IssueSeverity,
    RecordOptions,
    build_record,
    build_records,
    mapping_problems,
    suggest_mapping,
)
from tg_sales.domain.normalization import DateOrder
from tg_sales.services.imports import group_records

F = ImportField


def fields(headers: list[str], samples: list[list[object]] | None = None) -> list[F | None]:
    return [m.field for m in suggest_mapping(headers, samples or [])]  # type: ignore[arg-type]


def mapping(*targets: F | None) -> list[ColumnMapping]:
    return [ColumnMapping(i, str(t or f"col{i}"), t, 1.0) for i, t in enumerate(targets)]


# --- column mapping ------------------------------------------------------------------


def test_synonyms_are_recognized() -> None:
    assert fields(
        [
            "Company",
            "URL",
            "E-mail",
            "Position",
            "Reached out?",
            "Game Name",
            "Launch Date",
            "Linked In",
            "Socials",
        ]
    ) == [
        F.ORGANIZATION_NAME,
        F.WEBSITE,
        F.EMAIL,
        F.ROLE_TITLE,
        F.CONTACTED,
        F.GAME_TITLE,
        F.RELEASE_DATE,
        F.LINKEDIN,
        F.SOCIAL,
    ]
    assert fields(["Developer", "Website"])[0] is F.ORGANIZATION_NAME


def test_ambiguous_headers_are_not_guessed() -> None:
    proposals = suggest_mapping(["Name", "Title", "Website"])
    assert [p.field for p in proposals] == [None, None, F.WEBSITE]
    assert "Ambiguous" in proposals[0].note
    assert "Ambiguous" in proposals[1].note


def test_ambiguous_headers_resolved_from_context() -> None:
    assert fields(["Company", "Name", "Game", "Title"]) == [
        F.ORGANIZATION_NAME,
        F.CONTACT_NAME,
        F.GAME_TITLE,
        F.ROLE_TITLE,
    ]


def test_contact_column_resolved_from_values() -> None:
    emails = [["a@x.example"], ["b@y.example"]]
    names = [["Ana"], ["Bo"]]
    assert fields(["Contact"], emails) == [F.EMAIL]  # type: ignore[arg-type]
    assert fields(["Contact"], names) == [F.CONTACT_NAME]  # type: ignore[arg-type]


def test_only_best_column_kept_for_single_fields() -> None:
    proposals = suggest_mapping(["Studio", "Company"])
    assert [p.field for p in proposals] == [F.ORGANIZATION_NAME, None]
    assert "already mapped" in proposals[1].note
    assert [p.field for p in suggest_mapping(["Notes", "Comments"])] == [
        F.ORGANIZATION_NOTES,
        F.ORGANIZATION_NOTES,
    ]


def test_unrecognized_and_blank_headers() -> None:
    proposals = suggest_mapping(["Favourite colour", ""])
    assert [p.field for p in proposals] == [None, None]
    assert proposals[0].note == "Not recognized."


def test_mapping_problems() -> None:
    assert mapping_problems(mapping(F.WEBSITE)) == [
        "Choose the column that holds the studio or company name."
    ]
    assert "Only one column" in mapping_problems(mapping(F.ORGANIZATION_NAME, F.EMAIL, F.EMAIL))[0]
    assert mapping_problems(mapping(F.ORGANIZATION_NAME, F.TAGS, F.TAGS)) == []


# --- row interpretation ----------------------------------------------------------------

BASIC = mapping(F.ORGANIZATION_NAME, F.WEBSITE, F.CONTACT_NAME, F.EMAIL, F.CONTACTED)


def test_contacted_comes_only_from_an_explicit_column() -> None:
    with_flag = build_record(2, ["Studio", "s.example", "Ana", "ana@s.example", "✓"], BASIC)
    assert with_flag.record is not None
    assert with_flag.record.contacts[0].status is ContactStatus.ATTEMPTED
    no_column = build_record(2, ["Studio", "ana@s.example"], mapping(F.ORGANIZATION_NAME, F.EMAIL))
    assert no_column.record is not None
    assert no_column.record.contacts[0].status is ContactStatus.UNKNOWN
    blank = build_record(2, ["Studio", "s.example", "Ana", "ana@s.example", ""], BASIC)
    assert blank.record is not None
    assert blank.record.contacts[0].status is ContactStatus.UNKNOWN
    declined = build_record(2, ["Studio", "", "Ana", "", "no"], BASIC)
    assert declined.record is not None
    assert declined.record.contacts[0].status is ContactStatus.NOT_CONTACTED


def test_blank_rows_are_flagged_not_errors() -> None:
    result = build_record(5, ["", None, "  "], BASIC)
    assert result.blank
    assert result.record is None
    assert not result.issues


def test_missing_name_is_an_error() -> None:
    result = build_record(7, ["", "s.example", "Ana", "", ""], BASIC)
    assert result.record is None
    assert result.has_errors
    assert result.issues[-1].row_number == 7


def test_explicit_multiple_contacts() -> None:
    result = build_record(3, ["Studio", "", "Ana; Bo", "ana@s.example; bo@s.example", "yes"], BASIC)
    assert result.record is not None
    assert [(c.name, c.email) for c in result.record.contacts] == [
        ("Ana", "ana@s.example"),
        ("Bo", "bo@s.example"),
    ]
    assert not result.issues


def test_multiple_emails_without_names_are_flagged() -> None:
    result = build_record(3, ["Studio", "", "Ana", "ana@s.example, ana2@s.example", ""], BASIC)
    assert result.record is not None
    (contact,) = result.record.contacts
    assert contact.email == "ana@s.example"
    assert contact.notes is not None and "ana2@s.example" in contact.notes
    assert any("2 email addresses" in i.message for i in result.issues)


def test_formulas_are_kept_as_text_with_warning() -> None:
    result = build_record(4, ['=HYPERLINK("x")', "", "", "", ""], BASIC)
    assert result.record is not None
    assert result.record.organization_name == '=HYPERLINK("x")'
    assert any("formula" in i.message for i in result.issues)


def test_invalid_values_are_ignored_with_warnings() -> None:
    result = build_record(
        4, ["Studio", "javascript:alert(1)", "Ana", "not-an-email", "perhaps"], BASIC
    )
    assert result.record is not None
    assert result.record.website is None
    assert result.record.contacts[0].email is None
    messages = [i.message for i in result.issues]
    assert any("web address" in m for m in messages)
    assert sum("email" in m for m in messages) == 1
    assert any("Contacted value not recognized" in m for m in messages)
    assert all(i.severity is IssueSeverity.WARNING for i in result.issues)


def test_dates_and_games() -> None:
    cols = mapping(F.ORGANIZATION_NAME, F.GAME_TITLE, F.RELEASE_DATE, F.STORE_URL, F.PLATFORM)
    ambiguous = build_record(2, ["S", "Game", "03/04/2027", "", ""], cols)
    assert ambiguous.record is not None and ambiguous.record.game is not None
    assert ambiguous.record.game.release_date is None
    assert any("day/month" in i.message for i in ambiguous.issues)
    day_first = build_record(
        2, ["S", "Game", "03/04/2027", "", ""], cols, RecordOptions(DateOrder.DAY_FIRST)
    )
    assert day_first.record is not None and day_first.record.game is not None
    assert day_first.record.game.release_date == date(2027, 4, 3)
    malformed = build_record(2, ["S", "Game", "31/02/2027", "", ""], cols)
    assert any("not recognized" in i.message for i in malformed.issues)
    quarter = build_record(2, ["S", "Game", "Q2 2027", "store.example/app/1", "PC"], cols)
    assert quarter.record is not None and quarter.record.game is not None
    assert quarter.record.game.release_precision is ReleasePrecision.QUARTER
    assert quarter.record.game.store_url == "https://store.example/app/1"
    orphan = build_record(2, ["S", "", "2027", "", "PC"], cols)
    assert orphan.record is not None and orphan.record.game is None
    assert any("game title is empty" in i.message for i in orphan.issues)


def test_non_english_names_and_social_links() -> None:
    cols = mapping(F.ORGANIZATION_NAME, F.CONTACT_NAME, F.LINKEDIN, F.SOCIAL, F.ORGANIZATION_TYPE)
    result = build_record(
        2,
        [
            "株式会社サクラ",
            "山田 太郎",
            "linkedin.com/in/taro-example",
            "https://x.com/sakura_example; https://bsky.app/profile/sakura",
            "Publisher",
        ],
        cols,
    )
    assert result.record is not None
    assert result.record.organization_name == "株式会社サクラ"
    assert result.record.company_type is OrganizationType.PUBLISHER
    assert dict(result.record.contacts[0].social_urls) == {
        "linkedin": "https://linkedin.com/in/taro-example",
        "twitter": "https://x.com/sakura_example",
        "bluesky": "https://bsky.app/profile/sakura",
    }


def test_fingerprint_ignores_cosmetic_differences() -> None:
    a = build_record(
        2, ["Pixel Forge", "pixelforge.example", "Ana", "ANA@pixelforge.example", ""], BASIC
    )
    b = build_record(
        9,
        [" pixel forge ", "https://pixelforge.example/", "Ana", "ana@pixelforge.example", None],
        BASIC,
    )
    c = build_record(
        3, ["Pixel Forge", "pixelforge.example", "Bo", "bo@pixelforge.example", ""], BASIC
    )
    assert a.record is not None and b.record is not None and c.record is not None
    assert a.record.fingerprint == b.record.fingerprint
    assert a.record.fingerprint != c.record.fingerprint


def test_row_numbers_follow_the_source() -> None:
    results = build_records([["A"], ["B"]], mapping(F.ORGANIZATION_NAME), row_numbers=[4, 9])
    assert [r.row_number for r in results] == [4, 9]
    assert [r.row_number for r in build_records([["A"]], mapping(F.ORGANIZATION_NAME))] == [2]


@pytest.mark.parametrize(
    ("rows", "groups"),
    [
        # same domain → one group even with different spelling
        ([["Pixel Forge", "pixelforge.example"], ["Pixel Forge Studios", "pixelforge.example"]], 1),
        # same name, no website on one row → joins the website group
        ([["Moon Owl", "moonowl.example"], ["Moon Owl", ""]], 1),
        # same name, different websites → possibly different studios
        ([["Moon Owl", "moonowl.example"], ["Moon Owl", "moon-owl.example"]], 2),
        # shared hosts do not group unrelated studios
        ([["Alpha", "alpha.itch.io"], ["Beta", "beta.itch.io"]], 2),
    ],
)
def test_group_records(rows: list[list[str]], groups: int) -> None:
    records = [
        r.record
        for r in build_records(rows, mapping(F.ORGANIZATION_NAME, F.WEBSITE))
        if r.record is not None
    ]
    assert len(group_records(records)) == groups
