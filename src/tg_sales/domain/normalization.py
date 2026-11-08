"""Normalization used for indexing, duplicate detection and imports.

Normalized values are stored alongside the original values, which are never
modified, so the user always sees what was entered or imported. Parsers here
never guess: input that cannot be interpreted with confidence is reported as
unknown so the user can decide.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from tg_sales.domain.enums import ReleasePrecision

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EMAIL_SPLIT = re.compile(r"[;,\s|/]+")
_LIST_SPLIT = re.compile(r"[;,|\n]+")
_HOST_LABEL = re.compile(r"^[a-z0-9¡-￿-]{1,63}$")

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

# Domains shared by unrelated organizations: never evidence that two records
# are the same company.
GENERIC_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "gmx.de",
        "web.de",
        "mail.ru",
        "yandex.ru",
        "qq.com",
        "163.com",
        "naver.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "tiktok.com",
        "discord.gg",
        "discord.com",
        "linktr.ee",
        "itch.io",
        "github.com",
        "github.io",
        "steampowered.com",
        "store.steampowered.com",
        "steamcommunity.com",
        "epicgames.com",
        "store.epicgames.com",
        "gog.com",
        "apple.com",
        "apps.apple.com",
        "play.google.com",
        "google.com",
        "sites.google.com",
        "wixsite.com",
        "carrd.co",
        "bsky.app",
    }
)

# Company-form words ignored when comparing organization names.
_COMPANY_SUFFIXES = frozenset(
    {
        "inc",
        "ltd",
        "llc",
        "gmbh",
        "co",
        "corp",
        "corporation",
        "company",
        "limited",
        "sa",
        "sas",
        "srl",
        "bv",
        "ab",
        "oy",
        "kk",
        "pty",
        "plc",
        "ag",
    }
)

SOCIAL_NETWORKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("linkedin", ("linkedin.com",)),
    ("twitter", ("twitter.com", "x.com")),
    ("bluesky", ("bsky.app",)),
    ("facebook", ("facebook.com", "fb.com")),
    ("instagram", ("instagram.com",)),
    ("youtube", ("youtube.com", "youtu.be")),
    ("discord", ("discord.gg", "discord.com")),
    ("tiktok", ("tiktok.com",)),
    ("twitch", ("twitch.tv",)),
    ("github", ("github.com",)),
)


def normalize_name(name: str) -> str:
    """Case- and punctuation-insensitive form of a name (Unicode letters kept)."""
    folded = unicodedata.normalize("NFKC", name).casefold()
    return _NON_WORD.sub(" ", folded).strip()


def core_name(name: str) -> str:
    """Normalized name without company-form words such as "Inc" or "GmbH"."""
    words = [w for w in normalize_name(name).split() if w not in _COMPANY_SUFFIXES]
    return " ".join(words)


def normalize_email(email: str | None) -> str | None:
    """Lowercased, trimmed email address, or None if it is not a plausible address."""
    if email is None:
        return None
    candidate = unicodedata.normalize("NFKC", email).strip().lower()
    candidate = candidate.removeprefix("mailto:")
    return candidate if _EMAIL.match(candidate) else None


def split_emails(text: str | None) -> list[str]:
    """Split a cell holding one or more email addresses; keeps input order."""
    if not text:
        return []
    return [part for part in _EMAIL_SPLIT.split(text.strip()) if part]


def split_list(text: str | None) -> list[str]:
    """Split a cell holding a list separated by ``;``, ``,``, ``|`` or new lines."""
    if not text:
        return []
    return [part.strip() for part in _LIST_SPLIT.split(text) if part.strip()]


def _valid_host(host: str) -> bool:
    labels = host.split(".")
    return len(labels) >= 2 and all(_HOST_LABEL.match(label) for label in labels)


def normalize_url(url: str | None) -> str | None:
    """Canonical http(s) URL, or None if the text is not a safe web address.

    Missing schemes default to https. Other schemes (``javascript:``,
    ``file:``, ``data:`` …) and URLs carrying credentials are rejected.
    """
    if not url:
        return None
    text = unicodedata.normalize("NFKC", url).strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    if "://" not in text:
        if ":" in text.split("/", 1)[0] and not re.match(r"^[^:]+:\d+(/|$)", text):
            return None  # some other scheme, e.g. "javascript:alert(1)"
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ALLOWED_URL_SCHEMES or not host:
        return None
    if parts.username or parts.password:
        return None
    host = host.lower().rstrip(".")
    if not _valid_host(host):
        return None
    netloc = host if port is None else f"{host}:{port}"
    path = parts.path if parts.path not in ("", "/") else ""
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def domain_from_url(url: str | None) -> str | None:
    """Lowercase host name of a website URL without a leading ``www.``."""
    normalized = normalize_url(url)
    if normalized is None:
        return None
    host = urlsplit(normalized).hostname
    return host.removeprefix("www.") if host else None


def domain_from_email(email: str | None) -> str | None:
    normalized = normalize_email(email)
    return normalized.rsplit("@", 1)[1] if normalized else None


def is_generic_domain(domain: str | None) -> bool:
    """True for shared hosts (webmail, social networks, stores) that identify nobody."""
    if not domain:
        return True
    return any(domain == g or domain.endswith(f".{g}") for g in GENERIC_DOMAINS)


def identifying_domain(domain: str | None) -> str | None:
    """``domain`` if it can identify an organization, else None."""
    return None if is_generic_domain(domain) else domain


def social_network(url: str) -> str | None:
    """The social network a URL belongs to (``linkedin``, ``twitter`` …), if known."""
    host = domain_from_url(url)
    if host is None:
        return None
    for network, hosts in SOCIAL_NETWORKS:
        if any(host == h or host.endswith(f".{h}") for h in hosts):
            return network
    return None


class Flag(StrEnum):
    """A yes/no answer where missing or unreadable input stays unknown."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


