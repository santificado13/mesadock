"""Icon artwork: built-in dock icons and tinting.

Pure Pillow, no Tk, so the artwork can be generated and tested headlessly. The
GUI layer turns these PNGs into PhotoImages.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

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
    "portal": "lime",
}


def accent_name(folder) -> str:
    """Accent colour of a dock: the one the user picked, else the style's."""
    chosen = getattr(folder, "accent", "") or ""
    if chosen in ACCENTS:
        return chosen
    key = "portal" if getattr(folder, "portal", "") else (getattr(folder, "style", "") or "grid")
    return STYLE_COLOURS.get(key, "blue")


def accent_rgb(folder) -> tuple[int, int, int]:
    return ACCENTS[accent_name(folder)]


def _rgba(colour: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    return (colour[0], colour[1], colour[2], alpha)


def _render_tile(size: int, accent: str, style: str, opacity: float = 0.92) -> Image.Image:
    """Render a dark rounded glass tile with subtle accent styling.

    ``opacity`` (0..1) is how solid the glass is; the border and the glyph stay
    fully visible whatever it is.
    """
    opacity = max(0.0, min(1.0, float(opacity)))
    accent_rgb = ACCENTS.get(accent, ACCENTS["blue"])
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    pad = 1
    x0, y0 = pad, pad
    x1, y1 = size - 1 - pad, size - 1 - pad
    radius = max(4, int(size * 0.20))

    # Mask for rounded tile
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=255)

    # Vertical gradient: lighter at top, darker at bottom
    # Red channel shades from ~48 down to ~16 so top[0] > bottom[0]
    grad = Image.new("RGBA", (size, size))
    grad_data = []
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(48 * (1.0 - t) + 16 * t)
        g = int(54 * (1.0 - t) + 20 * t)
        b = int(72 * (1.0 - t) + 30 * t)
        # a touch more see-through at the top; 210..235 at the default 0.92
        a = int(255 * opacity * (0.895 + 0.105 * t))
        row = [(r, g, b, a)] * size
        grad_data.extend(row)
    grad.putdata(grad_data)

    # Composite base tile through mask
    base = Image.composite(grad, tile, mask)
    draw = ImageDraw.Draw(base)

    # Fine accent border, drawn after the gloss so it stays crisp
    border_width = max(1, int(size * 0.02))

    # Soft gloss: a white veil over the top third that fades out. The old inner
    # outline read as a second box drawn inside the tile.
    gloss = Image.new("L", (size, size), 0)
    gloss_rows = []
    limit = max(1, int(size * 0.42))
    for y in range(size):
        gloss_rows.extend([int(26 * (1.0 - y / limit)) if y < limit else 0] * size)
    gloss.putdata(gloss_rows)
    veil = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    veil.putalpha(ImageChops.multiply(gloss, mask))
    base = Image.alpha_composite(base, veil)
    draw = ImageDraw.Draw(base)

    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=_rgba(accent_rgb, 210), width=border_width)

    # Minimalist sleek style glyph in the center
    _draw_glyph(draw, size, style, accent_rgb)

    return base


