# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Company branding: name, accent color and images, with safe image handling.

An uploaded raster image is never stored as-is. It is checked (size, real
decoded format, pixel dimensions, decompression-bomb limit), decoded,
downscaled and re-encoded as a fresh PNG in the user's assets folder, which
strips metadata and anything that is not pixel data. An SVG is accepted only
when it is self-contained and has nothing active in it (see
:func:`sanitize_svg`); it is served only as an image with a restrictive
Content-Security-Policy.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from tg_sales.db.database import Database
from tg_sales.domain.enums import SettingScope
from tg_sales.errors import TgSalesError
from tg_sales.repositories.settings import SettingsRepository

logger = logging.getLogger(__name__)

LOGO_FILENAME = "company_logo.png"
ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "BMP", "WEBP"})
MAX_LOGO_FILE_BYTES = 5 * 1024 * 1024
MAX_LOGO_DIMENSION = 4096
STORED_LOGO_MAX_DIMENSION = 512
LOGO_REQUIREMENTS_TEXT = "PNG, JPEG, BMP or WebP, up to 5 MB and 4096 x 4096 pixels."


class LogoError(TgSalesError):
    """The selected logo image cannot be used."""


def _reject(message: str, detail: str | None = None) -> LogoError:
    return LogoError(
        message, action=f"Choose a different image file ({LOGO_REQUIREMENTS_TEXT})", detail=detail
    )


def sanitize_image(
    data: bytes,
    *,
    max_bytes: int,
    max_dimension: int,
    allowed: frozenset[str] = ALLOWED_FORMATS,
    target_max: int | None = None,
) -> tuple[bytes, int, int]:
    """Validate ``data`` and return it re-encoded as PNG with its width and height."""
    if not data:
        raise _reject("The image file is empty.")
    if len(data) > max_bytes:
        raise _reject("The image file is too large.")
    Image.MAX_IMAGE_PIXELS = max_dimension * max_dimension
    try:
        with Image.open(io.BytesIO(data)) as probe:
            image_format = probe.format or ""
            width, height = probe.size
            probe.verify()
        if image_format not in allowed:
            raise _reject(f"{image_format or 'This'} images are not supported.")
        if width > max_dimension or height > max_dimension or width < 1 or height < 1:
            raise _reject("The image is too large (in pixels).")
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            converted = image.convert("RGBA")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise _reject("The file is not a readable image.", repr(exc)) from exc
    if target_max is not None:
        converted.thumbnail((target_max, target_max))
    output = io.BytesIO()
    converted.save(output, format="PNG", optimize=True)
    return output.getvalue(), converted.width, converted.height


class LogoStore:
    """The company logo in the user's writable assets folder."""

    def __init__(self, assets_dir: Path) -> None:
        self._assets_dir = assets_dir

    @property
    def path(self) -> Path:
        return self._assets_dir / LOGO_FILENAME

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, data: bytes) -> Path:
        png, _w, _h = sanitize_image(
            data,
            max_bytes=MAX_LOGO_FILE_BYTES,
            max_dimension=MAX_LOGO_DIMENSION,
            target_max=STORED_LOGO_MAX_DIMENSION,
        )
        try:
            self._assets_dir.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_suffix(".partial")
            partial.write_bytes(png)
            partial.replace(self.path)
        except OSError as exc:
            raise LogoError(
                "The logo could not be saved.",
                action="Check that the disk is not full and the data folder is writable.",
                detail=repr(exc),
            ) from exc
        logger.info("Company logo updated")
        return self.path

    def read(self) -> bytes | None:
        """The stored logo, or None when missing or damaged (the app shows its own icon)."""
        try:
            data = self.path.read_bytes()
            sanitize_image(
                data,
                max_bytes=MAX_LOGO_FILE_BYTES,
                max_dimension=MAX_LOGO_DIMENSION,
                allowed=frozenset({"PNG"}),
            )
        except (OSError, LogoError):
            return None
        return data

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)


# ----------------------------------------------------------------------------------
# Company branding: name, accent color and images (logo, compact logo, favicon)
# ----------------------------------------------------------------------------------
#
# Branding belongs to one installation (like the other application settings), so
# the settings are device-scoped and the images live in the data folder's
# ``assets`` directory, never in the program folder or the built web app. They
# survive restarts, updates and rebuilds; in Docker the data folder is the
# ``/data`` volume. The software license and its notices are separate and are
# not affected by branding.

