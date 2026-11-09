# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Importing review dates, qualification source URLs and custom fields into the database."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tg_sales.db.database import Database
from tg_sales.db.models import Contact, Organization
from tg_sales.domain.custom_fields import FieldType, RecordType
from tg_sales.domain.importing import RecordOptions, suggest_mapping
from tg_sales.domain.prospects import OrganizationDraft
from tg_sales.services.custom_fields import CustomFieldDraft, CustomFieldError, CustomFieldService
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.import_files import inspect_file, read_table
from tg_sales.services.imports import ImportPlan, ImportService
from tg_sales.services.prospects import ProspectService, ProspectValidationError

pytestmark = pytest.mark.integration

URL = "https://research.example/lists?segment=indie&page=3&sort=-score#entry-12"


@pytest.fixture
def actor(database: Database) -> str:
    return ensure_local_actor(database)


@pytest.fixture
def service(database: Database, actor: str) -> ImportService:
    return ImportService(database, actor)


@pytest.fixture
def fields(database: Database) -> CustomFieldService:
    return CustomFieldService(database)


def plan_csv(
    service: ImportService,
    fields: CustomFieldService,
    tmp_path: Path,
    text: str,
    *,
    overwrite: bool = False,
) -> ImportPlan:
    path = tmp_path / "list.csv"
    path.write_text(text, encoding="utf-8")
    source = inspect_file(path)
    table = read_table(source)
    mappings = suggest_mapping(table.headers, table.rows[:50], fields.list())
    return service.plan(source, table, mappings, RecordOptions(), overwrite=overwrite)


def organization(database: Database, name: str) -> Organization:
    with database.session() as session:
        found = session.query(Organization).filter(Organization.name == name).one()
        session.expunge(found)
        return found


def test_review_date_url_and_custom_fields_are_imported(
    database: Database, service: ImportService, fields: CustomFieldService, tmp_path: Path
) -> None:
    fields.create(CustomFieldDraft("Account Tier", FieldType.TEXT))
    fields.create(CustomFieldDraft("Annual Revenue Estimate", FieldType.NUMBER))
    fields.create(CustomFieldDraft("Buying Role", FieldType.TEXT, RecordType.CONTACT))
    plan = plan_csv(
        service,
        fields,
        tmp_path,
        "Company,Reviewed On,Qualification Source URL,Account Tier,Annual Revenue Estimate,"
        "Contact Name,Email,Buying Role\n"
        f'Pixel Forge,2026-03-14,"{URL}",Tier 1,"250,000",Ana Ruiz,ana@pixel.example,Champion\n',
    )
    assert {m.target for m in plan.mappings} >= {
        "review_date",
        "qualification_source_url",
        "custom:prospect:account_tier",
        "custom:prospect:annual_revenue_estimate",
        "custom:contact:buying_role",
    }
    outcome = service.commit(plan)
    assert outcome.counts.rows_imported == 1
    assert outcome.counts.error_rows == 0
    org = organization(database, "Pixel Forge")
    assert org.reviewed_on == date(2026, 3, 14)
    assert org.qualification_source_url == URL  # complete, nothing truncated
    assert org.custom_fields == {"account_tier": "Tier 1", "annual_revenue_estimate": 250000}
    with database.session() as session:
        contact = session.query(Contact).filter(Contact.organization_id == org.id).one()
        assert contact.custom_fields == {"buying_role": "Champion"}

    detail = ProspectService(database, None).get_detail(org.id)
    assert detail is not None
    assert detail.reviewed_on == date(2026, 3, 14)
    assert ("Qualification source", URL) in [(link.label, link.url) for link in detail.links]
    assert {v.key: v.value for v in detail.custom_fields} == {
        "account_tier": "Tier 1",
        "annual_revenue_estimate": 250000,
    }