_YES = frozenset(
    {
        "yes",
        "y",
        "true",
        "t",
        "1",
        "x",
        "done",
        "contacted",
        "reached out",
        "reached",
        "sent",
        "emailed",
        "messaged",
        "oui",
        "si",
        "sí",
        "ja",
        "da",
    }
)
_NO = frozenset(
    {
        "no",
        "n",
        "false",
        "f",
        "0",
        "not contacted",
        "not yet",
        "pending",
        "todo",
        "to do",
        "non",
        "nein",
        "nee",
    }
)
_YES_SYMBOLS = frozenset("✓✔☑✅🗸")
_NO_SYMBOLS = frozenset("✗✘☐❌✕✖")


def parse_flag(value: object) -> tuple[Flag, bool]:
    """Interpret a checkmark/yes/no cell. Returns (flag, recognized).

    Blank cells are UNKNOWN and recognized; unreadable text is UNKNOWN and
    not recognized, so the caller can warn about it.
    """
    if value is None:
        return Flag.UNKNOWN, True
    if isinstance(value, bool):
        return (Flag.YES if value else Flag.NO), True
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return Flag.UNKNOWN, True
    if text in _YES_SYMBOLS:
        return Flag.YES, True
    if text in _NO_SYMBOLS:
        return Flag.NO, True
    lowered = " ".join(text.casefold().replace("_", " ").replace("-", " ").split())
    if lowered in _YES:
        return Flag.YES, True
    if lowered in _NO:
        return Flag.NO, True
    if lowered in {"unknown", "?", "n/a", "na"}:
        return Flag.UNKNOWN, True
    return Flag.UNKNOWN, False


class DateOrder(StrEnum):
    """How to read dates like 03/04/2027 where day and month are both ≤ 12."""

    AUTO = "auto"  # report as ambiguous
    MONTH_FIRST = "month_first"
    DAY_FIRST = "day_first"


@dataclass(frozen=True)
class ParsedDate:
    value: date | None
    precision: ReleasePrecision
    ambiguous: bool = False
    recognized: bool = True


