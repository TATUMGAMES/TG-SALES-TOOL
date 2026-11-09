# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Import rules: column mapping, value interpretation and row validation.

These functions are pure. They turn a parsed table (headers plus rows of cell
values) into validated :class:`ImportRecord` objects with row-level issues,
without touching files or the database. Nothing is guessed: ambiguous headers
are left unmapped, ambiguous dates are reported, and outreach status is only
taken from an explicit column (never inferred from the presence of an email).

Besides the built-in fields, a column can be mapped to a user-defined custom
field (see :mod:`tg_sales.domain.custom_fields`). Values that do not fit the
field's type are reported as warnings and left out; nothing is silently
dropped or changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from tg_sales.domain.custom_fields import (
    CustomFieldInfo,
    FieldType,
    InvalidValueError,
    RecordType,
    parse_value,
)
from tg_sales.domain.enums import ContactStatus, OrganizationType, ReleasePrecision
from tg_sales.domain.normalization import (
    DateOrder,
    Flag,
    domain_from_url,
    exact_url,
    looks_like_formula,
    normalize_email,
    normalize_name,
    normalize_url,
    parse_date,
    parse_flag,
    social_network,
    split_emails,
    split_list,
)

CellValue = str | int | float | bool | date | datetime | None

MAX_CELL_CHARS = 10_000


class ImportField(StrEnum):
    ORGANIZATION_NAME = "organization_name"
    WEBSITE = "website"
    ORGANIZATION_TYPE = "organization_type"
    LOCATION = "location"
    COUNTRY = "country"
    TAGS = "tags"
    ORGANIZATION_NOTES = "organization_notes"
    CONTACT_NAME = "contact_name"
    CONTACT_FIRST_NAME = "contact_first_name"
    CONTACT_LAST_NAME = "contact_last_name"
    ROLE_TITLE = "role_title"
    EMAIL = "email"
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    SOCIAL = "social"
    CONTACTED = "contacted"
    CONTACT_NOTES = "contact_notes"
    GAME_TITLE = "game_title"
    RELEASE_DATE = "release_date"
    PLATFORM = "platform"
    STORE_URL = "store_url"
    REVIEW_DATE = "review_date"
    QUALIFICATION_SOURCE_URL = "qualification_source_url"


