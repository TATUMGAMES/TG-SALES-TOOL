# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Steam store discovery adapter.

What the public Steam storefront provides (checked against the live store and
its robots.txt, which does not disallow ``/api/`` or ``/search/``):

* ``/search/results/?json=1`` lists games that are coming soon or newly
  released, but only with a name and an image URL (the app id is read from
  the image URL). It is not a complete catalog.
* ``/api/featuredcategories`` returns short "Coming soon" and "New releases"
  lists.
* ``/api/appdetails`` returns, per app: type (game, DLC, demo), developers,
  publishers, release date (or "Coming soon"), genres, categories, platforms,
  languages, the official website and a support email or URL the developer
  chose to publish.

These are storefront endpoints, not the documented Steam Web API, and they
are rate limited. tg_sales therefore uses them only when the user starts a
search, at a low request rate, caches details for a day, falls back to the
cache (clearly marked as stale) when Steam is unreachable, and attributes the
data to Steam. There is no future-release catalog or contact directory: the
only contact used is the support address a developer published on its store
page.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from html import unescape
from typing import Any

from tg_sales.cancellation import CancelToken
from tg_sales.domain.discovery import (
    DiscoveryParams,
    GameCandidate,
    GameType,
    SourceResult,
)
from tg_sales.domain.enums import ReleasePrecision
from tg_sales.domain.normalization import normalize_email, normalize_url, parse_date
from tg_sales.domain.time import Clock
from tg_sales.integrations.cache import JsonFileCache
from tg_sales.integrations.http import (
    AccessDeniedError,
    HttpClient,
    RateLimitedError,
    SourceError,
)

STORE = "https://store.steampowered.com"
SEARCH_URL = f"{STORE}/search/results/"
FEATURED_URL = f"{STORE}/api/featuredcategories"
DETAILS_URL = f"{STORE}/api/appdetails"
APP_URL = f"{STORE}/app/{{app_id}}/"
SEARCH_PAGE_SIZE = 50
GAMES_CATEGORY = 998  # Steam's "Games" category (excludes software, soundtracks, …)
CACHE_TTL = timedelta(hours=24)

_APP_IN_URL = re.compile(r"/apps?/(\d{1,10})(?:/|$|\?)")
_TAGS = re.compile(r"<[^>]+>")
_UNKNOWN_WORDS = ("coming soon", "to be announced", "tba", "tbd", "when it's done")

ProgressCallback = Callable[[int, str], None]


def _strings(items: Any, key: str = "description") -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    values = [str(i.get(key, "")).strip() if isinstance(i, dict) else str(i).strip() for i in items]
    return tuple(v for v in values if v)


def _languages(text: Any) -> tuple[str, ...]:
    if not isinstance(text, str):
        return ()
    plain = unescape(_TAGS.sub("", text)).replace("*", "")
    plain = plain.split("languages with full audio support")[0]
    return tuple(part.strip() for part in plain.split(",") if part.strip())


def parse_app_details(
    app_id: str, data: dict[str, Any], fetched_at: datetime, *, stale: bool = False
) -> GameCandidate:
    """Normalize one ``appdetails`` ``data`` object."""
    kind = str(data.get("type", "")).lower()
    game_type = {"game": GameType.GAME, "dlc": GameType.DLC, "demo": GameType.DEMO}.get(
        kind, GameType.OTHER
    )
    release = data.get("release_date") or {}
    release_text = str(release.get("date") or "").strip()
    coming_soon = bool(release.get("coming_soon"))
    parsed = parse_date(release_text) if release_text else None
    if parsed is None or parsed.value is None or release_text.casefold() in _UNKNOWN_WORDS:
        release_date, precision = None, ReleasePrecision.UNKNOWN
    else:
        release_date, precision = parsed.value, parsed.precision
    if not release_text:
        release_text = "Coming soon" if coming_soon else "Not listed"
    platforms = data.get("platforms") or {}
    support = data.get("support_info") or {}
    parent = data.get("fullgame") or {}
    return GameCandidate(
        source="steam",
        external_id=app_id,
        title=str(data.get("name") or f"Steam app {app_id}").strip(),
        store_url=APP_URL.format(app_id=app_id),
        game_type=game_type,
        release_date=release_date,
        release_precision=precision,
        release_text=release_text,
        developers=tuple(d.strip() for d in data.get("developers") or [] if str(d).strip()),
        publishers=tuple(p.strip() for p in data.get("publishers") or [] if str(p).strip()),
        genres=_strings(data.get("genres")),
        categories=_strings(data.get("categories")),
        platforms=tuple(sorted(name for name, available in platforms.items() if available)),
        languages=_languages(data.get("supported_languages")),
        website=normalize_url(str(data.get("website") or "")),
        support_email=normalize_email(str(support.get("email") or "")),
        support_url=normalize_url(str(support.get("url") or "")),
        parent_external_id=str(parent.get("appid")) if parent.get("appid") else None,
        parent_title=str(parent.get("name")) if parent.get("name") else None,
        fetched_at=fetched_at,
        provenance_url=APP_URL.format(app_id=app_id),
        stale=stale,
    )


def app_ids_from_search(payload: Any) -> list[str]:
    """App ids from a store search JSON page (read from each result's image URL)."""
    ids: list[str] = []
    for item in (payload or {}).get("items", []) if isinstance(payload, dict) else []:
        match = _APP_IN_URL.search(str(item.get("logo", ""))) if isinstance(item, dict) else None
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


