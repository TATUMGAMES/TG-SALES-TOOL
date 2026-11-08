"""Sync package files: writing, safe reading, hashing and optional encryption.

A package is a ZIP named ``tg_sales_sync_<person>_<YYYYMMDDTHHMMSSZ>_<shortid>.zip``:

* ``manifest.json`` — format and schema version, export id, source computer,
  creation time, record counts and a SHA-256 for every data file.
* ``changes/<table>.jsonl`` — one JSON object per changed record:
  ``{"id", "change_id", "history": [...], "row": {...}}``.

Encrypted packages hold ``manifest.json`` (without record details) and
``payload.bin``: the inner ZIP sealed with AES-256-GCM, the key derived from
the passphrase with scrypt. The export id is bound into the encryption as
associated data, so a payload cannot be swapped between packages.

Reading is defensive: only expected member names are accepted (no absolute
paths, no ``..``, no duplicates), compressed and uncompressed sizes and the
compression ratio are limited (ZIP bombs), and every hash must match.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from tg_sales.errors import TgSalesError

FORMAT = "tg_sales_sync"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
PAYLOAD = "payload.bin"
CHANGES_DIR = "changes/"
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_MEMBER_RATIO = 200
MAX_MEMBERS = 64
SCRYPT_N = 2**15
MIN_PASSPHRASE = 10
_MEMBER = re.compile(r"^changes/[a-z_]{1,64}\.jsonl$")


class PackageError(TgSalesError):
    """A sync package is unsafe, damaged, incompatible or cannot be decrypted."""


def _bad(message: str, detail: str | None = None) -> PackageError:
    return PackageError(
        message,
        action="Ask your colleague to export a new package and send it again through a "
        "company-approved channel.",
        detail=detail,
    )


@dataclass
class PackageContents:
    manifest: dict[str, Any]
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    sha256: str = ""


def person_slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-").lower()
    return (slug or "user")[:24]


def _derive(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=8, p=1).derive(passphrase.encode("utf-8"))


def _aad(export_id: str) -> bytes:
    return f"{FORMAT}:v{FORMAT_VERSION}:{export_id}".encode()


def build_zip(manifest: dict[str, Any], records: dict[str, list[dict[str, Any]]]) -> bytes:
    """The plain package: data files plus a manifest listing their hashes."""
    files: dict[str, bytes] = {}
    for table, rows in records.items():
        if rows:
            lines = (json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
            files[f"{CHANGES_DIR}{table}.jsonl"] = ("\n".join(lines) + "\n").encode("utf-8")
    manifest = {
        **manifest,
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for name, data in files.items()
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def seal(inner: bytes, manifest: dict[str, Any], passphrase: str) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE:
        raise PackageError(
            f"The passphrase must have at least {MIN_PASSPHRASE} characters.",
            action="Choose a longer passphrase and share it with your colleague separately.",
        )
    salt, nonce = os.urandom(16), os.urandom(12)
    sealed = AESGCM(_derive(passphrase, salt)).encrypt(nonce, inner, _aad(manifest["export_id"]))
    outer_manifest = {
        key: manifest[key]
        for key in ("format", "format_version", "export_id", "created_at_utc", "schema_revision")
    }
    outer_manifest["encrypted"] = {
        "cipher": "AES-256-GCM",
        "kdf": "scrypt",
        "n": SCRYPT_N,
        "r": 8,
        "p": 1,
        "salt": salt.hex(),
        "nonce": nonce.hex(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(MANIFEST, json.dumps(outer_manifest, indent=2))
        archive.writestr(PAYLOAD, sealed)
    return buffer.getvalue()


def write_package(path: Path, data: bytes) -> Path:
    partial = path.with_name(path.name + ".partial")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(data)
        partial.replace(path)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise PackageError(
            "The sync package could not be saved.",
            action="Choose a folder you can write to, with enough free space.",
            detail=repr(exc),
        ) from exc
    return path


def _open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise _bad("This file is not a tg_sales sync package (it is not a valid ZIP).") from exc
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise _bad("The sync package contains too many files.")
    names: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        if name in names:
            raise _bad("The sync package contains duplicate files.")
        names.add(name)
        if name not in (MANIFEST, PAYLOAD) and not _MEMBER.fullmatch(name):
            raise _bad("The sync package contains unexpected files.", detail=name)
        if info.flag_bits & 0x1:
            raise _bad("The sync package uses ZIP passwords, which tg_sales does not use.")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise _bad("The sync package is too large when unpacked.")
        if info.compress_size and info.file_size / info.compress_size > MAX_MEMBER_RATIO:
            raise _bad("The sync package is suspiciously compressed and was refused.")
    if MANIFEST not in names:
        raise _bad("The sync package has no manifest.")
    return archive


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    with archive.open(info) as handle:
        data = handle.read(info.file_size + 1)
    if len(data) != info.file_size:
        raise _bad("The sync package is damaged.", detail=f"size mismatch in {name}")
    return data


def _manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(_read_member(archive, MANIFEST))
    except (ValueError, zipfile.BadZipFile) as exc:
        raise _bad("The sync package's manifest is damaged.") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise _bad("This file is not a tg_sales sync package.")
    version = manifest.get("format_version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise PackageError(
            "This sync package was made by a newer version of tg_sales.",
            action="Install the latest tg_sales release, then import the package again.",
        )
    return manifest


def read_package(path: Path, passphrase: str | None = None) -> PackageContents:
    try:
        size = path.stat().st_size
        if size > MAX_PACKAGE_BYTES:
            raise _bad("The sync package is too large.")
        data = path.read_bytes()
    except OSError as exc:
        raise _bad("The sync package could not be read.", detail=repr(exc)) from exc
    return read_package_bytes(data, passphrase)


def read_package_bytes(data: bytes, passphrase: str | None = None) -> PackageContents:
    digest = hashlib.sha256(data).hexdigest()
    archive = _open_zip(data)
    manifest = _manifest(archive)
    encryption = manifest.get("encrypted")
    if isinstance(encryption, dict):
        if not passphrase:
            raise PackageError(
                "This sync package is encrypted.",
                action="Enter the passphrase your colleague gave you.",
            )
        try:
            if not 2**10 <= int(encryption["n"]) <= 2**20 or int(encryption["r"]) > 16:
                raise _bad("The package's encryption settings are not supported.")
            key = Scrypt(
                salt=bytes.fromhex(str(encryption["salt"])),
                length=32,
                n=int(encryption["n"]),
                r=int(encryption["r"]),
                p=int(encryption["p"]),
            ).derive(passphrase.encode("utf-8"))
            inner = AESGCM(key).decrypt(
                bytes.fromhex(str(encryption["nonce"])),
                _read_member(archive, PAYLOAD),
                _aad(str(manifest["export_id"])),
            )
        except InvalidTag as exc:
            raise PackageError(
                "The passphrase is wrong, or the package was changed after it was made.",
                action="Check the passphrase with your colleague and try again.",
            ) from exc
        except (KeyError, ValueError) as exc:
            raise _bad("The package's encryption details are damaged.") from exc
        contents = read_package_bytes(inner)
        contents.sha256 = digest
        contents.manifest["encrypted"] = True
        return contents

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise _bad("The sync package's manifest is incomplete.")
    records: dict[str, list[dict[str, Any]]] = {}
    for name in archive.namelist():
        if name == MANIFEST:
            continue
        expected = files.get(name)
        content = _read_member(archive, name)
        if not isinstance(expected, dict) or hashlib.sha256(content).hexdigest() != expected.get(
            "sha256"
        ):
            raise _bad("The sync package is damaged (a file does not match its checksum).", name)
        table = name[len(CHANGES_DIR) : -len(".jsonl")]
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(content.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError as exc:
                raise _bad("The sync package is damaged.", f"{name}:{number}") from exc
            if not isinstance(item, dict):
                raise _bad("The sync package is damaged.", f"{name}:{number}")
            rows.append(item)
        records[table] = rows
    missing = set(files) - set(archive.namelist())
    if missing:
        raise _bad(
            "The sync package is incomplete (files are missing).", ", ".join(sorted(missing))
        )
    manifest["encrypted"] = False
    return PackageContents(manifest, records, digest)