@dataclass(frozen=True)
class FieldSpec:
    field: ImportField
    label: str
    synonyms: tuple[str, ...]
    multiple: bool = False  # several columns may map to this field


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        ImportField.ORGANIZATION_NAME,
        "Studio / company name",
        (
            "studio",
            "studio name",
            "company",
            "company name",
            "developer",
            "developer name",
            "dev",
            "organization",
            "organisation",
            "organization name",
            "org",
            "business",
            "account",
            "account name",
            "team",
            "prospect",
        ),
    ),
    FieldSpec(
        ImportField.WEBSITE,
        "Website",
        ("website", "web", "url", "site", "homepage", "home page", "web site", "domain", "link"),
    ),
    FieldSpec(
        ImportField.ORGANIZATION_TYPE,
        "Company type",
        ("type", "company type", "category", "segment", "org type", "organization type"),
    ),
    FieldSpec(ImportField.LOCATION, "Location", ("location", "city", "region", "hq", "address")),
    FieldSpec(ImportField.COUNTRY, "Country", ("country", "nation", "country code")),
    FieldSpec(ImportField.TAGS, "Tags", ("tags", "tag", "labels", "label", "keywords"), True),
    FieldSpec(
        ImportField.ORGANIZATION_NOTES,
        "Company notes",
        ("notes", "note", "comments", "comment", "description", "remarks"),
        True,
    ),
    FieldSpec(
        ImportField.CONTACT_NAME,
        "Contact name",
        (
            "contact name",
            "full name",
            "person",
            "contact person",
            "people",
            "point of contact",
            "poc",
        ),
    ),
    FieldSpec(
        ImportField.CONTACT_FIRST_NAME,
        "Contact first name",
        ("first name", "firstname", "given name"),
    ),
    FieldSpec(
        ImportField.CONTACT_LAST_NAME,
        "Contact last name",
        ("last name", "lastname", "surname", "family name"),
    ),
    FieldSpec(
        ImportField.ROLE_TITLE,
        "Contact role / title",
        ("role", "job title", "position", "job", "contact title", "job role", "designation"),
    ),
    FieldSpec(
        ImportField.EMAIL,
        "Contact email",
        (
            "email",
            "e mail",
            "email address",
            "emails",
            "contact email",
            "business email",
            "work email",
            "mail",
        ),
    ),
    FieldSpec(ImportField.LINKEDIN, "LinkedIn URL", ("linkedin", "linkedin url", "linked in")),
    FieldSpec(
        ImportField.TWITTER,
        "X / Twitter URL",
        ("twitter", "x", "x twitter", "twitter url", "x url"),
    ),
    FieldSpec(
        ImportField.SOCIAL,
        "Other social URL",
        ("social", "socials", "social url", "social media", "social link", "socials url"),
        True,
    ),
    FieldSpec(
        ImportField.CONTACTED,
        "Contacted (yes / no)",
        (
            "contacted",
            "reached out",
            "outreach",
            "outreach done",
            "contacted yet",
            "emailed",
            "messaged",
            "sent",
            "status",
        ),
    ),
    FieldSpec(ImportField.CONTACT_NOTES, "Contact notes", ("contact notes", "contact note"), True),
    FieldSpec(
        ImportField.GAME_TITLE,
        "Game title",
        ("game", "game title", "game name", "games", "product", "project"),
    ),
    FieldSpec(
        ImportField.RELEASE_DATE,
        "Release date",
        ("release date", "release", "launch date", "released", "release day", "launch"),
    ),
    FieldSpec(ImportField.PLATFORM, "Platform", ("platform", "platforms", "store", "console")),
    FieldSpec(
        ImportField.STORE_URL,
        "Store page URL",
        ("store url", "steam url", "steam link", "store link", "steam page", "store page"),
    ),
    FieldSpec(
        ImportField.REVIEW_DATE,
        "Review date",
        (
            "reviewed on",
            "review date",
            "last reviewed",
            "date reviewed",
            "reviewed date",
            "last review date",
            "last review",
            "reviewed",
        ),
    ),
    FieldSpec(
        ImportField.QUALIFICATION_SOURCE_URL,
        "Qualification source URL",
        (
            "qualification source url",
            "qualification source",
            "qualification url",
            "qualification link",
            "source url",
            "source link",
            "research url",
            "research link",
            "reference url",
            "reference link",
            "evidence url",
        ),
    ),
)
SPEC_BY_FIELD: dict[ImportField, FieldSpec] = {spec.field: spec for spec in FIELD_SPECS}

# Headers that could mean several fields; resolved only from context or values.
AMBIGUOUS_HEADERS: dict[str, tuple[ImportField, ...]] = {
    "name": (ImportField.ORGANIZATION_NAME, ImportField.CONTACT_NAME, ImportField.GAME_TITLE),
    "title": (ImportField.GAME_TITLE, ImportField.ROLE_TITLE),
    "contact": (ImportField.CONTACT_NAME, ImportField.EMAIL),
}

CONFIDENCE_EXACT = 1.0
CONFIDENCE_CONTEXT = 0.8
CONFIDENCE_PARTIAL = 0.6


@dataclass(frozen=True)
class ColumnMapping:
    """Suggested or chosen target for one source column.

    The target is a built-in ``field`` or a ``custom`` field (never both).
    """

    column: int
    header: str
    field: ImportField | None
    confidence: float = 0.0
    note: str = ""
    custom: CustomFieldInfo | None = None

    @property
    def target(self) -> str | None:
        """The target as text: a field value or ``custom:<record type>:<key>``."""
        if self.custom is not None:
            return self.custom.target
        return self.field.value if self.field is not None else None

    def target_label(self) -> str:
        if self.custom is not None:
            return self.custom.label
        return SPEC_BY_FIELD[self.field].label if self.field is not None else ""


def custom_header_key(text: str) -> str:
    """How headers and custom field labels are compared (ignoring case and punctuation)."""
    return normalize_name(text.replace("_", " "))


def _looks_like_email_column(samples: Sequence[CellValue]) -> bool:
    texts = [str(v).strip() for v in samples if v is not None and str(v).strip()]
    if not texts:
        return False
    emails = sum(1 for t in texts if any(normalize_email(p) for p in split_emails(t)))
    return emails / len(texts) >= 0.8


def _partial_matches(header: str) -> list[ImportField]:
    """Fields with a multi-word synonym contained in the header as whole words."""
    padded = f" {header} "
    found: list[ImportField] = []
    for spec in FIELD_SPECS:
        if any(" " in s and f" {s} " in padded for s in spec.synonyms) and spec.field not in found:
            found.append(spec.field)
    return found


