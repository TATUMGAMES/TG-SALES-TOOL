# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Add (or check) the Apache 2.0 copyright header in original source files.

Usage::

    python scripts/license_headers.py          # add missing headers
    python scripts/license_headers.py --check  # list files without one; exit 1 if any

Only original source files get a header: Python, TypeScript/TSX, JavaScript,
CSS and PowerShell under ``src``, ``tests``, ``scripts`` and ``web``. Generated
files (``web/src/lib/api-types.ts``), templates, dependencies, lock files,
data, fixtures that are not code, and binary assets are never touched. Files
that already carry a copyright or license notice (for example third-party
code) are left exactly as they are.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NOTICE_LINES = (
    "Copyright 2013-present Tatum Games, LLC.",
    "",
    'Licensed under the Apache License, Version 2.0 (the "License"); you may not',
    "use this file except in compliance with the License. You may obtain a copy",
    "of the License at: https://www.apache.org/licenses/LICENSE-2.0",
    "",
    "Unless required by applicable law or agreed to in writing, software",
    'distributed under the License is distributed on an "AS IS" BASIS, WITHOUT',
    "WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
)

SOURCE_DIRS = ("src", "tests", "scripts", "web/src", "web/e2e", "web/public")
ROOT_FILES = ("web/vite.config.ts", "web/playwright.config.ts")
HASH_COMMENT = {".py", ".ps1"}
BLOCK_COMMENT = {".ts", ".tsx", ".js", ".mjs", ".css"}
SKIP_PARTS = {"node_modules", "dist", "__pycache__", ".venv", "fixtures", "test-results"}
GENERATED = {"web/src/lib/api-types.ts"}
MARKERS = ("copyright", "licensed under", "spdx-license-identifier")


def header_for(suffix: str) -> str:
    if suffix in HASH_COMMENT:
        return "".join(f"# {line}".rstrip() + "\n" for line in NOTICE_LINES) + "\n"
    body = "".join(f" * {line}".rstrip() + "\n" for line in NOTICE_LINES)
    return f"/*\n{body} */\n\n"


def candidates() -> list[Path]:
    files: list[Path] = [ROOT / name for name in ROOT_FILES]
    for directory in SOURCE_DIRS:
        files += [p for p in (ROOT / directory).rglob("*") if p.is_file()]
    result = []
    for path in sorted(set(files)):
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix not in HASH_COMMENT | BLOCK_COMMENT or relative in GENERATED:
            continue
        if SKIP_PARTS & set(path.relative_to(ROOT).parts):
            # Fixture *generators* are code; fixture data is not.
            if not (path.suffix == ".py" and "fixtures" in path.parts):
                continue
            if {"node_modules", "dist", "__pycache__", ".venv"} & set(path.parts):
                continue
        result.append(path)
    return result


def has_notice(text: str) -> bool:
    head = text[:1500].lower()
    return any(marker in head for marker in MARKERS)


def with_header(path: Path, text: str) -> str:
    header = header_for(path.suffix)
    lines = text.splitlines(keepends=True)
    keep: list[str] = []
    # Keep a shebang or encoding line first, as the interpreter requires.
    while lines and (lines[0].startswith("#!") or lines[0].startswith("# -*-")):
        keep.append(lines.pop(0))
    return "".join(keep) + header + "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only report missing headers")
    args = parser.parse_args()
    missing = []
    for path in candidates():
        text = path.read_text(encoding="utf-8")
        if not text.strip() or has_notice(text):
            continue
        missing.append(path)
        if not args.check:
            path.write_text(with_header(path, text), encoding="utf-8", newline="")
    for path in missing:
        action = "missing header" if args.check else "added header"
        sys.stdout.write(f"{action}: {path.relative_to(ROOT).as_posix()}\n")
    return 1 if args.check and missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