def test_invalid_values_are_skipped_with_warnings_and_the_row_still_imported(
    database: Database, service: ImportService, fields: CustomFieldService, tmp_path: Path
) -> None:
    fields.create(CustomFieldDraft("Annual Revenue Estimate", FieldType.NUMBER))
    plan = plan_csv(
        service,
        fields,
        tmp_path,
        "Company,Review Date,Source URL,Annual Revenue Estimate\n"
        "Bad Data Studio,not a date,javascript:alert(1),a lot\n",
    )
    outcome = service.commit(plan)
    assert outcome.counts.organizations_created == 1
    assert sorted(i.column for i in outcome.issues) == [
        "Annual Revenue Estimate",
        "Review Date",
        "Source URL",
    ]
    org = organization(database, "Bad Data Studio")
    assert (org.reviewed_on, org.qualification_source_url, org.custom_fields) == (None, None, {})


def test_duplicate_import_fills_empty_fields_but_keeps_existing_values(
    database: Database, service: ImportService, fields: CustomFieldService, tmp_path: Path
) -> None:
    fields.create(CustomFieldDraft("Account Tier", FieldType.TEXT))
    service.commit(
        plan_csv(
            service,
            fields,
            tmp_path,
            "Company,Website,Reviewed On,Account Tier\n"
            "Pixel Forge,pixel.example,2026-01-01,Tier 1\n",
        )
    )
    second = plan_csv(
        service,
        fields,
        tmp_path,
        "Company,Website,Reviewed On,Account Tier,Source URL\n"
        f'Pixel Forge,pixel.example,2026-06-30,Tier 2,"{URL}"\n',
    )
    outcome = service.commit(second)
    org = organization(database, "Pixel Forge")
    assert org.reviewed_on == date(2026, 1, 1)  # kept
    assert org.custom_fields == {"account_tier": "Tier 1"}  # kept
    assert org.qualification_source_url == URL  # was empty: filled
    messages = {(i.column, i.message) for i in outcome.issues}
    assert ("Review date", "Kept the existing review date; the file has a different value.") in (
        messages
    )
    assert ("Account Tier", "Kept the existing Account Tier; the file has a different value.") in (
        messages
    )
    assert outcome.counts.values_replaced == 0


def test_explicit_overwrite_replaces_values_and_undo_restores_them(
    database: Database, service: ImportService, fields: CustomFieldService, tmp_path: Path
) -> None:
    fields.create(CustomFieldDraft("Account Tier", FieldType.TEXT))
    service.commit(
        plan_csv(
            service,
            fields,
            tmp_path,
            "Company,Website,Reviewed On,Account Tier,Notes\n"
            "Pixel Forge,pixel.example,2026-01-01,Tier 1,Original notes\n",
        )
    )
    replace = plan_csv(
        service,
        fields,
        tmp_path,
        "Company,Website,Reviewed On,Account Tier,Notes\n"
        "Pixel Forge,pixel.example,2026-06-30,Tier 2,Other notes\n",
        overwrite=True,
    )
    outcome = service.commit(replace)
    assert outcome.counts.values_replaced == 2
    org = organization(database, "Pixel Forge")
    assert org.reviewed_on == date(2026, 6, 30)
    assert org.custom_fields == {"account_tier": "Tier 2"}
    assert org.notes == "Original notes"  # notes are never replaced

    service.undo(outcome.job_id)
    org = organization(database, "Pixel Forge")
    assert org.reviewed_on == date(2026, 1, 1)
    assert org.custom_fields == {"account_tier": "Tier 1"}