def suggest_mapping(
    headers: Sequence[str],
    samples: Sequence[Sequence[CellValue]] = (),
    custom_fields: Sequence[CustomFieldInfo] = (),
) -> list[ColumnMapping]:
    """Suggest a target field for every column, with confidence and notes.

    ``samples`` are the first data rows; they are only used to resolve a few
    ambiguous headers (for example "Contact" holding email addresses). A header
    matching the label (or key) of an active custom field is suggested for that
    field, since the user created it for exactly this kind of column.
    """
    exact = {s: spec.field for spec in FIELD_SPECS for s in spec.synonyms}
    by_label: dict[str, CustomFieldInfo] = {}
    for custom in custom_fields:
        if not custom.archived:
            by_label.setdefault(custom_header_key(custom.label), custom)
            by_label.setdefault(custom_header_key(custom.key), custom)
    proposals: list[ColumnMapping] = []
    ambiguous: list[int] = []
    for column, header in enumerate(headers):
        key = normalize_name(header)
        if not key:
            proposals.append(ColumnMapping(column, header, None, note="Column has no header."))
        elif (info := by_label.get(custom_header_key(header))) is not None:
            proposals.append(
                ColumnMapping(column, header, None, CONFIDENCE_EXACT, "Custom field.", info)
            )
        elif key in exact:
            proposals.append(ColumnMapping(column, header, exact[key], CONFIDENCE_EXACT))
        elif key in AMBIGUOUS_HEADERS:
            proposals.append(ColumnMapping(column, header, None))
            ambiguous.append(column)
        elif len(partial := _partial_matches(key)) == 1:
            proposals.append(ColumnMapping(column, header, partial[0], CONFIDENCE_PARTIAL))
        elif partial:
            labels = " or ".join(SPEC_BY_FIELD[f].label for f in partial)
            note = f"Could be {labels}; choose one."
            proposals.append(ColumnMapping(column, header, None, note=note))
        else:
            proposals.append(ColumnMapping(column, header, None, note="Not recognized."))

    mapped: set[ImportField] = {p.field for p in proposals if p.field is not None}
    for column in ambiguous:
        header = proposals[column].header
        key = normalize_name(header)
        choice: ImportField | None = None
        if key == "contact":
            values = [row[column] for row in samples if column < len(row)]
            choice = (
                ImportField.EMAIL if _looks_like_email_column(values) else ImportField.CONTACT_NAME
            )
        elif key == "name" and ImportField.ORGANIZATION_NAME in mapped:
            choice = ImportField.CONTACT_NAME
        elif key == "title" and ImportField.GAME_TITLE in mapped:
            choice = ImportField.ROLE_TITLE
        elif key == "title" and ImportField.ROLE_TITLE in mapped:
            choice = ImportField.GAME_TITLE
        if choice is not None and choice not in mapped:
            mapped.add(choice)
            proposals[column] = ColumnMapping(
                column, header, choice, CONFIDENCE_CONTEXT, note="Inferred from other columns."
            )
        else:
            labels = " or ".join(SPEC_BY_FIELD[f].label for f in AMBIGUOUS_HEADERS[key])
            proposals[column] = ColumnMapping(
                column, header, None, note=f"Ambiguous: could be {labels}; choose one."
            )
    return resolve_duplicate_targets(proposals)


def _single_target(m: ColumnMapping) -> str | None:
    """The target of ``m`` when only one column may use it (always for custom fields)."""
    if m.custom is not None:
        return m.custom.target
    if m.field is None or SPEC_BY_FIELD[m.field].multiple:
        return None
    return m.field.value


def resolve_duplicate_targets(mappings: Sequence[ColumnMapping]) -> list[ColumnMapping]:
    """Keep only the most confident column for each single-column field.

    The other columns are left unmapped with a note saying why, so the user
    sees them and can choose another target.
    """
    best: dict[str, ColumnMapping] = {}
    for m in mappings:
        target = _single_target(m)
        if target is None:
            continue
        current = best.get(target)
        if current is None or m.confidence > current.confidence:
            best[target] = m
    result = []
    for m in mappings:
        target = _single_target(m)
        if target is not None and best[target].column != m.column:
            note = f"Another column is already mapped to {m.target_label()}."
            result.append(ColumnMapping(m.column, m.header, None, 0.0, note))
        else:
            result.append(m)
    return result


