"""Pillow drawing helpers for the per-pixel-alpha windows (docks and panels).

Everything here is plain image work, no Tk: anti-aliased shapes, soft shadows
and text. Pillow draws shapes without anti-aliasing, so they are rendered
larger and scaled down.
"""
from __future__ import annotations

import functools
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SUPERSAMPLE = 3
_FONT_FILES = {
    "normal": ("segoeui.ttf", "arial.ttf"),
    "semibold": ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"),
    "bold": ("segoeuib.ttf", "arialbd.ttf"),
}


def rgba(colour, alpha: int = 255) -> tuple[int, int, int, int]:
    """(r, g, b, a) from "#rrggbb" or an (r, g, b) tuple."""
    if isinstance(colour, str):
        value = colour.lstrip("#")
        colour = (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    return (int(colour[0]), int(colour[1]), int(colour[2]), max(0, min(255, int(alpha))))


def mix(first, second, amount: float) -> tuple[int, int, int]:
    a, b = rgba(first), rgba(second)
    return tuple(int(round(a[i] + (b[i] - a[i]) * amount)) for i in range(3))  # type: ignore[return-value]


@functools.lru_cache(maxsize=64)
def font(pixels: int, weight: str = "normal") -> ImageFont.ImageFont:
    """Segoe UI at a pixel size, falling back to Pillow's built-in font."""
    folder = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in _FONT_FILES.get(weight, _FONT_FILES["normal"]):
        for candidate in (os.path.join(folder, name), name):
            try:
                return ImageFont.truetype(candidate, max(6, int(pixels)))
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=max(6, int(pixels)))
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def points_to_pixels(points: float, dpi: float = 96.0) -> int:
    return max(6, int(round(points * dpi / 72.0)))


def text_width(text: str, face: ImageFont.ImageFont) -> int:
    return int(round(face.getlength(text or "")))


def fit_text(text: str, face: ImageFont.ImageFont, available: int) -> str:
    """Shorten ``text`` with an ellipsis until it fits ``available`` pixels."""
    text = (text or "").strip()
    if not text or text_width(text, face) <= available:
        return text
    shortened = text
    while shortened and text_width(shortened + "\u2026", face) > available:
        shortened = shortened[:-1]
    return (shortened.rstrip() + "\u2026") if shortened else "\u2026"


def shape(size: tuple[int, int], painter, scale: int = SUPERSAMPLE) -> Image.Image:
    """Run ``painter(draw, scale)`` on a canvas ``scale`` times larger and
    reduce it, which is what gives the edges their anti-aliasing."""
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    big = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    painter(ImageDraw.Draw(big), scale)
    return big.resize((width, height), Image.LANCZOS)


def rounded(size: tuple[int, int], box, radius: float, fill=None, outline=None, width: float = 1) -> Image.Image:
    """Anti-aliased rounded rectangle on a transparent layer of ``size``."""
    def painter(draw: ImageDraw.ImageDraw, s: int) -> None:
        x0, y0, x1, y1 = (v * s for v in box)
        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=max(0, radius * s), fill=fill,
                               outline=outline, width=max(1, int(round(width * s))) if outline else 0)

    return shape(size, painter)


def ellipse(size: tuple[int, int], box, fill=None, outline=None, width: float = 1) -> Image.Image:
    def painter(draw: ImageDraw.ImageDraw, s: int) -> None:
        x0, y0, x1, y1 = (v * s for v in box)
        draw.ellipse((x0, y0, x1 - 1, y1 - 1), fill=fill, outline=outline,
                     width=max(1, int(round(width * s))) if outline else 0)

    return shape(size, painter)