def _draw_glyph(draw: ImageDraw.ImageDraw, size: int, style: str, colour: tuple[int, int, int]) -> None:
    """Draw a clean vector glyph representing the dock style inside the tile."""
    glyph_fill = _rgba(colour, 210)
    glyph_rim = _rgba(colour, 240)
    cx, cy = size / 2, size / 2

    if style == "grid":
        # 2x2 neat rounded tiles
        w = max(3, int(size * 0.17))
        gap = max(2, int(size * 0.07))
        total = 2 * w + gap
        top_left_x = int(cx - total / 2)
        top_left_y = int(cy - total / 2)
        r = max(1, w // 4)
        for row in range(2):
            for col in range(2):
                x = top_left_x + col * (w + gap)
                y = top_left_y + row * (w + gap)
                draw.rounded_rectangle((x, y, x + w, y + w), radius=r, fill=glyph_fill, outline=glyph_rim)

    elif style == "column":
        # 3 vertical slim cards
        w = max(3, int(size * 0.11))
        h = max(8, int(size * 0.44))
        gap = max(2, int(size * 0.06))
        total = 3 * w + 2 * gap
        top_left_x = int(cx - total / 2)
        top_left_y = int(cy - h / 2)
        r = max(1, w // 3)
        for col in range(3):
            x = top_left_x + col * (w + gap)
            draw.rounded_rectangle((x, top_left_y, x + w, top_left_y + h), radius=r, fill=glyph_fill, outline=glyph_rim)

    elif style == "row":
        # 3 horizontal slim cards
        w = max(8, int(size * 0.44))
        h = max(3, int(size * 0.11))
        gap = max(2, int(size * 0.06))
        total = 3 * h + 2 * gap
        top_left_x = int(cx - w / 2)
        top_left_y = int(cy - total / 2)
        r = max(1, h // 3)
        for row in range(3):
            y = top_left_y + row * (h + gap)
            draw.rounded_rectangle((top_left_x, y, top_left_x + w, y + h), radius=r, fill=glyph_fill, outline=glyph_rim)

    elif style == "fan":
        # Sleek 3-card fan / arc rays
        r = max(6, int(size * 0.22))
        draw.arc((cx - r, cy - r, cx + r, cy + r), start=210, end=330, fill=glyph_rim, width=max(2, int(size * 0.04)))
        r2 = max(3, int(size * 0.12))
        draw.arc((cx - r2, cy - r2, cx + r2, cy + r2), start=210, end=330, fill=glyph_fill, width=max(2, int(size * 0.04)))
        dot_r = max(2, int(size * 0.04))
        draw.ellipse((cx - dot_r, cy + int(r * 0.4) - dot_r, cx + dot_r, cy + int(r * 0.4) + dot_r), fill=glyph_rim)

    elif style == "ring":
        # Sleek concentric orbit rings
        r1 = max(6, int(size * 0.22))
        draw.ellipse((cx - r1, cy - r1, cx + r1, cy + r1), outline=glyph_rim, width=max(1, int(size * 0.03)))
        dot_r = max(2, int(size * 0.07))
        draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=glyph_fill)

    elif style == "portal":
        # Folder silhouette: a tab on top of a rounded body
        w = max(12, int(size * 0.50))
        h = max(9, int(size * 0.34))
        x0, y0 = int(cx - w / 2), int(cy - h / 2 + size * 0.03)
        tab_w, tab_h = int(w * 0.42), max(3, int(size * 0.08))
        r = max(2, int(size * 0.05))
        draw.rounded_rectangle((x0, y0 - tab_h, x0 + tab_w, y0 + r), radius=r, fill=glyph_rim)
        draw.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=r, fill=glyph_fill, outline=glyph_rim)

    else:
        # Default dot cluster
        r = max(4, int(size * 0.18))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=glyph_rim, width=max(1, int(size * 0.03)))


def dock_icon(style: str, size: int = 64, accent: str | None = None, item_count: int = 0,
              dock_index: int = 1, opacity: float = 0.92) -> Image.Image:
    """Return a modern translucent glass dock icon, badged when item_count > 0.

    ``dock_index`` is accepted for older callers and no longer drawn.
    """
    colour = accent or STYLE_COLOURS.get(style, "blue")
    # Pillow shapes are not anti-aliased: draw the tile larger and reduce it.
    scale = 4 if size <= 96 else (3 if size <= 160 else 2)
    image = _render_tile(size * scale, colour, style, opacity).resize((size, size), Image.LANCZOS)
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
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                 fill=_rgba(ACCENTS.get(accent, ACCENTS["blue"]), 240),
                 outline=(255, 255, 255, 180), width=1)
    label = str(count) if count < 100 else "99+"
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(size=max(8, int(size * 0.18)))
    except Exception:
        font = None
    box = draw.textbbox((0, 0), label, font=font)
    draw.text((cx - (box[2] - box[0]) / 2, cy - (box[3] - box[1]) / 2 - box[1]), label,
              fill=(12, 14, 18, 255), font=font)
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
    draw.rounded_rectangle((size * 0.16, size * 0.1, size * 0.84, size * 0.9),
                           radius=int(size * 0.08), fill=(245, 247, 250, 240))
    draw.rounded_rectangle((size * 0.16, size * 0.1, size * 0.84, size * 0.9),
                           radius=int(size * 0.08), outline=(120, 132, 148, 200), width=max(1, size // 40))
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