class SteamStoreAdapter:
    name = "steam"
    label = "Steam store"
    attribution = "Game data from the public Steam store (store.steampowered.com)."

    def __init__(
        self,
        http: HttpClient,
        cache: JsonFileCache,
        clock: Clock,
        *,
        country: str = "us",
        language: str = "english",
        cache_ttl: timedelta = CACHE_TTL,
    ) -> None:
        self._http = http
        self._cache = cache
        self._clock = clock
        self._country = country
        self._language = language
        self._ttl = cache_ttl

    def parse_reference(self, text: str) -> str | None:
        cleaned = text.strip()
        if cleaned.isdigit() and 0 < len(cleaned) <= 10:
            return cleaned
        match = re.search(r"store\.steampowered\.com/app/(\d{1,10})", cleaned)
        return match.group(1) if match else None

    # -- discovery ----------------------------------------------------------

    def _search(self, params: dict[str, Any], limit: int, token: CancelToken | None) -> list[str]:
        ids: list[str] = []
        start = 0
        while len(ids) < limit:
            page = self._http.get_json(
                SEARCH_URL,
                {
                    **params,
                    "json": 1,
                    "start": start,
                    "count": SEARCH_PAGE_SIZE,
                    "cc": self._country,
                    "l": self._language,
                },
                token,
            )
            found = app_ids_from_search(page)
            if not found:
                break
            ids.extend(i for i in found if i not in ids)
            start += SEARCH_PAGE_SIZE
        return ids[:limit]

    def candidate_ids(
        self, limit: int, token: CancelToken | None = None
    ) -> tuple[list[str], list[str]]:
        """Up to ``limit`` app ids: half coming soon, half newest releases. Returns (ids, notes)."""
        notes: list[str] = []
        upcoming = self._search(
            {"filter": "comingsoon", "category1": GAMES_CATEGORY}, (limit + 1) // 2, token
        )
        recent = self._search(
            {"sort_by": "Released_DESC", "category1": GAMES_CATEGORY}, limit // 2, token
        )
        ids = list(dict.fromkeys([*upcoming, *recent]))
        try:
            featured = self._http.get_json(
                FEATURED_URL, {"cc": self._country, "l": self._language}, token
            )
            for section in ("coming_soon", "new_releases"):
                for item in (featured.get(section) or {}).get("items", []):
                    app_id = str(item.get("id", ""))
                    if app_id.isdigit() and app_id not in ids and len(ids) < limit:
                        ids.append(app_id)
        except SourceError as exc:
            notes.append(f"Featured lists unavailable: {exc.user_message}")
        notes.append(
            "Steam search lists a selection of upcoming and newly released games; it is not a "
            "complete catalog."
        )
        return ids[:limit], notes

    def discover(
        self,
        params: DiscoveryParams,
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> SourceResult:
        if progress:
            progress(2, "Searching the Steam store…")
        ids, notes = self.candidate_ids(params.max_candidates, token)
        result = self._details(ids, token, progress, notes)
        return result

    def lookup(
        self,
        references: Sequence[str],
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> SourceResult:
        ids = list(dict.fromkeys(i for i in (self.parse_reference(r) for r in references) if i))
        return self._details(ids, token, progress, [])

    # -- details ------------------------------------------------------------

    def _fetch_details(self, app_id: str, token: CancelToken | None) -> dict[str, Any] | None:
        payload = self._http.get_json(
            DETAILS_URL, {"appids": app_id, "cc": self._country, "l": self._language}, token
        )
        entry = payload.get(app_id) if isinstance(payload, dict) else None
        if (
            not isinstance(entry, dict)
            or not entry.get("success")
            or not isinstance(entry.get("data"), dict)
        ):
            return None
        data: dict[str, Any] = entry["data"]
        return data

    def _details(
        self,
        app_ids: Iterable[str],
        token: CancelToken | None,
        progress: ProgressCallback | None,
        notes: list[str],
    ) -> SourceResult:
        queue = list(dict.fromkeys(app_ids))
        seen: set[str] = set()
        candidates: list[GameCandidate] = []
        failed: list[str] = []
        stale = 0
        stopped: SourceError | None = None
        index = 0
        while index < len(queue):
            app_id = queue[index]
            index += 1
            if app_id in seen:
                continue
            seen.add(app_id)
            if token is not None:
                token.raise_if_cancelled()
            if progress:
                progress(
                    10 + int(85 * index / max(1, len(queue))),
                    f"Reading game {index} of {len(queue)}…",
                )
            now = self._clock.now()
            cached = self._cache.get(f"steam_app_{app_id}")
            data: dict[str, Any] | None = None
            is_stale = False
            if cached is not None and now - cached.fetched_at < self._ttl:
                data, fetched_at = cached.data, cached.fetched_at
            elif stopped is None:
                try:
                    data = self._fetch_details(app_id, token)
                    fetched_at = now
                    if data is not None:
                        self._cache.put(f"steam_app_{app_id}", data, now)
                except (AccessDeniedError, RateLimitedError) as exc:
                    stopped = exc  # stop asking Steam for the rest of this run
                except SourceError:
                    pass
            if data is None and cached is not None:
                data, fetched_at, is_stale = cached.data, cached.fetched_at, True
            if data is None:
                failed.append(app_id)
                continue
            candidate = parse_app_details(app_id, data, fetched_at, stale=is_stale)
            stale += int(is_stale)
            if candidate.game_type is GameType.DEMO:
                # A demo stands for its game: look at the full game instead.
                if candidate.parent_external_id and candidate.parent_external_id not in seen:
                    queue.append(candidate.parent_external_id)
                continue
            candidates.append(candidate)
        if stopped is not None:
            notes.append(f"{stopped.user_message} {stopped.suggested_action}")
        if stale:
            notes.append(
                f"{stale} game(s) could not be refreshed and are shown from the saved copy "
                "(marked as not current)."
            )
        if failed:
            notes.append(f"{len(failed)} game(s) could not be read from Steam.")
        if progress:
            progress(100, "Done")
        return SourceResult(tuple(candidates), tuple(notes), stale, tuple(failed))
