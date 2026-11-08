"""Find public business contact addresses on a studio's official website.

Runs only when the user asks for it. It reads the site's robots.txt and
respects it, then reads the home page and at most a couple of pages on the
same site whose links mention contact, press, business or legal information.
Only addresses that actually appear on those pages (mailto links or written
addresses) are returned, each with the page it came from; nothing is guessed,
and every result still needs verification by the salesperson.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from tg_sales.cancellation import CancelToken
from tg_sales.domain.normalization import normalize_email, normalize_url
from tg_sales.integrations.http import USER_AGENT, HttpClient, SourceError

MAX_EXTRA_PAGES = 2
MAX_RESULTS = 5
_LINK = re.compile(
    r"<a\b[^>]*href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL
)
_MAILTO = re.compile(r"mailto:([^\"'?>\s]+)", re.IGNORECASE)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_KEYWORDS = ("contact", "press", "business", "impressum", "imprint", "legal", "about", "media")
_IGNORED_LOCAL = ("noreply", "no-reply", "donotreply", "example", "privacy", "abuse")
_FILE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


@dataclass(frozen=True)
class FoundAddress:
    email: str
    source_url: str


@dataclass(frozen=True)
class ContactSearch:
    website: str
    addresses: tuple[FoundAddress, ...]
    checked_urls: tuple[str, ...]
    blocked_by_robots: bool = False
    message: str = ""


def _visible_text(html: str) -> str:
    return unescape(_TAG.sub(" ", _SCRIPT.sub(" ", html)))


def extract_addresses(html: str) -> list[str]:
    """Email addresses written on a page (mailto links first), normalized and filtered."""
    found: list[str] = []
    for raw in [*_MAILTO.findall(html), *_EMAIL.findall(_visible_text(html))]:
        email = normalize_email(unescape(raw))
        if email is None or email in found:
            continue
        local = email.split("@", 1)[0]
        if any(word in local for word in _IGNORED_LOCAL) or email.endswith(_FILE_SUFFIXES):
            continue
        found.append(email)
    return found


def candidate_pages(html: str, base_url: str) -> list[str]:
    """Same-site links whose address or text suggests contact or business information."""
    host = urlsplit(base_url).hostname
    pages: list[str] = []
    for href, text in _LINK.findall(html):
        if href.lower().startswith(("mailto:", "javascript:", "tel:")):
            continue
        url = normalize_url(urljoin(base_url, href.strip()))
        if url is None or urlsplit(url).hostname != host or url in pages or url == base_url:
            continue
        label = f"{href} {_visible_text(text)}".casefold()
        if any(word in label for word in _KEYWORDS):
            pages.append(url)
    return pages[:MAX_EXTRA_PAGES]


class WebsiteContactFinder:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def _robots(self, website: str, token: CancelToken | None) -> RobotFileParser:
        parts = urlsplit(website)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            response = self._http.get(robots_url, token=token, allow_status=(404, 410))
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
        except SourceError:
            parser.parse([])  # robots.txt unreachable: proceed only if the pages themselves load
        return parser

    def find(self, website: str, token: CancelToken | None = None) -> ContactSearch:
        url = normalize_url(website)
        if url is None:
            return ContactSearch(website, (), (), message="The website address is not valid.")
        robots = self._robots(url, token)
        if not robots.can_fetch(USER_AGENT, url):
            return ContactSearch(
                url,
                (),
                (),
                blocked_by_robots=True,
                message="The website does not allow automated reading.",
            )
        checked: list[str] = []
        addresses: list[FoundAddress] = []
        pages = [url]
        index = 0
        while index < len(pages):
            page = pages[index]
            index += 1
            if not robots.can_fetch(USER_AGENT, page):
                continue
            try:
                response = self._http.get(page, token=token)
            except SourceError as exc:
                if index == 1:
                    return ContactSearch(url, (), tuple(checked), message=exc.user_message)
                continue
            if "html" not in response.headers.get("content-type", "html"):
                continue
            checked.append(page)
            html = response.text
            for email in extract_addresses(html):
                if all(a.email != email for a in addresses):
                    addresses.append(FoundAddress(email, page))
            if index == 1:
                pages.extend(candidate_pages(html, page))
        site_domain = (urlsplit(url).hostname or "").removeprefix("www.")
        # Addresses on the studio's own domain first.
        addresses.sort(key=lambda a: not a.email.endswith("@" + site_domain))
        message = "" if addresses else "No business email address is published on these pages."
        return ContactSearch(url, tuple(addresses[:MAX_RESULTS]), tuple(checked), message=message)
