"""Company logo storage with safe image handling.

An uploaded image is never stored as-is. It is checked (size, real decoded
format, pixel dimensions, decompression-bomb limit), decoded, downscaled and
re-encoded as a fresh PNG in the user's assets folder, which strips metadata
and anything that is not pixel data. SVG is not accepted (it can contain
scripts).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from tg_sales.errors import TgSalesError

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
