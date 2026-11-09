# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Small JSON file cache for source responses (one file per key, written atomically)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tg_sales.domain.time import format_utc, parse_utc

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass(frozen=True)
class CacheEntry:
    data: Any
    fetched_at: datetime


class JsonFileCache:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, key: str) -> Path:
        return self._directory / f"{_SAFE.sub('_', key)}.json"

    def get(self, key: str) -> CacheEntry | None:
        path = self._path(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return CacheEntry(raw["data"], parse_utc(raw["fetched_at"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None  # missing or unreadable entries are simply refetched

    def put(self, key: str, data: Any, fetched_at: datetime) -> None:
        path = self._path(key)
        partial = path.with_name(path.name + ".partial")
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            partial.write_text(
                json.dumps(
                    {"fetched_at": format_utc(fetched_at), "data": data}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
            partial.replace(path)
        except OSError:
            partial.unlink(missing_ok=True)  # caching is best effort