def mapping_problems(mappings: Sequence[ColumnMapping]) -> list[str]:
    """Problems that prevent importing with this mapping (empty if usable)."""
    problems = []
    targets = [m.field for m in mappings if m.field is not None]
    if ImportField.ORGANIZATION_NAME not in targets:
        problems.append("Choose the column that holds the studio or company name.")
    singles: list[str] = []
    labels: dict[str, str] = {}
    for m in mappings:
        target = _single_target(m)
        if target is not None:
            singles.append(target)
            labels[target] = m.target_label()
    for target in set(singles):
        if singles.count(target) > 1:
            problems.append(f"Only one column can be mapped to {labels[target]}.")
    return sorted(problems)


class IssueSeverity(StrEnum):
    ERROR = "error"  # the row is not imported
    WARNING = "warning"  # the row is imported; something was ignored or adjusted


@dataclass(frozen=True)
class RowIssue:
    row_number: int  # 1-based line/row number in the source file
    severity: IssueSeverity
    column: str
    message: str


@dataclass(frozen=True)
class ContactRecord:
    name: str | None
    role_title: str | None
    email: str | None
    social_urls: Mapping[str, str]
    status: ContactStatus
    notes: str | None
    custom_values: Mapping[str, object] = field(default_factory=dict)  # by field key


@dataclass(frozen=True)
class GameRecord:
    title: str
    release_date: date | None
    release_precision: ReleasePrecision
    platform: str | None
    store_url: str | None


@dataclass(frozen=True)
class ImportRecord:
    row_number: int
    organization_name: str
    website: str | None
    domain: str | None
    company_type: OrganizationType | None
    location: str | None
    country: str | None
    tags: tuple[str, ...]
    notes: str | None
    contacts: tuple[ContactRecord, ...]
    game: GameRecord | None
    fingerprint: str
    reviewed_on: date | None = None
    qualification_source_url: str | None = None
    custom_values: Mapping[str, object] = field(default_factory=dict)  # by field key


@dataclass
class RowResult:
    """Outcome of interpreting one source row."""

    row_number: int
    record: ImportRecord | None
    issues: list[RowIssue] = field(default_factory=list)
    blank: bool = False

    @property
    def has_errors(self) -> bool:
        return any(i.severity is IssueSeverity.ERROR for i in self.issues)


@dataclass(frozen=True)
class RecordOptions:
    date_order: DateOrder = DateOrder.AUTO


_TYPE_WORDS: dict[str, OrganizationType] = {
    "studio": OrganizationType.STUDIO,
    "developer": OrganizationType.STUDIO,
    "dev": OrganizationType.STUDIO,
    "indie": OrganizationType.STUDIO,
    "game studio": OrganizationType.STUDIO,
    "publisher": OrganizationType.PUBLISHER,
    "publishing": OrganizationType.PUBLISHER,
    "data buyer": OrganizationType.DATA_BUYER,
    "data licensing": OrganizationType.DATA_BUYER,
    "buyer": OrganizationType.DATA_BUYER,
    "other": OrganizationType.OTHER,
}


def cell_text(value: CellValue) -> str | None:
    """Cell value as trimmed text; numbers lose a trailing ``.0``; blank is None."""
    if value is None:
        return None
    if isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    elif isinstance(value, datetime):
        text = value.date().isoformat() if value.time() == datetime.min.time() else str(value)
    elif isinstance(value, date):
        text = value.isoformat()
    else:
        text = str(value)
    text = text.replace("\x00", "").strip()
    return text or None


