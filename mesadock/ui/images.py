"""Tk image helpers: icon extraction with an on-disk and in-memory cache."""
from __future__ import annotations

import hashlib
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

from ..core import paths as core_paths
from ..core import icons as icon_art
from ..win32 import shell


class ImageCache:
    """Keeps PhotoImage objects alive and avoids re-extracting the same icon."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._images: dict[str, ImageTk.PhotoImage] = {}
        self._pillow: dict[str, Image.Image] = {}
        self._cache_dir = cache_dir or core_paths.icons_cache_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # -- low level ---------------------------------------------------------
    def _key(self, source: str, size: int) -> str:
        digest = hashlib.sha1(source.encode("utf-8", "replace")).hexdigest()[:16]
        # The trailing version invalidates icons cached before the move to 256px
        # jumbo extraction; without it the old blurry PNGs kept being reused.
        return digest + "-" + str(size) + "-v2"

    def _disk_path(self, key: str) -> Path:
        return self._cache_dir / (key + ".png")

    def photo(self, source: str, size: int = 64) -> ImageTk.PhotoImage:
        """PhotoImage for a file path, url or known glyph name."""
        key = self._key(source, size)
        cached = self._images.get(key)
        if cached is not None:
            return cached
        image = self._paste_image(source, size, key)
        photo = ImageTk.PhotoImage(image)
        self._images[key] = photo
        self._pillow[key] = image
        return photo

    def pillow(self, source: str, size: int = 64) -> Image.Image:
        self.photo(source, size)
        return self._pillow[self._key(source, size)]

    def _paste_image(self, source: str, size: int, key: str) -> Image.Image:
        disk = self._disk_path(key)
        if disk.exists():
            try:
                with Image.open(disk) as cached:
                    return cached.convert("RGBA").resize((size, size), Image.LANCZOS)
            except (OSError, ValueError):
                pass
        image = self._render(source, size)
        try:
            icon_art.save_png(image, disk)
        except OSError:
            pass
        return image

    def _render(self, source: str, size: int) -> Image.Image:
        if source.startswith("glyph:"):
            return icon_art.dock_icon(source.split(":", 1)[1], size, item_count=0)
        path = source
        if path and Path(path).exists():
            if shell.is_image(path) and not path.lower().endswith(".ico"):
                try:
                    with Image.open(path) as opened:
                        return opened.convert("RGBA").resize((size, size), Image.LANCZOS)
                except (OSError, ValueError):
                    pass
            # Prefer the 256px jumbo icon and downscale it: asking Windows for a
            # 32px icon and enlarging it was what made panel icons look blurry.
            high_res = shell.extract_icon_jumbo(path)
            if high_res is not None:
                bbox = high_res.getbbox()
                if bbox and (bbox[2] - bbox[0] < 120 or bbox[3] - bbox[1] < 120):
                    payload = shell.extract_icon_png(path, size)
                    if payload:
                        import io
                        try:
                            with Image.open(io.BytesIO(payload)) as opened:
                                return opened.convert("RGBA").resize((size, size), Image.LANCZOS)
                        except (OSError, ValueError):
                            pass
                    try:
                        cropped = high_res.crop(bbox)
                        return cropped.convert("RGBA").resize((size, size), Image.LANCZOS)
                    except (OSError, ValueError):
                        pass
                try:
                    return high_res.convert("RGBA").resize((size, size), Image.LANCZOS)
                except (OSError, ValueError):
                    pass
            payload = shell.extract_icon_png(path, size)
            if payload:
                import io

                with Image.open(io.BytesIO(payload)) as opened:
                    return opened.convert("RGBA").resize((size, size), Image.LANCZOS)
            return icon_art.placeholder_icon(Path(path).suffix, size)
        return icon_art.placeholder_icon("", size)

    def clear(self) -> None:
        self._images.clear()
        self._pillow.clear()

    def release(self, source: str, size: int = 64) -> None:
        key = self._key(source, size)
        self._images.pop(key, None)
        self._pillow.pop(key, None)
        try:
            self._disk_path(key).unlink()
        except OSError:
            pass


def item_source(item) -> str:
    """Which file the icon of an item should be read from."""
    if getattr(item, "icon", ""):
        return item.icon
    if getattr(item, "kind", "") == "url":
        return "glyph:grid"
    # Prefer target executable over .lnk to avoid Windows shortcut arrow overlay
    if getattr(item, "target", "") and Path(item.target).exists():
        return item.target
    if getattr(item, "path", "") and Path(item.path).exists():
        return item.path
    return getattr(item, "target", "") or getattr(item, "path", "")


def folder_source(folder) -> str:
    if getattr(folder, "icon", ""):
        try:
            if Path(folder.icon).exists():
                return folder.icon
        except Exception:
            pass
    return "glyph:" + (getattr(folder, "style", "") or "grid")


def prepare_canvas(window: tk.Misc, transparent_key: str) -> None:
    """Make the window background click-through outside the drawn panel."""
    try:
        window.wm_attributes("-transparentcolor", transparent_key)
    except tk.TclError:
        pass
