# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Custom field definitions for prospects and contacts."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Svc
from tg_sales.domain.custom_fields import (
    FIELD_TYPE_LABELS,
    MAX_DESCRIPTION_LENGTH,
    MAX_LABEL_LENGTH,
    RECORD_TYPE_LABELS,
    CustomFieldInfo,
    FieldType,
    RecordType,
)
from tg_sales.services.custom_fields import CustomFieldDraft

router = APIRouter(tags=["custom-fields"])


class CustomFieldView(BaseModel):
    id: str
    record_type: RecordType
    key: str
    label: str
    field_type: FieldType
    description: str | None
    sort_order: int
    archived: bool
    target: str  # the import mapping value

    @classmethod
    def of(cls, info: CustomFieldInfo) -> CustomFieldView:
        return cls(
            id=info.id,
            record_type=info.record_type,
            key=info.key,
            label=info.label,
            field_type=info.field_type,
            description=info.description,
            sort_order=info.sort_order,
            archived=info.archived,
            target=info.target,
        )


class CustomFieldIn(Body):
    label: str = Field(min_length=1, max_length=MAX_LABEL_LENGTH)
    field_type: FieldType = FieldType.TEXT
    record_type: RecordType = RecordType.PROSPECT
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)


class CustomFieldEdit(Body):
    label: str = Field(min_length=1, max_length=MAX_LABEL_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)


class ArchiveIn(Body):
    archived: bool


class Choice(BaseModel):
    value: str
    label: str


class CustomFieldMeta(BaseModel):
    field_types: list[Choice]
    record_types: list[Choice]


@router.get("/custom-fields", response_model=list[CustomFieldView])
def list_fields(
    svc: Svc, record_type: RecordType | None = None, include_archived: bool = False
) -> list[CustomFieldView]:
    return [
        CustomFieldView.of(f)
        for f in svc.custom_fields.list(record_type, include_archived=include_archived)
    ]


@router.get("/custom-fields/meta", response_model=CustomFieldMeta)
def meta() -> CustomFieldMeta:
    return CustomFieldMeta(
        field_types=[Choice(value=t.value, label=label) for t, label in FIELD_TYPE_LABELS.items()],
        record_types=[
            Choice(value=t.value, label=label) for t, label in RECORD_TYPE_LABELS.items()
        ],
    )


@router.post("/custom-fields", response_model=CustomFieldView, status_code=201)
def create_field(body: CustomFieldIn, svc: Svc) -> CustomFieldView:
    return CustomFieldView.of(
        svc.custom_fields.create(
            CustomFieldDraft(body.label, body.field_type, body.record_type, body.description)
        )
    )


@router.put("/custom-fields/{field_id}", response_model=CustomFieldView)
def update_field(field_id: str, body: CustomFieldEdit, svc: Svc) -> CustomFieldView:
    return CustomFieldView.of(svc.custom_fields.update(field_id, body.label, body.description))


@router.post("/custom-fields/{field_id}/archive", response_model=CustomFieldView)
def archive_field(field_id: str, body: ArchiveIn, svc: Svc) -> CustomFieldView:
    return CustomFieldView.of(svc.custom_fields.set_archived(field_id, body.archived))
