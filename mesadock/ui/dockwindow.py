"""One collapsed dock on the desktop: a single icon that fans out on hover."""
from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageFilter, ImageTk

from ..core import icons as icon_art
from ..core import layout as layout_mod
from ..core.models import DockFolder
from ..win32 import layered
from . import paint, theme
from .images import ImageCache, folder_source, prepare_canvas

ICON_PAD = 8
DRAG_THRESHOLD = 5
LABEL_PILL = "#121722"
LABEL_PILL_HOVER = "#1b2333"
DROP_GREEN = "#34d399"


class DockWindow:
    """The always-present, single-icon face of a dock."""

    def __init__(self, app, folder: DockFolder) -> None:
        self._drop_highlight = False
        self.app = app
        self.folder = folder
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._reassert_job = None
        self._watch_job = None
        self._moved = False
        self._click_job: str | None = None
        self._hover = False
        self._hidden = False
        self._photos: list[ImageTk.PhotoImage] = []
        self._drop_target = None
        # None = not tried yet, True = per-pixel alpha works, False = colour-key fallback
        self._layered: bool | None = None
        self._image: Image.Image | None = None
        size = self._pixel_size()
        self.window = tk.Toplevel(app.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", False)
        self.window.configure(bg=theme.TRANSPARENT_KEY)
        x, y = self.position()
        self.window.geometry(str(size) + "x" + str(size) + "+" + str(x) + "+" + str(y))
        self.canvas = tk.Canvas(self.window, width=size, height=size, bg=theme.TRANSPARENT_KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._bind()
        self._draw()
        self.app.root.after(30, self._place_on_desktop)
        self.app.root.after(80, self._ensure_on_desktop)
        self.app.root.after(900, self._watch_desktop_layer)

    # -- geometry ----------------------------------------------------------
    def _pixel_size(self) -> int:
        scale = getattr(self.app.monitor_for(self.position()), "scale", 1.0) or 1.0
        icon = self.folder.icon_size or self.app.store.settings.icon_size
        return int(max(48, min(160, round(icon * scale)))) + ICON_PAD * 2

    def position(self) -> tuple[int, int]:
        if self.folder.position:
            return int(self.folder.position[0]), int(self.folder.position[1])
        monitor = self.app.primary_monitor()
        size = self.folder.icon_size or self.app.store.settings.icon_size
        x = monitor.work[0] + 24
        y = monitor.work[1] + 24 + size
        return int(x), int(y)

    def rect(self) -> tuple[int, int, int, int]:
        try:
            return (self.window.winfo_rootx(), self.window.winfo_rooty(),
                    self.window.winfo_width(), self.window.winfo_height())
        except tk.TclError:
            x, y = self.position()
            size = self._pixel_size()
            return x, y, size, size

    def move_to(self, x: int, y: int, snap: bool = True) -> None:
        if snap and self.app.store.settings.snap_to_grid:
            monitor = self.app.monitor_for((x, y))
            x, y = layout_mod.snap_to_grid(x, y, monitor.rect, self.app.icon_cell(monitor))
            x, y = layout_mod.clamp_to_monitor((x, y, self._pixel_size(), self._pixel_size()), monitor.rect)
        self.window.geometry("+" + str(int(x)) + "+" + str(int(y)))
        self.folder.position = (int(x), int(y))
        self.app.root.after(10, self._ensure_on_desktop)
        self.app.touch()

    def _place_on_desktop(self) -> None:
        """Layer the dock like a desktop icon, unless the user opted out."""
        self._register_drops()
        if self._hidden:
            # sit_above_desktop shows the window (SWP_SHOWWINDOW); a dock hidden by
            # the user came back on screen 30 ms after it was created or refreshed.
            return
        if not self._on_desktop_layer():
            self._set_topmost(True)
            return
        try:
            hwnd = int(self.window.winfo_id())
        except tk.TclError:
            return
        from ..win32 import desktop

        self._set_topmost(False)
        desktop.apply_desktop_window_styles(hwnd)
        desktop.sit_above_desktop(hwnd)

    def _register_drops(self) -> None:
        self.app.register_drop_target(
            self.window,
            lambda paths: self.app.add_paths_to_dock(self.folder.id, paths),
        )

    def _set_topmost(self, topmost: bool) -> None:
        try:
            self.window.attributes("-topmost", bool(topmost))
            if topmost:
                self.window.lift()
        except tk.TclError:
            pass

    def _on_desktop_layer(self) -> bool:
        """Docks sit behind windows unless that is off or Peek is showing them."""
        return bool(self.app.store.settings.attach_to_desktop) and not getattr(self.app, "peek_active", False)

    def apply_layer(self) -> None:
        """Re-apply the z-order after Peek was turned on or off."""
        if not self._hidden:
            self._ensure_on_desktop()

    def set_hidden(self, hidden: bool) -> None:
        """Take the dock off the desktop, or bring it back, without closing it."""
        if hidden == self._hidden:
            return
        self._hidden = hidden
        try:
            if hidden:
                self.window.withdraw()
            else:
                self.window.deiconify()
                self._draw()
                self._ensure_on_desktop()
        except tk.TclError:
            pass

    def _ensure_on_desktop(self) -> None:
        if self._reassert_job is not None:
            try:
                self.app.root.after_cancel(self._reassert_job)
            except tk.TclError:
                pass
            self._reassert_job = None
        self._reassert_step(0)

    def _reassert_step(self, step: int) -> None:
        self._reassert_job = None
        if not self.is_alive() or self._hidden:
            return
        if self._on_desktop_layer():
            self._set_topmost(False)
            try:
                hwnd = int(self.window.winfo_id())
            except tk.TclError:
                return
            from ..win32 import desktop

            desktop.sit_above_desktop(hwnd)
        else:
            self._set_topmost(True)
        if step < 3:
            self._reassert_job = self.app.root.after(
                120, lambda: self._reassert_step(step + 1)
            )

    def _watch_desktop_layer(self) -> None:
        self._watch_job = None
        if not self.is_alive():
            return
        try:
            from ..win32 import desktop

            if (
                self._on_desktop_layer()
                and not self._hidden
                and desktop.desktop_enabled()
            ):
                try:
                    hwnd = int(self.window.winfo_id())
                except tk.TclError:
                    hwnd = 0
                if hwnd and desktop.needs_reanchor(hwnd):
                    desktop.sit_above_desktop(hwnd)
        except Exception:
            pass
        self._watch_job = self.app.root.after(700, self._watch_desktop_layer)

    # -- drawing -----------------------------------------------------------
    def set_drop_highlight(self, active: bool) -> None:
        """Show the green ring while a shortcut is dragged over this dock."""
        if self._drop_highlight == active:
            return
        self._drop_highlight = active
        self._draw()

    def _draw(self) -> None:
        """Compose the dock as one RGBA picture and hand it to Windows.

        The picture has real per-pixel alpha (see win32.layered), so the tile,
        its shadow and the name blend with any wallpaper without the ragged
        edges a colour-keyed Tk canvas produced.
        """
        size = self._pixel_size()
        width = self._dock_width()
        label = self._label_text()
        label_height = self._label_height() if label else 0
        height = size + label_height
        self._resize_window(width, height)
        self._show(self._compose(width, height, size, label, label_height))

    def _compose(self, width: int, height: int, size: int, label: str, label_height: int) -> Image.Image:
        accent = icon_art.accent_rgb(self.folder)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        icon_size = size - ICON_PAD * 2
        cx, cy = width / 2, size / 2
        # Alpha 1 (invisible) over the tile's column keeps it clickable as one
        # block down to the name, so the pointer does not flicker between them.
        # The empty sides stay at alpha 0: with a long name the window is much
        # wider than the tile, and it must not swallow clicks meant for the
        # desktop icons next to it.
        image.paste((0, 0, 0, 1), (int(cx - size / 2), 0, int(cx + size / 2), height))
        tile = (cx - icon_size / 2, cy - icon_size / 2, cx + icon_size / 2, cy + icon_size / 2)

        if self._drop_highlight:
            image.alpha_composite(paint.rounded(
                (width, size), (1, 1, width - 1, size - 1), 14,
                fill=paint.rgba(DROP_GREEN, 70), outline=paint.rgba(DROP_GREEN, 255), width=2))
        elif self._hover:
            image.alpha_composite(paint.rounded(
                (width, size), (tile[0] - 3, tile[1] - 3, tile[2] + 3, tile[3] + 3), icon_size * 0.24,
                fill=paint.rgba(accent, 46), outline=paint.rgba(accent, 150), width=1))

        cache: ImageCache = self.app.images
        try:
            icon = cache.pillow(folder_source(self.folder), icon_size).convert("RGBA")
        except Exception:
            icon = None
        if icon is not None:
            # Shadow in the shape of the icon itself, so custom artwork gets one too.
            silhouette = Image.new("RGBA", (width, size), (0, 0, 0, 0))
            dark = Image.new("RGBA", icon.size, (0, 0, 0, 0))
            dark.putalpha(icon.getchannel("A").point(lambda v: int(v * 0.42)))
            paint.paste_centre(silhouette, dark, (cx, cy + max(2, icon_size * 0.05)))
            image.alpha_composite(silhouette.filter(ImageFilter.GaussianBlur(max(2.0, icon_size * 0.05))))
            paint.paste_centre(image, icon, (cx, cy))

        count = len(self.folder.items)
        if count:
            badge = self._badge_image(count, size)
            inset = ICON_PAD // 2
            image.alpha_composite(badge, (max(0, int(width - inset - 4 - badge.width)), inset + 4))

        if label:
            face = self._label_face()
            text = paint.fit_text(label, face, max(10, width - 18))
            text_w = paint.text_width(text, face)
            pill_h = label_height - 4
            half_w = min(width - 2, text_w + 16) / 2
            centre_y = size + label_height / 2
            pill_fill = paint.mix(LABEL_PILL_HOVER, accent, 0.10) if self._hover else paint.rgba(LABEL_PILL)[:3]
            image.alpha_composite(paint.rounded(
                (width, height), (cx - half_w, centre_y - pill_h / 2, cx + half_w, centre_y + pill_h / 2),
                pill_h / 2, fill=paint.rgba(pill_fill, 228),
                outline=paint.rgba(accent, 170) if self._hover else None, width=1))
            paint.draw_text(image, (cx, centre_y - 1), text, face, paint.rgba("#f5f7fb"))
        return image

    def _dpi(self) -> float:
        """DPI of the monitor the dock is on (Tk only knows the primary one)."""
        return 96.0 * float(getattr(self.app.monitor_for(self.position()), "scale", 1.0) or 1.0)

    def _label_face(self):
        return paint.font(paint.points_to_pixels(9, self._dpi()), "semibold")

    def _show(self, image: Image.Image) -> None:
        self._image = image
        if self._layered is not False:
            try:
                self.window.update_idletasks()
                shown = layered.present(int(self.window.winfo_id()), image)
            except tk.TclError:
                return
            if shown:
                self._layered = True
                return
            self._layered = False
            prepare_canvas(self.window, theme.TRANSPARENT_KEY)
        # Fallback: the same picture on the canvas, see-through by colour key.
        backdrop = Image.new("RGBA", image.size, paint.rgba(theme.TRANSPARENT_KEY))
        solid = image.copy()
        solid.putalpha(image.getchannel("A").point(lambda v: 255 if v >= 96 else 0))
        backdrop.alpha_composite(solid)
        photo = ImageTk.PhotoImage(backdrop)
        self._photos = [photo]
        self.canvas.delete("all")
        self.canvas.configure(bg=theme.TRANSPARENT_KEY)
        self.canvas.create_image(0, 0, image=photo, anchor="nw")

    def _label_font(self):
        return ("Segoe UI Semibold", 9)

    def _label_text(self) -> str:
        name = (self.folder.name or "").strip()
        if not name:
            return ""
        # Measured with the font the name is painted in, at this monitor's DPI.
        return paint.fit_text(name, self._label_face(), self._label_space())

    def _label_space(self) -> int:
        """Pixels available for the name inside the dock window."""
        return max(24, self._dock_width() - 18)

    def _label_width(self) -> int:
        name = (self.folder.name or "").strip()
        size = self._pixel_size()
        if not name:
            return size
        # Text + pill padding (2 x 8px) + a little margin, so names are not cut
        return int(min(max(size, paint.text_width(name, self._label_face()) + 22), size * 2.8))

    def _dock_width(self) -> int:
        return max(self._pixel_size(), self._label_width())

    def _label_height(self) -> int:
        return int(22 * (getattr(self.app.monitor_for(self.position()), "scale", 1.0) or 1.0))

    def _resize_window(self, width: int, height: int) -> None:
        try:
            x, y = self.position()
            current_h = self.window.winfo_height()
            if current_h == height and self.window.winfo_width() == width:
                return
            self.canvas.configure(height=height, width=width)
            self.window.geometry(str(int(width)) + "x" + str(int(height)) + "+" + str(int(x)) + "+" + str(int(y)))
        except tk.TclError:
            pass

    def _badge_image(self, count: int, size: int) -> Image.Image:
        diameter = max(18, int(size * 0.30))
        # self_badge draws the circle in the corner of a square layer; crop to the
        # circle before scaling, or the whole layer shrinks it to a dot.
        layer = icon_art.self_badge(diameter * 6, count, icon_art.accent_name(self.folder))
        box = layer.getbbox()
        if box:
            layer = layer.crop(box)
        return layer.resize((diameter, diameter), Image.LANCZOS)

    def refresh(self) -> None:
        """Re-read the dock (style, icon, item count) and redraw."""
        self._draw()
        self.app.root.after(10, self._place_on_desktop)
        self.app.root.after(60, self._ensure_on_desktop)

    # -- interaction -------------------------------------------------------
    def _bind(self) -> None:
        canvas = self.canvas
        canvas.bind("<Enter>", self._on_enter)
        canvas.bind("<Leave>", self._on_leave)
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_motion)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Button-3>", self._on_context)
        canvas.bind("<Double-Button-1>", self._on_double_click)

    def _on_enter(self, _event) -> None:
        self._hover = True
        self._draw()
        self.app.pointer_entered_dock(self)

    def _on_leave(self, _event) -> None:
        self._hover = False
        self._draw()
        self.app.pointer_left_dock(self)

    def _on_press(self, event) -> None:
        self._drag_origin = (event.x_root, event.y_root,
                             self.window.winfo_rootx(), self.window.winfo_rooty())
        self._moved = False
        self.app.dock_pressed(self)

    def _on_motion(self, event) -> None:
        if self._drag_origin is None:
            return
        dx = event.x_root - self._drag_origin[0]
        dy = event.y_root - self._drag_origin[1]
        if abs(dx) > DRAG_THRESHOLD or abs(dy) > DRAG_THRESHOLD:
            self._moved = True
        self.window.geometry("+" + str(self._drag_origin[2] + dx) + "+" + str(self._drag_origin[3] + dy))

    def _on_release(self, _event) -> None:
        if self._drag_origin is None:
            return
        if self._moved:
            x = self.window.winfo_rootx()
            y = self.window.winfo_rooty()
            self.move_to(x, y, snap=True)
            self.app.close_panels(except_dock=self.folder.id)
        else:
            if self._click_job is not None:
                try:
                    self.app.root.after_cancel(self._click_job)
                except tk.TclError:
                    pass
            self._click_job = self.app.root.after(200, lambda: self.app.toggle_panel(self.folder))
        self._drag_origin = None

    def _on_double_click(self, _event) -> None:
        if self._click_job is not None:
            try:
                self.app.root.after_cancel(self._click_job)
            except tk.TclError:
                pass
            self._click_job = None
        self.app.open_manager(select=self.folder.id)

    def _on_context(self, event) -> None:
        self.app.show_dock_menu(self.folder, event.x_root, event.y_root)

    # -- lifetime ----------------------------------------------------------
    def destroy(self) -> None:
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def is_alive(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def contains_point(self, x: int, y: int) -> bool:
        if self._hidden:
            return False
        left, top, width, height = self.rect()
        return left <= x < left + width and top <= y < top + height