DEFAULT_COMPANY_NAME = "Tatum Games"
BRANDING_KEY = "branding"
MAX_COMPANY_NAME = 80
MAX_SVG_BYTES = 512 * 1024
BRANDING_REQUIREMENTS_TEXT = (
    "PNG, JPEG, WebP or BMP up to 5 MB and 4096 x 4096 pixels, or a simple SVG up to "
    "512 KB without scripts or external links."
)


class ImageSlot(StrEnum):
    LOGO = "logo"  # sidebar and menu
    COMPACT_LOGO = "compact_logo"  # small spaces: the phone header
    FAVICON = "favicon"  # browser tab


_SLOT_PNG = {
    ImageSlot.LOGO: LOGO_FILENAME,  # same file as before, so existing logos keep working
    ImageSlot.COMPACT_LOGO: "company_logo_compact.png",
    ImageSlot.FAVICON: "favicon.png",
}
_SLOT_SIZE = {ImageSlot.LOGO: 512, ImageSlot.COMPACT_LOGO: 256, ImageSlot.FAVICON: 64}

_SVG_BLOCKED_ELEMENTS = frozenset(
    {
        "script",
        "foreignobject",
        "iframe",
        "object",
        "embed",
        "audio",
        "video",
        "canvas",
        "handler",
        "listener",
        "animate",
        "animatemotion",
        "animatetransform",
        "set",
        "a",
    }
)
_SAFE_DATA_IMAGE = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[a-z0-9+/=\s]*$", re.I)
_CSS_DANGER = re.compile(r"@import|javascript:|expression\s*\(|url\s*\(\s*['\"]?(?!#)", re.I)


