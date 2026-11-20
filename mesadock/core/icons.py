"""Icon artwork: built-in dock icons and tinting.

Pure Pillow, no Tk, so the artwork can be generated and tested headlessly. The
GUI layer turns these PNGs into PhotoImages.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ACCENTS = {
    "blue": (94, 162, 255),
    "teal": (45, 212, 191),
    "violet": (139, 122, 255),
    "amber": (251, 191, 36),
    "rose": (244, 114, 182),
    "lime": (163, 230, 53),
    "slate": (148, 163, 184),
}

STYLE_COLOURS = {
    "grid": "blue",
    "column": "teal",
    "row": "violet",
    "fan": "amber",
    "ring": "rose",
}


def _rgba(colour: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    return (colour[0], colour[1], colour[2], alpha)


def _background(size: int, accent: str) -> Image.Image:
    """Use the high-resolution logo/dock artwork directly."""
    try:
        from .paths import asset
        path = asset("logo.png")
        if path.exists():
            with Image.open(path) as img:
                return img.convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        pass
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return base


def _mini_tiles(draw: ImageDraw.ImageDraw, size: int, count: int, accent: str) -> None:
    """A few item tiles hinting at the contents of the dock."""
    colour = ACCENTS.get(accent, ACCENTS["blue"])
    tile = int(size * 0.17)
    gap = int(size * 0.06)
    cols = 2 if count > 1 else 1
    rows = max(1, (count + cols - 1) // cols)
    total_w = cols * tile + (cols - 1) * gap
    total_h = rows * tile + (rows - 1) * gap
    left = (size - total_w) // 2
    top = (size - total_h) // 2 + int(size * 0.02)
    for index in range(count):
        row, col = divmod(index, cols)
        x = left + col * (tile + gap)
        y = top + row * (tile + gap)
        draw.rounded_rectangle((x, y, x + tile, y + tile), radius=max(2, tile // 4), fill=_rgba(colour, 190))
        draw.rounded_rectangle((x, y, x + tile, y + tile), radius=max(2, tile // 4), outline=(255, 255, 255, 90))


def dock_icon(style: str, size: int = 64, accent: str | None = None, item_count: int = 0) -> Image.Image:
    """Return the logo artwork, with a count badge in the corner when ``item_count`` > 0."""
    colour = accent or STYLE_COLOURS.get(style, "blue")
    image = _background(size, colour)
    if item_count > 0:
        image = Image.alpha_composite(image, self_badge(size, item_count, colour))
    return image


def self_badge(size: int, count: int, accent: str) -> Image.Image:
    """Small count badge drawn in the corner of a dock icon."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    radius = max(6, int(size * 0.16))
    cx = size - radius - max(1, int(size * 0.03))
    cy = size - radius - max(1, int(size * 0.03))
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=_rgba(ACCENTS.get(accent, ACCENTS["blue"]), 240))
    label = str(count) if count < 100 else "99+"
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(size=max(8, int(size * 0.18)))
    except Exception:
        font = None
    box = draw.textbbox((0, 0), label, font=font)
    draw.text((cx - (box[2] - box[0]) / 2, cy - (box[3] - box[1]) / 2 - box[1]), label, fill=(12, 14, 18, 255), font=font)
    return layer


def default_image(style: str, size: int = 64) -> Image.Image:
    return dock_icon(style, size)


def save_png(image: Image.Image, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")
    return target


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def tint_icon(image: Image.Image, colour: tuple[int, int, int], strength: float = 0.35) -> Image.Image:
    """Blend a colour into the opaque pixels of an icon."""
    overlay = Image.new("RGBA", image.size, _rgba(colour, int(255 * max(0.0, min(1.0, strength)))))
    return Image.alpha_composite(image, overlay)


def placeholder_icon(extension: str, size: int = 64) -> Image.Image:
    """Neutral icon for documents that do not yield a shell icon."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((size * 0.16, size * 0.1, size * 0.84, size * 0.9), radius=int(size * 0.08), fill=(245, 247, 250, 240))
    draw.rounded_rectangle((size * 0.16, size * 0.1, size * 0.84, size * 0.9), radius=int(size * 0.08), outline=(120, 132, 148, 200), width=max(1, size // 40))
    label = (extension or "file").replace(".", "").upper()[:4]
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(size=max(8, int(size * 0.22)))
    except Exception:
        font = None
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(((size - (box[2] - box[0])) / 2, size * 0.5), label, fill=(70, 82, 100, 255), font=font)
    return image


def ensure_default_assets(directory: str | Path, size: int = 256) -> dict[str, Path]:
    """Write the built-in dock icons once; returns style -> path."""
    folder = Path(directory)
    produced: dict[str, Path] = {}
    for style in ("grid", "column", "row", "fan", "ring"):
        path = folder / ("dock-" + style + ".png")
        if not path.exists():
            save_png(dock_icon(style, size, item_count=0), path)
        produced[style] = path
    return produced
