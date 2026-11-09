# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Review date, qualification source URL and custom fields in the import rules."""

from __future__ import annotations

from datetime import date

import pytest

from tg_sales.domain.custom_fields import (
    CustomFieldInfo,
    FieldType,
    InvalidValueError,
    RecordType,
    clean_values,
    custom_field_id,
    key_from_label,
    merged,
    parse_value,
)
from tg_sales.domain.importing import (
    ColumnMapping,
    ImportField,
    IssueSeverity,
    RecordOptions,
    build_record,
    mapping_problems,
    suggest_mapping,
)
from tg_sales.domain.normalization import DateOrder, exact_url

F = ImportField


def custom(
    label: str, field_type: FieldType, record_type: RecordType = RecordType.PROSPECT
) -> CustomFieldInfo:
    key = key_from_label(label)
    return CustomFieldInfo(
        custom_field_id(record_type, key), record_type, key, label, field_type, None, 10, False
    )


def targets(headers: list[str], fields: list[CustomFieldInfo] | None = None) -> list[str | None]:
    return [m.target for m in suggest_mapping(headers, (), fields or [])]


# -- suggestions ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Reviewed On", F.REVIEW_DATE),
        ("Review Date", F.REVIEW_DATE),
        ("Last Reviewed", F.REVIEW_DATE),
        ("Date Reviewed", F.REVIEW_DATE),
        ("Reviewed Date", F.REVIEW_DATE),
        ("Qualification Source URL", F.QUALIFICATION_SOURCE_URL),
        ("Source URL", F.QUALIFICATION_SOURCE_URL),
        ("Research URL", F.QUALIFICATION_SOURCE_URL),
        ("Reference URL", F.QUALIFICATION_SOURCE_URL),
        ("Qualification Link", F.QUALIFICATION_SOURCE_URL),
        ("Company", F.ORGANIZATION_NAME),
        ("Website", F.WEBSITE),
        ("Email Address", F.EMAIL),
        ("Notes", F.ORGANIZATION_NOTES),
    ],
)
def test_suggestions_for_common_headers(header: str, expected: ImportField) -> None:
    assert targets([header]) == [expected.value]


def test_review_date_is_not_confused_with_other_dates() -> None:
    suggested = targets(["Created Date", "Updated", "Last Contacted", "Next Follow-Up Date"])
    assert F.REVIEW_DATE.value not in suggested


def test_plain_source_is_not_mapped_to_the_url_field() -> None:
    # "Source" is usually a lead-source category (Referral, LinkedIn), not a URL.
    assert targets(["Source"]) == [None]


def test_custom_field_label_is_suggested_and_wins() -> None:
    tier = custom("Account Tier", FieldType.TEXT)
    assert targets(["Company", "account tier", "ACCOUNT_TIER"], [tier]) == [
        F.ORGANIZATION_NAME.value,
        tier.target,
        None,  # second column for the same custom field is left for the user
    ]


def test_archived_custom_fields_are_not_suggested() -> None:
    tier = custom("Account Tier", FieldType.TEXT)
    archived = CustomFieldInfo(**{**tier.__dict__, "archived": True})
    assert targets(["Account Tier"], [archived]) == [None]


def test_duplicate_mapping_is_reported() -> None:
    tier = custom("Account Tier", FieldType.TEXT)
    mappings = [
        ColumnMapping(0, "Name", F.ORGANIZATION_NAME),
        ColumnMapping(1, "Reviewed", F.REVIEW_DATE),
        ColumnMapping(2, "Review date", F.REVIEW_DATE),
        ColumnMapping(3, "Tier", None, custom=tier),
        ColumnMapping(4, "Tier 2", None, custom=tier),
    ]
    assert mapping_problems(mappings) == [
        "Only one column can be mapped to Account Tier.",
        "Only one column can be mapped to Review date.",
    ]


# -- values -----------------------------------------------------------------------


def row(cells: list[object], mappings: list[ColumnMapping], order: DateOrder = DateOrder.AUTO):  # type: ignore[no-untyped-def]
    return build_record(2, cells, mappings, RecordOptions(date_order=order))


BASE = [ColumnMapping(0, "Company", F.ORGANIZATION_NAME)]


@pytest.mark.parametrize(
    ("value", "order", "expected"),
    [
        ("2026-03-14", DateOrder.AUTO, date(2026, 3, 14)),
        ("14/03/2026", DateOrder.AUTO, date(2026, 3, 14)),
        ("03/14/2026", DateOrder.AUTO, date(2026, 3, 14)),
        ("04/03/2026", DateOrder.DAY_FIRST, date(2026, 3, 4)),
        ("04/03/2026", DateOrder.MONTH_FIRST, date(2026, 4, 3)),
        ("March 14, 2026", DateOrder.AUTO, date(2026, 3, 14)),
        (date(2026, 3, 14), DateOrder.AUTO, date(2026, 3, 14)),
    ],
)
def test_review_date_formats(value: object, order: DateOrder, expected: date) -> None:
    result = row(["Studio", value], [*BASE, ColumnMapping(1, "Reviewed On", F.REVIEW_DATE)], order)
    assert result.record is not None
    assert result.record.reviewed_on == expected
    assert result.issues == []


@pytest.mark.parametrize("value", ["04/03/2026", "someday", "2026", "Q2 2026", "2026-02-30"])
def test_invalid_review_dates_are_reported_not_guessed(value: str) -> None:
    result = row(["Studio", value], [*BASE, ColumnMapping(1, "Reviewed On", F.REVIEW_DATE)])
    assert result.record is not None  # the row is still imported
    assert result.record.reviewed_on is None
    assert [i.severity for i in result.issues] == [IssueSeverity.WARNING]
    assert result.issues[0].column == "Reviewed On"