def test_custom_values_survive_prospect_edits(
    database: Database, service: ImportService, fields: CustomFieldService, tmp_path: Path
) -> None:
    fields.create(CustomFieldDraft("Account Tier", FieldType.TEXT))
    fields.create(CustomFieldDraft("Partner", FieldType.BOOLEAN))
    service.commit(
        plan_csv(
            service,
            fields,
            tmp_path,
            f'Company,Reviewed On,Source URL,Account Tier\nPixel Forge,2026-01-01,"{URL}",Tier 1\n',
        )
    )
    prospects = ProspectService(database, None)
    org = organization(database, "Pixel Forge")
    # A form that does not send the new fields (an older client) keeps them.
    prospects.update(
        org.id,
        OrganizationDraft(
            "Pixel Forge Studios", keep=frozenset({"reviewed_on", "qualification_source_url"})
        ),
    )
    org = organization(database, "Pixel Forge Studios")
    assert org.reviewed_on == date(2026, 1, 1)
    assert org.qualification_source_url == URL
    assert org.custom_fields == {"account_tier": "Tier 1"}

    # Changing one custom field keeps the others; empty clears.
    prospects.update(
        org.id,
        OrganizationDraft(
            "Pixel Forge Studios",
            reviewed_on=date(2026, 2, 2),
            qualification_source_url=URL,
            custom_fields={"partner": "yes"},
        ),
    )
    org = organization(database, "Pixel Forge Studios")
    assert org.custom_fields == {"account_tier": "Tier 1", "partner": True}
    prospects.update(
        org.id,
        OrganizationDraft(
            "Pixel Forge Studios",
            qualification_source_url=URL,
            custom_fields={"account_tier": ""},
        ),
    )
    org = organization(database, "Pixel Forge Studios")
    assert org.custom_fields == {"partner": True}
    assert org.reviewed_on is None  # sent as empty: cleared on purpose

    with pytest.raises(ProspectValidationError, match="Partner"):
        prospects.update(
            org.id, OrganizationDraft("Pixel Forge Studios", custom_fields={"partner": "maybe"})
        )
    with pytest.raises(ProspectValidationError, match="not a valid web address"):
        prospects.update(
            org.id,
            OrganizationDraft("Pixel Forge Studios", qualification_source_url="javascript:x"),
        )


def test_exports_include_new_and_custom_fields(
    database: Database, service: ImportService, fields: CustomFieldService, tmp_path: Path
) -> None:
    fields.create(CustomFieldDraft("Account Tier", FieldType.TEXT))
    service.commit(
        plan_csv(
            service,
            fields,
            tmp_path,
            f'Company,Reviewed On,Source URL,Account Tier\nPixel Forge,2026-01-01,"{URL}",Tier 1\n',
        )
    )
    org = organization(database, "Pixel Forge")
    out = tmp_path / "export.csv"
    ProspectService(database, None).export_csv(out, [org.id])
    text = out.read_text(encoding="utf-8-sig")
    header, line = text.splitlines()[:2]
    assert header.endswith(
        "Review date,Qualification source URL,Archived,Created (UTC),Updated (UTC),Account Tier"
    )
    assert "2026-01-01" in line and URL in line and line.endswith("Tier 1")


def test_custom_field_rules(fields: CustomFieldService) -> None:
    tier = fields.create(CustomFieldDraft("Account Tier", FieldType.TEXT))
    assert (tier.key, tier.target) == ("account_tier", "custom:prospect:account_tier")
    with pytest.raises(CustomFieldError, match="already a custom field"):
        fields.create(CustomFieldDraft("account tier"))
    with pytest.raises(CustomFieldError, match="built-in field"):
        fields.create(CustomFieldDraft("Review Date", FieldType.DATE))
    # The same label is fine for another record type.
    contact_tier = fields.create(CustomFieldDraft("Account Tier", record_type=RecordType.CONTACT))
    assert contact_tier.id != tier.id

    renamed = fields.update(tier.id, "Customer Tier", "A, B or C")
    assert (renamed.key, renamed.label) == ("account_tier", "Customer Tier")  # key is permanent
    archived = fields.set_archived(tier.id, True)
    assert archived.archived
    assert tier.key not in fields.by_key(RecordType.PROSPECT)
    assert fields.set_archived(tier.id, False).archived is False