def shadow(size: tuple[int, int], box, radius: float, blur: float = 10, offset: tuple[int, int] = (0, 4),
           opacity: int = 110, round_shape: bool = False) -> Image.Image:
    """Soft drop shadow of a rounded rectangle (or an ellipse) on its own layer."""
    layer = Image.new("RGBA", (max(1, int(size[0])), max(1, int(size[1]))), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    moved = (x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1])
    if round_shape:
        draw.ellipse(moved, fill=(0, 0, 0, opacity))
    else:
        draw.rounded_rectangle(moved, radius=radius, fill=(0, 0, 0, opacity))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def outer_shadow(size: tuple[int, int], box, radius: float, blur: float = 10, offset: tuple[int, int] = (0, 4),
                 opacity: int = 110, round_shape: bool = False) -> Image.Image:
    """Like :func:`shadow`, but only outside the shape that casts it.

    Under a translucent card the shadow would show through and darken it, by a
    different amount for each shape, so the same opacity setting looked different
    on a card and on a disc. Cutting the shape out keeps the card exactly as
    translucent as asked.
    """
    layer = shadow(size, box, radius, blur, offset, opacity, round_shape)
    if round_shape:
        cut = ellipse(layer.size, box, fill=(255, 255, 255, 255))
    else:
        cut = rounded(layer.size, box, radius, fill=(255, 255, 255, 255))
    layer.putalpha(ImageChops.subtract(layer.getchannel("A"), cut.getchannel("A")))
    return layer


def paste_centre(target: Image.Image, picture: Image.Image, centre: tuple[float, float]) -> None:
    """Alpha-composite ``picture`` centred on a point of ``target``, in place."""
    if picture.mode != "RGBA":
        picture = picture.convert("RGBA")
    left = int(round(centre[0] - picture.width / 2))
    top = int(round(centre[1] - picture.height / 2))
    if left >= target.width or top >= target.height or left + picture.width <= 0 or top + picture.height <= 0:
        return
    target.alpha_composite(picture, (max(0, left), max(0, top)),
                           (max(0, -left), max(0, -top)))


def draw_text(target: Image.Image, position: tuple[float, float], text: str, face: ImageFont.ImageFont,
              fill, anchor: str = "mm", halo=None) -> None:
    """Draw ``text``; ``halo`` (a colour) adds a thin outline around the letters,
    which keeps them readable on a see-through panel over a busy wallpaper."""
    if not text:
        return
    draw = ImageDraw.Draw(target)
    if halo is not None:
        # On a layer just big enough for this text: blurring one the size of the
        # whole panel for every name made a 60-item panel take most of a second.
        margin = 4
        left, top, right, bottom = draw.textbbox(position, text, font=face, anchor=anchor, stroke_width=2)
        left, top = int(left) - margin, int(top) - margin
        layer = Image.new("RGBA", (int(right) - left + margin, int(bottom) - top + margin), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((position[0] - left, position[1] - top), text, font=face, fill=halo,
                                   anchor=anchor, stroke_width=2, stroke_fill=halo)
        layer = layer.filter(ImageFilter.GaussianBlur(0.8))
        if left < target.width and top < target.height and left + layer.width > 0 and top + layer.height > 0:
            target.alpha_composite(layer, (max(0, left), max(0, top)), (max(0, -left), max(0, -top)))
    draw.text(position, text, font=face, fill=fill, anchor=anchor)


def tint(picture: Image.Image, colour, strength: float = 0.6) -> Image.Image:
    """Recolour an icon towards ``colour`` keeping its shading and transparency.

    The icon is reduced to its brightness and that is mapped onto the colour, then
    mixed with the original: every icon of a dock ends up in the same hue.
    """
    picture = picture.convert("RGBA")
    alpha = picture.getchannel("A")
    grey = picture.convert("L")
    target = rgba(colour)
    dark = mix(target, (0, 0, 0), 0.72)
    light = mix(target, (255, 255, 255), 0.82)
    channels = []
    for index in range(3):
        low, mid, high = dark[index], target[index], light[index]
        table = [int(low + (mid - low) * v / 128) if v < 128 else int(mid + (high - mid) * (v - 128) / 127)
                 for v in range(256)]
        channels.append(grey.point(table))
    coloured = Image.merge("RGB", channels).convert("RGBA")
    blended = Image.blend(picture, coloured, max(0.0, min(1.0, strength)))
    blended.putalpha(alpha)
    return blended
