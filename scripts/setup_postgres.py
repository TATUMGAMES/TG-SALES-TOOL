# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Download and unpack the portable PostgreSQL runtime into ``runtime/postgresql``.

Uses the official EnterpriseDB Windows binaries (zip, no installer, no
administrator rights). The download is verified against a pinned SHA-256
before anything is extracted. Only the server and client programs are kept
(pgAdmin, StackBuilder, headers and documentation are skipped).

    python scripts/setup_postgres.py [--zip path\\to\\downloaded.zip]
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "18.4-1"
URL = f"https://get.enterprisedb.com/postgresql/postgresql-{VERSION}-windows-x64-binaries.zip"
SHA256 = "7effe34c0bf89027b3f171447d351cbc460f4566c8d0f643daec67f140787858"
TARGET = ROOT / "runtime" / "postgresql"
SKIP = ("pgsql/pgAdmin 4/", "pgsql/StackBuilder/", "pgsql/symbols/", "pgsql/doc/", "pgsql/include/")


def say(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(target: Path) -> None:
    say(f"Downloading PostgreSQL {VERSION} (about 340 MB)...")
    partial = target.with_suffix(".partial")
    with urllib.request.urlopen(URL, timeout=60) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    partial.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, help="use an already downloaded zip")
    args = parser.parse_args()
    if (TARGET / "bin" / "pg_ctl.exe").is_file():
        say(f"PostgreSQL is already installed in {TARGET}.")
        return 0
    downloads = ROOT / "runtime" / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = args.zip or downloads / f"postgresql-{VERSION}-windows-x64-binaries.zip"
    if not archive.is_file():
        download(archive)
    say("Checking the download...")
    if sha256(archive) != SHA256:
        say("The PostgreSQL download is damaged or not the expected file. Delete it and try again.")
        return 1
    staging = TARGET.with_name("postgresql.partial")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            name = info.filename
            unsafe = ".." in name or not name.startswith("pgsql/") or name.startswith(SKIP)
            if info.is_dir() or unsafe:
                continue
            out = staging / name[len("pgsql/") :]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zipped.read(info))
    staging.replace(TARGET)
    say(f"PostgreSQL {VERSION} is ready in {TARGET}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
