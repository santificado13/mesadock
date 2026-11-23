"""Screenshot helper used by the visual checks and the docs.

Window rectangles are taken from Tk itself; MesaDock runs Per-Monitor V2 DPI
aware, so Tk coordinates are already physical screen pixels.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageGrab


def screen_scale() -> float:
    """Physical pixels per Tk pixel.

    MesaDock switches the process to Per-Monitor V2 DPI awareness before Tk
    starts, so Tk coordinates are already physical pixels and the ratio is 1.0.
    The helper stays in one place so that behaviour cannot leak into callers.
    """
    return 1.0


def window_rect(window, pad: int = 0) -> tuple[int, int, int, int]:
    """Physical-pixel rectangle of a Tk window (with optional padding)."""
    window.update_idletasks()
    scale = screen_scale()
    x = int(round(window.winfo_rootx() * scale)) - pad
    y = int(round(window.winfo_rooty() * scale)) - pad
    w = int(round(window.winfo_width() * scale)) + pad * 2
    h = int(round(window.winfo_height() * scale)) + pad * 2
    return x, y, x + max(1, w), y + max(1, h)


def grab_window(window, path: str | Path, pad: int = 4) -> Image.Image:
    """Save a screenshot of one window; returns the image."""
    left, top, right, bottom = window_rect(window, pad)
    # Docks and panels are layered windows (per-pixel alpha); a plain grab skips them.
    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True,
                           include_layered_windows=True).convert("RGB")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return image


def colour_stats(image: Image.Image, limit: int = 6) -> list[tuple[int, tuple[int, int, int]]]:
    """Most common colours, for assertions in the visual checks."""
    colours = image.convert("RGB").getcolors(maxcolors=1_000_000) or []
    colours.sort(reverse=True)
    return [(count, rgb) for count, rgb in colours[:limit]]


def has_colour(image: Image.Image, rgb: tuple[int, int, int], tolerance: int = 8) -> int:
    """Number of pixels close to rgb."""
    target = image.convert("RGB")
    data = target.tobytes()
    total = 0
    for index in range(0, len(data), 3):
        if (abs(data[index] - rgb[0]) <= tolerance
                and abs(data[index + 1] - rgb[1]) <= tolerance
                and abs(data[index + 2] - rgb[2]) <= tolerance):
            total += 1
    return total


def open_folder(path: str | Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        pass