def test_qualification_url_is_kept_exactly() -> None:
    url = "https://Example.com/Search/Results?q=indie+studio&page=2&utm_source=x#row-7"
    mappings = [*BASE, ColumnMapping(1, "Source URL", F.QUALIFICATION_SOURCE_URL)]
    result = row(["Studio", url], mappings)
    assert result.record is not None
    assert result.record.qualification_source_url == url
    assert result.issues == []


def test_qualification_url_without_scheme_gets_https() -> None:
    mappings = [*BASE, ColumnMapping(1, "Source URL", F.QUALIFICATION_SOURCE_URL)]
    result = row(["Studio", "example.com/list?a=1"], mappings)
    assert result.record is not None
    assert result.record.qualification_source_url == "https://example.com/list?a=1"


@pytest.mark.parametrize(
    "value", ["javascript:alert(1)", "file:///C:/x", "https://user:pw@example.com", "not a url"]
)
def test_unsafe_or_invalid_urls_are_refused(value: str) -> None:
    mappings = [*BASE, ColumnMapping(1, "Source URL", F.QUALIFICATION_SOURCE_URL)]
    result = row(["Studio", value], mappings)
    assert result.record is not None
    assert result.record.qualification_source_url is None
    assert len(result.issues) == 1
    assert exact_url(value) is None


def test_custom_values_are_typed_and_invalid_ones_reported() -> None:
    tier = custom("Account Tier", FieldType.TEXT)
    revenue = custom("Annual Revenue Estimate", FieldType.NUMBER)
    partner = custom("Partner", FieldType.BOOLEAN)
    since = custom("Customer Since", FieldType.DATE)
    link = custom("Research Page", FieldType.URL)
    role = custom("Buying Role", FieldType.TEXT, RecordType.CONTACT)
    mappings = [
        *BASE,
        ColumnMapping(1, "Tier", None, custom=tier),
        ColumnMapping(2, "Revenue", None, custom=revenue),
        ColumnMapping(3, "Partner", None, custom=partner),
        ColumnMapping(4, "Since", None, custom=since),
        ColumnMapping(5, "Page", None, custom=link),
        ColumnMapping(6, "Contact", F.CONTACT_NAME),
        ColumnMapping(7, "Buying role", None, custom=role),
    ]
    good = row(
        ["Studio", "Tier 1", "$1,250,000", "yes", "2025-01-31", "x.example/?a=1", "Ana", "CFO"],
        mappings,
    )
    assert good.issues == []
    assert good.record is not None
    assert good.record.custom_values == {
        "account_tier": "Tier 1",
        "annual_revenue_estimate": 1_250_000,
        "partner": True,
        "customer_since": "2025-01-31",
        "research_page": "https://x.example/?a=1",
    }
    assert good.record.contacts[0].custom_values == {"buying_role": "CFO"}

    bad = row(["Studio", "", "lots", "maybe", "soon", "ftp://x", "Ana", ""], mappings)
    assert bad.record is not None
    assert bad.record.custom_values == {}
    assert sorted(i.column for i in bad.issues) == ["Page", "Partner", "Revenue", "Since"]
    assert all(i.severity is IssueSeverity.WARNING for i in bad.issues)


def test_new_fields_do_not_change_old_fingerprints() -> None:
    old = row(["Studio", ""], [*BASE, ColumnMapping(1, "Reviewed On", F.REVIEW_DATE)])
    plain = row(["Studio"], BASE)
    with_value = row(
        ["Studio", "2026-01-02"], [*BASE, ColumnMapping(1, "Reviewed On", F.REVIEW_DATE)]
    )
    assert old.record is not None and plain.record is not None and with_value.record is not None
    assert old.record.fingerprint == plain.record.fingerprint
    assert with_value.record.fingerprint != plain.record.fingerprint


# -- custom field values ----------------------------------------------------------


@pytest.mark.parametrize(
    ("field_type", "raw", "expected"),
    [
        (FieldType.TEXT, "  hello ", "hello"),
        (FieldType.TEXT, 3.0, "3"),
        (FieldType.NUMBER, "-12.5", -12.5),
        (FieldType.NUMBER, 7, 7),
        (FieldType.DATE, "2026-12-01", "2026-12-01"),
        (FieldType.BOOLEAN, "No", False),
        (FieldType.BOOLEAN, True, True),
        (FieldType.URL, "https://a.example/x?y=1#z", "https://a.example/x?y=1#z"),
        (FieldType.TEXT, "", None),
    ],
)
def test_parse_value(field_type: FieldType, raw: object, expected: object) -> None:
    assert parse_value(field_type, raw) == expected


@pytest.mark.parametrize(
    ("field_type", "raw"),
    [
        (FieldType.NUMBER, "12%"),
        (FieldType.NUMBER, "lots"),
        (FieldType.DATE, "2026"),
        (FieldType.BOOLEAN, "maybe"),
        (FieldType.URL, "javascript:alert(1)"),
    ],
)
def test_parse_value_refuses_invalid_values(field_type: FieldType, raw: object) -> None:
    with pytest.raises(InvalidValueError):
        parse_value(field_type, raw)


def test_clean_values_refuses_unknown_keys_and_merge_keeps_others() -> None:
    tier = custom("Account Tier", FieldType.TEXT)
    with pytest.raises(InvalidValueError, match="no custom field"):
        clean_values({tier.key: tier}, {"typo": "x"})
    changes = clean_values({tier.key: tier}, {tier.key: ""})
    assert changes == {tier.key: None}
    assert merged({tier.key: "old", "other": 1}, changes) == {"other": 1}
