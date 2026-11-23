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
        # v3: dock glyphs were redrawn in the redesign; drop renders of the old art.
        # v4: tiles are anti-aliased and lost the inner outline.
        return digest + "-" + str(size) + "-v4"

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
            # "glyph:<style>" or "glyph:<style>:<accent>"
            parts = source.split(":")
            return icon_art.dock_icon(parts[1], size, accent=parts[2] if len(parts) > 2 else None, item_count=0)
        path = source
        if path and Path(path).exists():
            if path.lower().endswith(".ico"):
                # Pillow opens an .ico at its largest size, sharper than asking
                # Windows for the shell icon of the file.
                try:
                    with Image.open(path) as opened:
                        return opened.convert("RGBA").resize((size, size), Image.LANCZOS)
                except (OSError, ValueError):
                    pass
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

    def forget(self, source: str) -> None:
        """Drop every cached render of ``source``, at all sizes, memory and disk.

        Needed when a file is replaced in place (a new custom icon saved under the
        same name): the cache is keyed by path, so it would keep the old picture.
        """
        prefix = self._key(source, 0).split("-", 1)[0] + "-"
        for key in [k for k in self._images if k.startswith(prefix)]:
            self._images.pop(key, None)
            self._pillow.pop(key, None)
        try:
            for cached in self._cache_dir.glob(prefix + "*.png"):
                cached.unlink()
        except OSError:
            pass

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
    path = getattr(item, "path", "") or ""
    if getattr(item, "kind", "") == "url":
        # A web link shows the default browser's icon: the dock glyph made it look
        # like a nested dock, and Windows often gives a .url file a blank page.
        return shell.default_browser_icon() or "glyph:grid"
    # A shortcut that names its own icon keeps it. Web apps installed by Chrome or
    # Edge point at a proxy exe with a blank icon, and their artwork lives in that
    # .ico; reading the exe instead lost the icon once the shortcut was docked.
    if path.lower().endswith(".lnk") and Path(path).exists():
        icon, index = shell.shortcut_icon_location(path)
        if icon:
            if icon.lower().endswith(".ico") or index == 0:
                return icon
            return path  # icon at another index of an exe/dll: let Windows resolve it
    # Otherwise prefer the target executable over the .lnk, which avoids the
    # shortcut arrow overlay.
    if getattr(item, "target", "") and Path(item.target).exists():
        return item.target
    if getattr(item, "path", "") and Path(item.path).exists():
        return item.path
    return getattr(item, "target", "") or getattr(item, "path", "")


def folder_source(folder) -> str:
    icon = getattr(folder, "icon", "") or ""
    # dock_custom_<id>.png files were generated automatically by older builds
    # (numbered artwork); they are not a user choice, so use the built-in glyph.
    if icon and not Path(icon).name.startswith("dock_custom_"):
        try:
            if Path(icon).exists():
                return icon
        except Exception:
            pass
    glyph = "portal" if getattr(folder, "portal", "") else (getattr(folder, "style", "") or "grid")
    accent = getattr(folder, "accent", "") or ""
    return "glyph:" + glyph + (":" + accent if accent in icon_art.ACCENTS else "")


def prepare_canvas(window: tk.Misc, transparent_key: str) -> None:
    """Make the window background click-through outside the drawn panel."""
    try:
        window.wm_attributes("-transparentcolor", transparent_key)
    except tk.TclError:
        pass
