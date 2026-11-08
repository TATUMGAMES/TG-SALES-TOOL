"""Render the web app's PNG icons from the app icon design (brand palette bars)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "icons"
# (x, y, width, height) on a 64-unit grid, as in the SVG icon.
BARS = [
    ((12, 34, 8, 18), "#86c4c2"),
    ((24, 26, 8, 26), "#c7d47f"),
    ((36, 18, 8, 34), "#f6d271"),
    ((48, 10, 6, 42), "#d87b7a"),
]


def icon(size: int, *, maskable: bool = False) -> Image.Image:
    scale = 4  # draw large, then downsample for smooth edges
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    unit = big / 64
    if maskable:  # full-bleed background, content inside the 80% safe zone
        draw.rectangle((0, 0, big, big), fill="#a787bd")
        offset, unit = big * 0.1, big * 0.8 / 64
    else:
        offset = 0.0
        draw.rounded_rectangle(
            (2 * unit, 2 * unit, 62 * unit, 62 * unit), 14 * unit, fill="#a787bd"
        )
    for (x, y, w, h), color in BARS:
        box = (
            offset + x * unit,
            offset + y * unit,
            offset + (x + w) * unit,
            offset + (y + h) * unit,
        )
        draw.rounded_rectangle(box, 2 * unit, fill=color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192).save(OUT / "icon-192.png")
    icon(512).save(OUT / "icon-512.png")
    icon(512, maskable=True).save(OUT / "icon-maskable-512.png")
    apple = Image.new("RGBA", (180, 180), "#a787bd")
    apple.alpha_composite(icon(180, maskable=True))
    apple.convert("RGB").save(OUT / "apple-touch-icon.png")


if __name__ == "__main__":
    main()