class _RowReader:
    def __init__(
        self,
        row_number: int,
        cells: Sequence[CellValue],
        mappings: Sequence[ColumnMapping],
        options: RecordOptions,
    ) -> None:
        self.row_number = row_number
        self.cells = cells
        self.options = options
        self.issues: list[RowIssue] = []
        self.columns: dict[ImportField, list[ColumnMapping]] = {}
        self.custom: list[ColumnMapping] = []
        for m in mappings:
            if m.custom is not None:
                self.custom.append(m)
            elif m.field is not None:
                self.columns.setdefault(m.field, []).append(m)

    def issue(self, severity: IssueSeverity, column: str, message: str) -> None:
        self.issues.append(RowIssue(self.row_number, severity, column, message))

    def raw(self, f: ImportField) -> list[tuple[str, CellValue]]:
        return [
            (m.header, self.cells[m.column] if m.column < len(self.cells) else None)
            for m in self.columns.get(f, [])
        ]

    def texts(self, f: ImportField) -> list[tuple[str, str]]:
        result = []
        for header, value in self.raw(f):
            text = cell_text(value)
            if text is None:
                continue
            if len(text) > MAX_CELL_CHARS:
                text = text[:MAX_CELL_CHARS]
                self.issue(
                    IssueSeverity.WARNING,
                    header,
                    f"Text longer than {MAX_CELL_CHARS:,} characters was shortened.",
                )
            if looks_like_formula(text):
                self.issue(
                    IssueSeverity.WARNING,
                    header,
                    "Starts like a spreadsheet formula; kept as plain text, never calculated.",
                )
            result.append((header, text))
        return result

    def first(self, f: ImportField) -> str | None:
        values = self.texts(f)
        return values[0][1] if values else None

    def joined(self, f: ImportField) -> str | None:
        values = [text for _, text in self.texts(f)]
        return "\n".join(values) if values else None

    def header(self, f: ImportField) -> str:
        columns = self.columns.get(f)
        return columns[0].header if columns else SPEC_BY_FIELD[f].label

    def custom_values(self, record_type: RecordType) -> dict[str, object]:
        """Validated values of the custom-field columns for ``record_type``, by key."""
        values: dict[str, object] = {}
        for m in self.custom:
            info = m.custom
            if info is None or info.record_type is not record_type:
                continue
            raw = self.cells[m.column] if m.column < len(self.cells) else None
            if info.field_type is FieldType.TEXT:
                text = cell_text(raw)
                if text is not None and looks_like_formula(text):
                    self.issue(
                        IssueSeverity.WARNING,
                        m.header,
                        "Starts like a spreadsheet formula; kept as plain text, never calculated.",
                    )
                raw = text
            try:
                value = parse_value(info.field_type, raw, date_order=self.options.date_order)
            except InvalidValueError as exc:
                self.issue(
                    IssueSeverity.WARNING,
                    m.header,
                    f"{exc} “{info.label}” was left empty for this row.",
                )
                continue
            if value is not None:
                values[info.key] = value
        return values


