from __future__ import annotations

from datetime import date, datetime

import pytest

from tg_sales.domain.enums import ReleasePrecision
from tg_sales.domain.normalization import (
    DateOrder,
    Flag,
    core_name,
    domain_from_url,
    identifying_domain,
    is_generic_domain,
    looks_like_formula,
    normalize_email,
    normalize_url,
    parse_date,
    parse_flag,
    social_network,
    split_emails,
    split_list,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("studio.example", "https://studio.example"),
        ("  HTTPS://WWW.Studio.Example/Press/  ", "https://www.studio.example/Press/"),
        ("http://studio.example/", "http://studio.example"),
        ("studio.example:8080/x", "https://studio.example:8080/x"),
        ("https://studio.example/a?b=1#frag", "https://studio.example/a?b=1"),
        ("javascript:alert(1)", None),
        ("file:///C:/secret.txt", None),
        ("data:text/html;base64,AAAA", None),
        ("ftp://studio.example", None),
        ("https://user:pass@studio.example", None),
        ("https://localhost", None),
        ("not a url", None),
        ("", None),
        (None, None),
        ("https://exa mple.example", None),
        ("https://スタジオ.example", "https://スタジオ.example"),
    ],
)
def test_normalize_url(raw: str | None, expected: str | None) -> None:
    assert normalize_url(raw) == expected


def test_domains_and_generic_hosts() -> None:
    assert domain_from_url("https://www.pixelforge.example/about") == "pixelforge.example"
    assert is_generic_domain("gmail.com")
    assert is_generic_domain("mystudio.itch.io")
    assert is_generic_domain("store.steampowered.com")
    assert is_generic_domain(None)
    assert not is_generic_domain("pixelforge.example")
    assert identifying_domain("linktr.ee") is None
    assert identifying_domain("pixelforge.example") == "pixelforge.example"


def test_email_helpers() -> None:
    assert normalize_email("MAILTO:Ana@Studio.Example") == "ana@studio.example"
    assert split_emails("a@x.example; b@x.example, c@x.example | d@x.example") == [
        "a@x.example",
        "b@x.example",
        "c@x.example",
        "d@x.example",
    ]
    assert split_emails(None) == []
    assert split_list("indie, vr;  mobile |pc\nconsole") == [
        "indie",
        "vr",
        "mobile",
        "pc",
        "console",
    ]


def test_core_name_ignores_company_form() -> None:
    assert core_name("Pixel Forge Studios, Inc.") == "pixel forge studios"
    assert core_name("Northwind GmbH") == "northwind"
    assert core_name("株式会社サクラ") == "株式会社サクラ"


@pytest.mark.parametrize(
    ("url", "network"),
    [
        ("https://www.linkedin.com/in/someone", "linkedin"),
        ("https://x.com/someone", "twitter"),
        ("twitter.com/someone", "twitter"),
        ("https://bsky.app/profile/x", "bluesky"),
        ("https://studio.example", None),
    ],
)
def test_social_network(url: str, network: str | None) -> None:
    assert social_network(url) == network


@pytest.mark.parametrize(
    ("value", "flag", "recognized"),
    [
        ("✓", Flag.YES, True),
        ("✔", Flag.YES, True),
        ("☑", Flag.YES, True),
        ("x", Flag.YES, True),
        ("Yes", Flag.YES, True),
        ("reached out", Flag.YES, True),
        ("Reached-Out", Flag.YES, True),
        (True, Flag.YES, True),
        (1, Flag.YES, True),
        ("no", Flag.NO, True),
        ("☐", Flag.NO, True),
        ("✗", Flag.NO, True),
        ("not contacted", Flag.NO, True),
        (False, Flag.NO, True),
        ("", Flag.UNKNOWN, True),
        (None, Flag.UNKNOWN, True),
        ("?", Flag.UNKNOWN, True),
        ("maybe", Flag.UNKNOWN, False),
        ("2026-01-01", Flag.UNKNOWN, False),
    ],
)
def test_parse_flag(value: object, flag: Flag, recognized: bool) -> None:
    assert parse_flag(value) == (flag, recognized)


@pytest.mark.parametrize(
    ("value", "expected", "precision"),
    [
        ("2027-03-14", date(2027, 3, 14), ReleasePrecision.DAY),
        ("2027/3/4", date(2027, 3, 4), ReleasePrecision.DAY),
        ("14.03.2027", date(2027, 3, 14), ReleasePrecision.DAY),
        ("25/12/2027", date(2027, 12, 25), ReleasePrecision.DAY),
        ("12/25/2027", date(2027, 12, 25), ReleasePrecision.DAY),
        ("04/04/2027", date(2027, 4, 4), ReleasePrecision.DAY),
        ("March 14, 2027", date(2027, 3, 14), ReleasePrecision.DAY),
        ("14 Mar 2027", date(2027, 3, 14), ReleasePrecision.DAY),
        ("1st of March 2027", date(2027, 3, 1), ReleasePrecision.DAY),
        ("Sept 2027", date(2027, 9, 1), ReleasePrecision.MONTH),
        ("2027-09", date(2027, 9, 1), ReleasePrecision.MONTH),
        ("Q3 2027", date(2027, 7, 1), ReleasePrecision.QUARTER),
        ("2027 Q1", date(2027, 1, 1), ReleasePrecision.QUARTER),
        ("2027", date(2027, 1, 1), ReleasePrecision.YEAR),
        (datetime(2027, 5, 20, 9, 30), date(2027, 5, 20), ReleasePrecision.DAY),  # noqa: DTZ001
        (date(2027, 5, 20), date(2027, 5, 20), ReleasePrecision.DAY),
        ("TBA", None, ReleasePrecision.UNKNOWN),
        ("Coming soon", None, ReleasePrecision.UNKNOWN),
        ("", None, ReleasePrecision.UNKNOWN),
        (None, None, ReleasePrecision.UNKNOWN),
    ],
)
def test_parse_date(value: object, expected: date | None, precision: ReleasePrecision) -> None:
    parsed = parse_date(value)
    assert (parsed.value, parsed.precision) == (expected, precision)
    assert parsed.recognized
    assert not parsed.ambiguous


@pytest.mark.parametrize("value", ["31/02/2027", "2027-13-01", "soonish", "March", "1850", "99"])
def test_parse_date_unreadable(value: str) -> None:
    parsed = parse_date(value)
    assert parsed.value is None
    assert not parsed.recognized


def test_ambiguous_dates_are_not_guessed() -> None:
    assert parse_date("03/04/2027").ambiguous
    assert parse_date("03/04/2027").value is None
    assert parse_date("03/04/2027", DateOrder.MONTH_FIRST).value == date(2027, 3, 4)
    assert parse_date("03/04/2027", DateOrder.DAY_FIRST).value == date(2027, 4, 3)


@pytest.mark.parametrize(
    ("text", "formula"),
    [
        ("=SUM(A1:A2)", True),
        ("+1+2", True),
        ("-2+3", True),
        ("@cmd", True),
        ("\tx", True),
        ("-5", False),
        ("+44", False),
        ("Normal text", False),
        ("", False),
    ],
)
def test_looks_like_formula(text: str, formula: bool) -> None:
    assert looks_like_formula(text) is formula