_UNKNOWN_DATE_WORDS = frozenset(
    {"tba", "tbd", "coming soon", "soon", "to be announced", "unknown", "n/a", "na", "?"}
)
_MONTHS = {name.casefold(): i for i, name in enumerate(calendar.month_name) if name} | {
    name.casefold(): i for i, name in enumerate(calendar.month_abbr) if name
}
_MONTHS["sept"] = 9
_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})([/.-])(\d{1,2})\2(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})[-/](\d{1,2})$")
_QUARTER = re.compile(r"^(?:q([1-4])\s*[-/ ]?\s*(\d{4})|(\d{4})\s*[-/ ]?\s*q([1-4]))$")
_YEAR = re.compile(r"^(\d{4})$")
_WORDS = re.compile(r"[a-z]+|\d+")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _plausible_year(year: int) -> bool:
    return 1970 <= year <= 2100


def parse_date(value: object, order: DateOrder = DateOrder.AUTO) -> ParsedDate:
    """Parse a release-date cell into a date and its precision.

    Supports ISO dates, numeric day/month dates, month names, quarters
    ("Q3 2027"), years, and words such as "TBA". Quarters and years are stored
    as their first day with a matching precision.
    """
    unknown = ParsedDate(None, ReleasePrecision.UNKNOWN)
    if value is None:
        return unknown
    if isinstance(value, date):  # includes datetime
        day = value if type(value) is date else date(value.year, value.month, value.day)
        return ParsedDate(day, ReleasePrecision.DAY)
    text = " ".join(unicodedata.normalize("NFKC", str(value)).strip().casefold().split())
    if not text or text in _UNKNOWN_DATE_WORDS:
        return unknown
    unreadable = ParsedDate(None, ReleasePrecision.UNKNOWN, recognized=False)

    if m := _ISO.match(text):
        parsed = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return ParsedDate(parsed, ReleasePrecision.DAY) if parsed else unreadable
    if m := _NUMERIC.match(text):
        first, separator, second, year = int(m[1]), m[2], int(m[3]), int(m[4])
        if separator == "." or first > 12:
            day_first = True
        elif second > 12:
            day_first = False
        elif first == second:
            day_first = True
        elif order is DateOrder.AUTO:
            return ParsedDate(None, ReleasePrecision.UNKNOWN, ambiguous=True)
        else:
            day_first = order is DateOrder.DAY_FIRST
        day_number, month_number = (first, second) if day_first else (second, first)
        parsed = _safe_date(year, month_number, day_number)
        return ParsedDate(parsed, ReleasePrecision.DAY) if parsed else unreadable
    if m := _YEAR_MONTH.match(text):
        parsed = _safe_date(int(m[1]), int(m[2]), 1)
        return ParsedDate(parsed, ReleasePrecision.MONTH) if parsed else unreadable
    if m := _QUARTER.match(text):
        quarter = int(m[1] or m[4])
        year = int(m[2] or m[3])
        return ParsedDate(date(year, 3 * quarter - 2, 1), ReleasePrecision.QUARTER)
    if m := _YEAR.match(text):
        year = int(m[1])
        if _plausible_year(year):
            return ParsedDate(date(year, 1, 1), ReleasePrecision.YEAR)
        return unreadable

    tokens = _WORDS.findall(text)
    months = [_MONTHS[t] for t in tokens if t in _MONTHS]
    numbers = [int(t) for t in tokens if t.isdigit()]
    others = [t for t in tokens if not t.isdigit() and t not in _MONTHS and t not in {"of"}]
    others = [t for t in others if t not in {"st", "nd", "rd", "th"}]
    if len(months) != 1 or others:
        return unreadable
    years = [n for n in numbers if n >= 1000]
    days = [n for n in numbers if n < 1000]
    if len(years) != 1 or len(days) > 1 or not _plausible_year(years[0]):
        return unreadable
    if days:
        parsed = _safe_date(years[0], months[0], days[0])
        return ParsedDate(parsed, ReleasePrecision.DAY) if parsed else unreadable
    return ParsedDate(date(years[0], months[0], 1), ReleasePrecision.MONTH)


def looks_like_formula(text: str) -> bool:
    """True if spreadsheet software could treat ``text`` as a formula."""
    return bool(text) and text[0] in "=+-@\t\r" and not _is_number(text)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