def fingerprint(values: Mapping[str, object]) -> str:
    """Stable hash of a row's normalized content, used to recognize re-imports."""
    encoded = json.dumps(values, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _contact_status(reader: _RowReader) -> ContactStatus:
    raw = reader.raw(ImportField.CONTACTED)
    if not raw:
        return ContactStatus.UNKNOWN
    header, value = raw[0]
    flag, recognized = parse_flag(value)
    if not recognized:
        reader.issue(
            IssueSeverity.WARNING,
            header,
            "Contacted value not recognized (use yes/no or a checkmark); saved as unknown.",
        )
    return {
        Flag.YES: ContactStatus.ATTEMPTED,
        Flag.NO: ContactStatus.NOT_CONTACTED,
        Flag.UNKNOWN: ContactStatus.UNKNOWN,
    }[flag]


def _social_urls(reader: _RowReader) -> dict[str, str]:
    urls: dict[str, str] = {}
    sources = [
        (ImportField.LINKEDIN, "linkedin"),
        (ImportField.TWITTER, "twitter"),
        (ImportField.SOCIAL, None),
    ]
    for f, network in sources:
        for header, text in reader.texts(f):
            for part in split_list(text) if f is ImportField.SOCIAL else [text]:
                url = normalize_url(part)
                if url is None:
                    reader.issue(IssueSeverity.WARNING, header, "Not a valid web address; ignored.")
                    continue
                key = network or social_network(url) or "other"
                if key in urls:
                    suffix = 2
                    while f"{key} {suffix}" in urls:
                        suffix += 1
                    key = f"{key} {suffix}"
                urls[key] = url
    return urls


def _contacts(reader: _RowReader) -> list[ContactRecord]:
    full_name = reader.first(ImportField.CONTACT_NAME)
    first = reader.first(ImportField.CONTACT_FIRST_NAME)
    last = reader.first(ImportField.CONTACT_LAST_NAME)
    if full_name is None and (first or last):
        full_name = " ".join(p for p in (first, last) if p)
    role = reader.first(ImportField.ROLE_TITLE)
    notes = reader.joined(ImportField.CONTACT_NOTES)
    email_header = reader.header(ImportField.EMAIL)

    emails: list[str] = []
    for header, text in reader.texts(ImportField.EMAIL):
        invalid = False
        for part in split_emails(text):
            normalized = normalize_email(part)
            if normalized is None:
                invalid = True
            elif normalized not in emails:
                emails.append(normalized)
        if invalid:
            reader.issue(IssueSeverity.WARNING, header, "Not a valid email address; ignored.")

    socials = _social_urls(reader)
    status = _contact_status(reader)
    custom = reader.custom_values(RecordType.CONTACT)

    names = split_list(full_name) if full_name and (";" in full_name or "\n" in full_name) else []
    if len(emails) > 1 and len(names) == len(emails):
        return [
            ContactRecord(n, role, e, {}, status, notes, custom)
            for n, e in zip(names, emails, strict=True)
        ]
    if len(emails) > 1:
        reader.issue(
            IssueSeverity.WARNING,
            email_header,
            f"{len(emails)} email addresses for one contact; the first was used and the "
            "others were added to the contact's notes. List one name per email (separated "
            "by ';') to create separate contacts.",
        )
        extra = "Other email addresses from import: " + ", ".join(emails[1:])
        notes = f"{notes}\n{extra}" if notes else extra
    email = emails[0] if emails else None
    if full_name is None and email is None and not socials:
        if role or notes:
            reader.issue(
                IssueSeverity.WARNING,
                reader.header(ImportField.ROLE_TITLE if role else ImportField.CONTACT_NOTES),
                "Contact details ignored because the row has no contact name, email or "
                "social link.",
            )
        if status is not ContactStatus.UNKNOWN:
            reader.issue(
                IssueSeverity.WARNING,
                reader.header(ImportField.CONTACTED),
                "Contacted status ignored because the row has no contact.",
            )
        if custom:
            reader.issue(
                IssueSeverity.WARNING,
                next(m.header for m in reader.custom if m.custom and m.custom.key in custom),
                "Contact custom fields ignored because the row has no contact name, email or "
                "social link.",
            )
        return []
    return [ContactRecord(full_name, role, email, socials, status, notes, custom)]


def _game(reader: _RowReader) -> GameRecord | None:
    title = reader.first(ImportField.GAME_TITLE)
    raw_dates = reader.raw(ImportField.RELEASE_DATE)
    platform = reader.first(ImportField.PLATFORM)
    store_text = reader.first(ImportField.STORE_URL)
    store_url = normalize_url(store_text) if store_text else None
    if store_text and store_url is None:
        reader.issue(
            IssueSeverity.WARNING,
            reader.header(ImportField.STORE_URL),
            "Not a valid web address; ignored.",
        )
    if title is None:
        if any(cell_text(v) for _, v in raw_dates) or platform or store_url:
            reader.issue(
                IssueSeverity.WARNING,
                reader.header(ImportField.GAME_TITLE),
                "Game details ignored because the game title is empty.",
            )
        return None
    release: date | None = None
    precision = ReleasePrecision.UNKNOWN
    if raw_dates:
        header, value = raw_dates[0]
        parsed = parse_date(value, reader.options.date_order)
        if parsed.ambiguous:
            reader.issue(
                IssueSeverity.WARNING,
                header,
                "Date could be day/month or month/day; saved as unknown. Choose the date "
                "order on the mapping step to read it.",
            )
        elif not parsed.recognized:
            reader.issue(IssueSeverity.WARNING, header, "Date not recognized; saved as unknown.")
        release, precision = parsed.value, parsed.precision
    return GameRecord(title, release, precision, platform, store_url)


def _review_date(reader: _RowReader) -> date | None:
    raw = reader.raw(ImportField.REVIEW_DATE)
    if not raw:
        return None
    header, value = raw[0]
    if cell_text(value) is None:
        return None
    parsed = parse_date(value, reader.options.date_order)
    if parsed.ambiguous:
        reader.issue(
            IssueSeverity.WARNING,
            header,
            "Review date could be day/month or month/day; left empty. Choose the date "
            "order on the mapping step to read it.",
        )
        return None
    if parsed.value is None:
        reader.issue(IssueSeverity.WARNING, header, "Review date not recognized; left empty.")
        return None
    if parsed.precision is not ReleasePrecision.DAY:
        reader.issue(
            IssueSeverity.WARNING,
            header,
            "Review date is not a full date (day, month and year); left empty.",
        )
        return None
    return parsed.value


def _qualification_url(reader: _RowReader) -> str | None:
    text = reader.first(ImportField.QUALIFICATION_SOURCE_URL)
    if text is None:
        return None
    url = exact_url(text)
    if url is None:
        reader.issue(
            IssueSeverity.WARNING,
            reader.header(ImportField.QUALIFICATION_SOURCE_URL),
            "Not a valid web address (http or https); the qualification source was left empty.",
        )
    return url


def build_record(
    row_number: int,
    cells: Sequence[CellValue],
    mappings: Sequence[ColumnMapping],
    options: RecordOptions = RecordOptions(),  # noqa: B008 - immutable default
) -> RowResult:
    """Interpret one source row using the chosen column mapping."""
    if all(cell_text(c) is None for c in cells):
        return RowResult(row_number, None, blank=True)
    reader = _RowReader(row_number, cells, mappings, options)
    name = reader.first(ImportField.ORGANIZATION_NAME)
    website_text = reader.first(ImportField.WEBSITE)
    website = normalize_url(website_text) if website_text else None
    if website_text and website is None:
        reader.issue(
            IssueSeverity.WARNING,
            reader.header(ImportField.WEBSITE),
            "Not a valid web address (http or https); ignored.",
        )
    company_type: OrganizationType | None = None
    type_text = reader.first(ImportField.ORGANIZATION_TYPE)
    if type_text:
        company_type = _TYPE_WORDS.get(normalize_name(type_text))
        if company_type is None:
            reader.issue(
                IssueSeverity.WARNING,
                reader.header(ImportField.ORGANIZATION_TYPE),
                "Company type not recognized (studio, publisher, data buyer, other); "
                "saved as unknown.",
            )
    tags: list[str] = []
    for _, text in reader.texts(ImportField.TAGS):
        tags.extend(t for t in split_list(text) if t not in tags)
    contacts = _contacts(reader)
    game = _game(reader)
    location = reader.first(ImportField.LOCATION)
    country = reader.first(ImportField.COUNTRY)
    notes = reader.joined(ImportField.ORGANIZATION_NOTES)
    reviewed_on = _review_date(reader)
    qualification_url = _qualification_url(reader)
    custom = reader.custom_values(RecordType.PROSPECT)

    if name is None:
        reader.issue(
            IssueSeverity.ERROR,
            reader.header(ImportField.ORGANIZATION_NAME),
            "No studio or company name; the row was not imported.",
        )
        return RowResult(row_number, None, reader.issues)

    content: dict[str, object] = {
        "name": normalize_name(name),
        "website": website,
        "type": company_type,
        "location": location,
        "country": country,
        "tags": sorted(tags),
        "notes": notes,
        "contacts": [
            [c.name, c.role_title, c.email, sorted(c.social_urls.items()), c.status, c.notes]
            for c in contacts
        ],
        "game": None
        if game is None
        else [game.title, game.release_date, game.release_precision, game.platform, game.store_url],
    }
    # Newer fields are added only when present, so rows that do not use them keep
    # the fingerprint they had before (re-imports are still recognized).
    if reviewed_on is not None:
        content["reviewed_on"] = reviewed_on
    if qualification_url is not None:
        content["qualification_source_url"] = qualification_url
    if custom:
        content["custom"] = sorted(custom.items())
    contact_custom = [sorted(c.custom_values.items()) for c in contacts if c.custom_values]
    if contact_custom:
        content["contact_custom"] = contact_custom
    record = ImportRecord(
        row_number=row_number,
        organization_name=name,
        website=website,
        domain=domain_from_url(website),
        company_type=company_type,
        location=location,
        country=country,
        tags=tuple(tags),
        notes=notes,
        contacts=tuple(contacts),
        game=game,
        fingerprint=fingerprint(content),
        reviewed_on=reviewed_on,
        qualification_source_url=qualification_url,
        custom_values=custom,
    )
    return RowResult(row_number, record, reader.issues)


def build_records(
    rows: Sequence[Sequence[CellValue]],
    mappings: Sequence[ColumnMapping],
    options: RecordOptions = RecordOptions(),  # noqa: B008 - immutable default
    *,
    row_numbers: Sequence[int] | None = None,
) -> list[RowResult]:
    """Interpret every data row.

    ``row_numbers`` are the rows' line numbers in the source file (by default
    2, 3, … after a header on line 1) so issues point at the right place.
    """
    numbers = row_numbers if row_numbers is not None else range(2, 2 + len(rows))
    return [
        build_record(number, row, mappings, options)
        for number, row in zip(numbers, rows, strict=True)
    ]
