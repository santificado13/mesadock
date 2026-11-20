from __future__ import annotations

import io
import os
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from . import paths

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


def _get_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    font_size = max(8, int(size * 0.35))
    for font_name in ("arialbd.ttf", "arial.ttf", "consola.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(font_name, font_size)
        except (OSError, IOError):
            pass
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for font_name in ("arialbd.ttf", "arial.ttf", "consola.ttf"):
        font_path = Path(windir) / "Fonts" / font_name
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), font_size)
            except (OSError, IOError):
                pass
    return ImageFont.load_default()


def dock_icon(
    style: str,
    size: int = 64,
    accent: str | None = None,
    item_count: int = 0,
    dock_index: int = 1,
) -> Image.Image:
    caminho_foto = paths.asset("molde_limpo.png")
    if not caminho_foto.exists():
        caminho_foto = paths.asset("mesadock.png")

    if caminho_foto.exists():
        try:
            base_img = Image.open(caminho_foto).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            graus = ((dock_index - 1) * 60) % 360 if dock_index > 0 else random.randint(0, 359)
            r, g, b, a = base_img.split()
            img_hsv = Image.merge("RGB", (r, g, b)).convert("HSV")
            h, s, v = img_hsv.split()
            shift = int((graus / 360.0) * 255)
            h = h.point(lambda p: (p + shift) % 256)
            img_rgb = Image.merge("HSV", (h, s, v)).convert("RGB")
            r2, g2, b2 = img_rgb.split()
            final_img = Image.merge("RGBA", (r2, g2, b2, a))
        except Exception:
            final_img = Image.new("RGBA", (size, size), (20, 20, 30, 255))
    else:
        final_img = Image.new("RGBA", (size, size), (20, 20, 30, 255))

    draw = ImageDraw.Draw(final_img)

    # Selo no canto superior direito
    bx = size * 0.85
    by = size * 0.16

    font = _get_font(size)
    cor_texto = (255, 255, 255, 255)
    draw.text((bx, by), str(dock_index), fill=cor_texto, font=font, anchor="mm")

    return final_img


def self_badge(size: int, count: int, accent: str) -> Image.Image:
    return Image.new("RGBA", (size, size), (0, 0, 0, 0))


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
    folder = Path(directory)
    produced: dict[str, Path] = {}
    for style in ("grid", "column", "row", "fan", "ring"):
        path = folder / f"dock-{style}.png"
        if not path.exists():
            save_png(dock_icon(style, size, dock_index=1), path)
        produced[style] = path
    return produced