def sanitize_svg(data: bytes) -> bytes:
    """Return ``data`` if it is a self-contained SVG with nothing active in it.

    Anything that could run code or load other content is refused rather than
    removed: scripts, event handlers (``on…``), embedded HTML, animations that
    can change links, links to other files or sites, document type
    declarations and entities. The file is also only ever shown through an
    image element with a restrictive Content-Security-Policy, where browsers
    do not run scripts anyway.
    """
    if not data:
        raise _reject("The image file is empty.")
    if len(data) > MAX_SVG_BYTES:
        raise _reject("The SVG file is too large.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _reject("The SVG file is not readable text.") from exc
    if re.search(r"<!\s*(doctype|entity)", text, re.I):
        raise _reject("SVG files with document type declarations are not accepted.")
    try:
        root = ElementTree.fromstring(text)  # noqa: S314 - no DTD/entities (checked above)
    except ElementTree.ParseError as exc:
        raise _reject("The file is not a valid SVG image.", repr(exc)) from exc

    def local(name: str) -> str:
        return name.rsplit("}", 1)[-1].lower()

    if local(root.tag) != "svg":
        raise _reject("The file is not an SVG image.")
    for element in root.iter():
        tag = local(element.tag)
        if tag in _SVG_BLOCKED_ELEMENTS:
            raise _reject(f"SVG images with <{tag}> elements are not accepted.")
        if tag == "style" and _CSS_DANGER.search(element.text or ""):
            raise _reject("The SVG's styles load other content.")
        for name, value in element.attrib.items():
            attribute = local(name)
            if attribute.startswith("on"):
                raise _reject("SVG images with event handlers are not accepted.")
            if attribute == "href" and not (
                value.startswith("#") or _SAFE_DATA_IMAGE.match(value.strip())
            ):
                raise _reject("SVG images that link to other files or sites are not accepted.")
            if attribute == "style" and _CSS_DANGER.search(value):
                raise _reject("The SVG's styles load other content.")
            if "javascript:" in value.lower():
                raise _reject("SVG images with scripts are not accepted.")
    return data


def _contrast_text(color: str) -> str:
    """Black or white text, whichever reads better on ``color`` (#rrggbb)."""
    red, green, blue = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
    return "#1a1320" if luminance > 0.4 else "#ffffff"


class BrandingSettings(BaseModel):
    """The installation's visible company branding (not the software's license)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME)
    accent_color: str | None = Field(default=None, pattern=r"^#[0-9a-f]{6}$")

    @field_validator("company_name", mode="before")
    @classmethod
    def _clean_name(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split()) or None
        return value

    @field_validator("accent_color", mode="before")
    @classmethod
    def _clean_color(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() or None
        return value

    @property
    def display_name(self) -> str:
        return self.company_name or DEFAULT_COMPANY_NAME

    @property
    def accent_text_color(self) -> str | None:
        return _contrast_text(self.accent_color) if self.accent_color else None


@dataclass(frozen=True)
class StoredImage:
    slot: ImageSlot
    media_type: str  # image/png or image/svg+xml
    data: bytes
    version: str  # changes whenever the image changes (for browser caching)


class BrandingStore:
    """Branding images in the data folder's assets directory."""

    def __init__(self, assets_dir: Path) -> None:
        self._assets_dir = assets_dir

    def _png(self, slot: ImageSlot) -> Path:
        return self._assets_dir / _SLOT_PNG[slot]

    def _svg(self, slot: ImageSlot) -> Path:
        return self._png(slot).with_suffix(".svg")

    def save(self, slot: ImageSlot, data: bytes) -> None:
        """Validate and store an image; SVG is checked, everything else re-encoded as PNG."""
        head = data[:512].lstrip().lower()
        is_svg = head.startswith((b"<", b"\xef\xbb\xbf<")) and b"<svg" in data[:4096].lower()
        if is_svg:
            content, target, other = sanitize_svg(data), self._svg(slot), self._png(slot)
        else:
            content, _w, _h = sanitize_image(
                data,
                max_bytes=MAX_LOGO_FILE_BYTES,
                max_dimension=MAX_LOGO_DIMENSION,
                target_max=_SLOT_SIZE[slot],
            )
            target, other = self._png(slot), self._svg(slot)
        try:
            self._assets_dir.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(target.suffix + ".partial")
            partial.write_bytes(content)
            partial.replace(target)
            other.unlink(missing_ok=True)
        except OSError as exc:
            raise LogoError(
                "The image could not be saved.",
                action="Check that the disk is not full and the data folder is writable.",
                detail=repr(exc),
            ) from exc
        logger.info("Branding image updated", extra={"context": {"slot": slot.value}})

    def read(self, slot: ImageSlot) -> StoredImage | None:
        """The stored image, or None when missing or damaged (the default is shown)."""
        for path, media_type in (
            (self._svg(slot), "image/svg+xml"),
            (self._png(slot), "image/png"),
        ):
            try:
                data = path.read_bytes()
                if media_type == "image/svg+xml":
                    sanitize_svg(data)
                else:
                    sanitize_image(
                        data,
                        max_bytes=MAX_LOGO_FILE_BYTES,
                        max_dimension=MAX_LOGO_DIMENSION,
                        allowed=frozenset({"PNG"}),
                    )
            except (OSError, LogoError):
                continue
            version = hashlib.sha256(data).hexdigest()[:16]
            return StoredImage(slot, media_type, data, version)
        return None

    def remove(self, slot: ImageSlot) -> None:
        self._png(slot).unlink(missing_ok=True)
        self._svg(slot).unlink(missing_ok=True)


class BrandingService:
    """Company name, accent color and images of this installation."""

    def __init__(self, database: Database, store: BrandingStore) -> None:
        self._database = database
        self.store = store

    def get(self) -> BrandingSettings:
        with self._database.session() as session:
            raw = SettingsRepository(session).get(BRANDING_KEY, SettingScope.DEVICE)
        if not isinstance(raw, dict):
            return BrandingSettings()
        try:
            return BrandingSettings.model_validate(raw)
        except ValidationError:
            return BrandingSettings()

    def update(self, changes: dict[str, object]) -> BrandingSettings:
        current = self.get().model_dump()
        try:
            updated = BrandingSettings.model_validate({**current, **changes})
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first.get("loc", ()))
            raise TgSalesError(
                f"The branding setting “{field}” is not valid.",
                action="Use a company name of up to 80 characters and a color like #6f4f8a.",
            ) from exc
        with self._database.session() as session:
            SettingsRepository(session).set(
                BRANDING_KEY, updated.model_dump(mode="json"), SettingScope.DEVICE
            )
        return updated

    def reset(self) -> BrandingSettings:
        """Restore the default name, color and images (uploaded images are removed)."""
        for slot in ImageSlot:
            self.store.remove(slot)
        with self._database.session() as session:
            SettingsRepository(session).set(BRANDING_KEY, {}, SettingScope.DEVICE)
        return BrandingSettings()
