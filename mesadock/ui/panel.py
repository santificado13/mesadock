"""The expanding panel that a dock fans out into.

One Toplevel per open panel, drawn on a single canvas: a rounded dark card
with the dock's items laid out by core.layout. Items highlight on hover and
launch on click; the panel closes itself when the pointer leaves both the panel
and its dock icon.
"""
from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
import logging
from typing import Callable

from PIL import ImageTk

from ..core import layout as layout_mod
from ..core.models import DockFolder, DockItem
from ..core.i18n import tr
from ..win32 import desktop
from . import theme
from .images import ImageCache, folder_source, item_source, prepare_canvas

LAUNCH_ICON = 40


def _classify_kind(target: str, kind: str = "") -> str:
    target_clean = (target or "").strip().lower()
    if target_clean.startswith(("http://", "https://", "ftp://", "mailto:")) or kind == "url":
        return tr("Web")
    if kind == "folder":
        return tr("Folder")
    if target_clean.endswith((".exe", ".lnk")) or kind == "app":
        return tr("App")
    if target_clean.endswith((".bat", ".cmd", ".ps1", ".py", ".vbs")):
        return tr("Script")
    return tr("File")


class Panel:
    """Expanded view of one dock."""

    def __init__(
        self,
        app,
        folder: DockFolder,
        anchor_rect: tuple[int, int, int, int],
        monitor,
        on_launch: Callable[[DockFolder, DockItem], None] | None = None,
        on_edit: Callable[[DockFolder, str], None] | None = None,
        on_menu: Callable[[DockFolder, DockItem, int, int], None] | None = None,
        on_close: Callable[["Panel"], None] | None = None,
    ) -> None:
        self.app = app
        self.folder = folder
        self.monitor = monitor
        self.on_launch = on_launch
        self.on_edit = on_edit
        self.on_menu = on_menu
        self.on_close = on_close
        self.window: tk.Toplevel | None = None
        self.canvas: tk.Canvas | None = None
        self.layout = None
        self._hover_index = -1
        self._closing = False
        self._anim_job: str | None = None
        self._hovered_items: list[tuple[int, int, int, int]] = []
        self._icon_size = self._resolve_icon_size()
        self._photos: list[ImageTk.PhotoImage] = []
        self._build(anchor_rect)

    # -- construction ------------------------------------------------------
    def _resolve_icon_size(self) -> int:
        scale = getattr(self.monitor, "scale", 1.0) or 1.0
        return int(max(36, min(96, round(LAUNCH_ICON * scale))))

    def _panel_opacity(self) -> float:
        if self.layout is not None and self.layout.style in ("ring", "fan"):
            return 1.0
        try:
            return float(self.app.store.settings.panel_opacity)
        except (TypeError, ValueError):
            return 0.94

    def _label_cell_width(self) -> int:
        labels = self.app.store.settings.show_labels or self.folder.show_labels
        if not labels or not self.folder.items:
            return 0
        try:
            measure = tkfont.Font(font=theme.font(8), root=self.app.root).measure
        except (tk.TclError, AttributeError):
            return 0
        widest = max((measure(item.name or "") for item in self.folder.items), default=0)
        return int(widest) + 16

    def _theme_colours(self) -> tuple[str, str, str]:
        settings = self.app.store.settings
        if settings.panel_theme == "light":
            return theme.PANEL_LIGHT_BG, theme.PANEL_LIGHT_BORDER, theme.PANEL_LIGHT_TEXT
        return theme.BG_ELEVATED, theme.BORDER, theme.TEXT

    def _build(self, anchor_rect: tuple[int, int, int, int]) -> None:
        settings = self.app.store.settings
        self.layout = layout_mod.build_layout(
            self.folder.style,
            len(self.folder.items),
            icon=self._icon_size,
            gap=int(10 * (getattr(self.monitor, "scale", 1.0) or 1.0)),
            padding=14,
            labels=settings.show_labels or self.folder.show_labels,
            max_width=self.monitor.work[2] - 60,
            max_height=self.monitor.work[3] - 60,
            min_cell_width=self._label_cell_width(),
        )
        x, y = layout_mod.place_panel(anchor_rect, self.layout, self.monitor.work)
        window = tk.Toplevel(self.app.root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        try:
            desktop.apply_desktop_window_styles(int(window.winfo_id()))
        except tk.TclError:
            pass

        window.geometry(str(self.layout.width) + "x" + str(self.layout.height) + "+" + str(x) + "+" + str(y))
        window.configure(bg=theme.TRANSPARENT_KEY)
        prepare_canvas(window, theme.TRANSPARENT_KEY)
        try:
            window.attributes("-transparentcolor", theme.TRANSPARENT_KEY)
        except tk.TclError:
            pass

        is_radial = self.layout.style in ("ring", "fan")
        if not is_radial:
            try:
                window.attributes("-alpha", 0.0 if settings.animations else self._panel_opacity())
            except tk.TclError:
                pass

        canvas = tk.Canvas(
            window,
            width=self.layout.width,
            height=self.layout.height,
            bg=theme.TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
        self.window = window
        self.canvas = canvas
        self._draw()

        for target_window in (window, canvas):
            self.app.register_drop_target(
                target_window,
                lambda paths, fid=self.folder.id: self.app.add_paths_to_dock(fid, paths),
            )
        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<Leave>", self._on_leave)
        canvas.bind("<Button-1>", self._on_click)
        canvas.bind("<Button-3>", self._on_right_click)
        canvas.bind("<ButtonPress-1>", self._on_press, add="+")
        window.bind("<Escape>", lambda _event: self.hide())
        self.window.after(10, self._probe_pointer)
        if settings.animations and not is_radial:
            self._fade_in()
        self.after_open()

    def after_open(self) -> None:
        self.app._panel_opened(self)

    # -- drawing -----------------------------------------------------------
    def _draw(self) -> None:
        if self.canvas is None or self.layout is None:
            return
        bg, border, text_colour = self._theme_colours()
        canvas = self.canvas
        canvas.delete("all")
        width, height = self.layout.width, self.layout.height
        is_radial = self.layout.style in ("ring", "fan")

        if is_radial:
            self._draw_disc(canvas, width, height, bg, border)
            if self.layout.cells:
                hub_x, hub_y, _orbit, _cw, _ch, hub_radius = self._ring_geometry()
                if hub_radius:
                    self._draw_hub(canvas, hub_x, hub_y, hub_radius, text_colour)
        else:
            # Clean dark card with 12px rounded corners
            theme.rounded_rect(canvas, 1, 1, width - 1, height - 1, radius=12,
                               fill=bg, outline=border, width=1, tags=("chrome", "card"))
            theme.rounded_rect(canvas, 2, 2, width - 2, height - 2, radius=11,
                               fill="", outline=theme.lighten(bg, 0.06), width=1, tags=("chrome",))

        if not self.folder.items:
            canvas.create_text(width / 2, height / 2 - 8, text=tr("Empty dock"),
                               fill=text_colour, font=theme.font(10, "bold"))
            canvas.create_text(width / 2, height / 2 + 12, text=tr("Add shortcuts..."),
                               fill=theme.TEXT_MUTED, font=theme.font(8))
            self._hovered_items = []
            return

        cache: ImageCache = self.app.images
        settings = self.app.store.settings
        labels = settings.show_labels or self.folder.show_labels
        self._hovered_items = []
        self._item_photos = []

        for index, item in enumerate(self.folder.items):
            if index >= len(self.layout.cells):
                break
            cell_x, cell_y = self.layout.cells[index]
            cell_width, cell_height = self.layout.cell_size()
            if not cell_width or not cell_height:
                cell_width = cell_height = self._icon_size

            icon_x = cell_x + (cell_width - self._icon_size) / 2
            icon_y = cell_y + max(0.0, (cell_height - self._icon_size) / 2 - (6 if labels else 0))

            try:
                photo = cache.photo(item_source(item), self._icon_size)
            except Exception:
                photo = None
            large = None
            if photo is not None:
                try:
                    large = cache.photo(item_source(item), int(self._icon_size * 1.15))
                except Exception:
                    large = None

            if photo is not None:
                canvas.create_image(icon_x + self._icon_size / 2, icon_y + self._icon_size / 2,
                                    image=photo, tags=("icon", "item" + str(index), "iconitem" + str(index)))
                self._keep(photo)
                if large is not None:
                    self._keep(large)
            self._item_photos.append((photo, large))

            if labels:
                label_width = max(self._icon_size + 8, cell_width - 4)
                label = _fit_label(item.name, label_width)
                canvas.create_text(
                    cell_x + cell_width / 2,
                    icon_y + self._icon_size + 5,
                    text=label,
                    fill=text_colour,
                    font=theme.font(8),
                    width=label_width,
                    anchor="n",
                    tags=("label", "item" + str(index)),
                )
            self._hovered_items.append((icon_x, icon_y, self._icon_size, self._icon_size))

        if self._hover_index >= 0:
            self._highlight(self._hover_index, True)

    def _draw_disc(self, canvas, width: int, height: int, bg: str, border: str) -> None:
        """Clean translucent dark disc backdrop for radial styles."""
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 2
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                           fill=bg, outline=border, width=1, tags=("chrome", "disc"))
        # Subtle inner highlight ring
        canvas.create_oval(cx - radius + 3, cy - radius + 3, cx + radius - 3, cy + radius - 3,
                           outline=theme.blend(border, theme.ACCENT, 0.22), width=1, tags=("chrome",))

    def _ring_geometry(self) -> tuple[float, float, float, int, int, float]:
        width, height = self.layout.width, self.layout.height
        cx, cy = width / 2, height / 2
        cell_w, cell_h = self.layout.cell_size()
        if not cell_w or not cell_h:
            cell_w = cell_h = self._icon_size
        if not self.layout.cells:
            return cx, cy, 0.0, cell_w, cell_h, 0.0
        cell_x, cell_y = self.layout.cells[0]
        orbit = math.hypot(cell_x + cell_w / 2 - cx, cell_y + cell_h / 2 - cy)
        clearance = orbit - math.hypot(cell_w, cell_h) / 2
        hub_radius = min(clearance * 0.58, min(width, height) * 0.28)
        if hub_radius < 40:
            hub_radius = 0.0
        return cx, cy, orbit, cell_w, cell_h, hub_radius

    def _draw_hub(self, canvas, cx: float, cy: float, hub_radius: float, text_colour: str) -> None:
        """Central hub plate: shows hovered item name, or dock name when nothing is hovered."""
        canvas.delete("hub")
        # Hub circular backing plate
        canvas.create_oval(cx - hub_radius, cy - hub_radius,
                           cx + hub_radius, cy + hub_radius,
                           fill=theme.BG_SIDEBAR, outline=theme.BORDER, width=1, tags=("hub", "chrome"))
        canvas.create_oval(cx - hub_radius + 2, cy - hub_radius + 2,
                           cx + hub_radius - 2, cy + hub_radius - 2,
                           outline=theme.blend(theme.BORDER, theme.ACCENT, 0.3), width=1, tags=("hub",))

        # Check if an item is currently hovered
        if 0 <= self._hover_index < len(self.folder.items):
            item = self.folder.items[self._hover_index]
            icon_side = max(18, int(hub_radius * 0.65))
            try:
                photo = self.app.images.photo(item_source(item), icon_side)
            except Exception:
                photo = None
            if photo is not None:
                self._keep(photo)
                canvas.create_image(cx, cy - hub_radius * 0.28, image=photo, tags=("hub",))

            name = _fit_label(item.name, int(hub_radius * 1.6))
            if name:
                canvas.create_text(cx, cy + hub_radius * 0.22, text=name,
                                   fill=theme.ACCENT, font=theme.font(9, "bold"), tags=("hub",))
            kind_text = _classify_kind(item.target or item.path, item.kind)
            canvas.create_text(cx, cy + hub_radius * 0.58, text=kind_text,
                               fill=theme.TEXT_MUTED, font=theme.font(8), tags=("hub",))
        else:
            # Dock information
            icon_side = max(18, int(hub_radius * 0.65))
            try:
                photo = self.app.images.photo(folder_source(self.folder), icon_side)
            except Exception:
                photo = None
            if photo is not None:
                self._keep(photo)
                canvas.create_image(cx, cy - hub_radius * 0.28, image=photo, tags=("hub",))

            name = _fit_label(self.folder.name, int(hub_radius * 1.6))
            if name:
                canvas.create_text(cx, cy + hub_radius * 0.22, text=name,
                                   fill=text_colour, font=theme.font(9, "bold"), tags=("hub",))
            count = len(self.folder.items)
            status = f"{count} " + (tr("item") if count == 1 else tr("items"))
            canvas.create_text(cx, cy + hub_radius * 0.58, text=status,
                               fill=theme.SUCCESS, font=theme.font(8, "bold"), tags=("hub",))

    def _keep(self, photo: ImageTk.PhotoImage) -> None:
        if photo not in self._photos:
            self._photos.append(photo)

    def _highlight(self, index: int, active: bool) -> None:
        logging.getLogger("mesadock").debug("hover: highlight idx=%s active=%s", index, active)
        if self.canvas is None or index >= len(self._hovered_items):
            return
        tag = "hl" + str(index)
        self.canvas.delete(tag)

        # Magnify on hover
        if index < len(getattr(self, "_item_photos", ())):
            normal, large = self._item_photos[index]
            target = large if (active and large is not None) else normal
            if target is not None:
                self.canvas.itemconfigure("iconitem" + str(index), image=target)

        # Update hub in ring mode
        if self.layout and self.layout.style == "ring":
            cx, cy, _orbit, _cw, _ch, hub_radius = self._ring_geometry()
            if hub_radius:
                _bg, _border, text_colour = self._theme_colours()
                self._draw_hub(self.canvas, cx, cy, hub_radius, text_colour)

        if not active:
            return

        x, y, w, h = self._hovered_items[index]
        pad = 5
        # Soft accent rounded highlight behind hovered item (no cyan border)
        theme.rounded_rect(
            self.canvas,
            x - pad, y - pad, x + w + pad, y + h + pad,
            radius=8,
            fill=theme.blend(theme.BG_ELEVATED, theme.ACCENT, 0.22),
            outline=theme.blend(theme.BORDER, theme.ACCENT, 0.45),
            width=1,
            tags=("hover", tag),
        )
        self.canvas.tag_lower(tag, "iconitem" + str(index))

    # -- interaction -------------------------------------------------------
    def _index_at(self, x: int, y: int) -> int:
        for index, (cx, cy, cw, ch) in enumerate(self._hovered_items):
            if cx - 6 <= x < cx + cw + 6 and cy - 6 <= y < cy + ch + 6:
                return index
        return -1

    def _on_motion(self, event) -> None:
        index = self._index_at(event.x, event.y)
        if index != self._hover_index:
            if self._hover_index >= 0:
                self._highlight(self._hover_index, False)
            self._hover_index = index
            if index >= 0:
                self._highlight(index, True)
            elif self.layout and self.layout.style == "ring":
                cx, cy, _orbit, _cw, _ch, hub_radius = self._ring_geometry()
                if hub_radius:
                    _bg, _border, text_colour = self._theme_colours()
                    self._draw_hub(self.canvas, cx, cy, hub_radius, text_colour)
            self._update_cursor(index)
        self.app._pointer_inside_panel(self, True)

    def _update_cursor(self, index: int) -> None:
        if self.canvas is None:
            return
        self.canvas.configure(cursor="hand2" if index >= 0 else "arrow")

    def _probe_pointer(self) -> None:
        if not self.is_alive():
            return
        try:
            x, y = self.window.winfo_pointerxy()
        except tk.TclError:
            return
        if self.contains_point(x, y):
            self.app._pointer_inside_panel(self, True)
            index = self._index_at(x - self.window.winfo_rootx(), y - self.window.winfo_rooty())
            if index >= 0:
                self._hover_index = index
                self._highlight(index, True)

    def _on_leave(self, _event) -> None:
        if self._hover_index >= 0:
            self._highlight(self._hover_index, False)
            self._hover_index = -1
            if self.layout and self.layout.style == "ring":
                cx, cy, _orbit, _cw, _ch, hub_radius = self._ring_geometry()
                if hub_radius:
                    _bg, _border, text_colour = self._theme_colours()
                    self._draw_hub(self.canvas, cx, cy, hub_radius, text_colour)
        self._update_cursor(-1)
        self.app._pointer_inside_panel(self, False)

    def _on_press(self, _event) -> None:
        self.app._panel_pressed(self)

    def _on_click(self, event) -> None:
        index = self._index_at(event.x, event.y)
        if index < 0 or index >= len(self.folder.items):
            return
        item = self.folder.items[index]
        if self.on_launch:
            self.on_launch(self.folder, item)
        self.hide()

    def _on_right_click(self, event) -> None:
        index = self._index_at(event.x, event.y)
        if self.on_menu is not None and index >= 0:
            self.on_menu(self.folder, self.folder.items[index], event.x_root, event.y_root)
        else:
            self.app.show_dock_menu(self.folder, event.x_root, event.y_root)

    # -- lifetime ----------------------------------------------------------
    def _fade_in(self) -> None:
        target = self._panel_opacity()
        steps = 6
        state = {"step": 0}

        def tick() -> None:
            if self.window is None or not self.window.winfo_exists():
                return
            state["step"] += 1
            try:
                self.window.attributes("-alpha", min(target, target * state["step"] / steps))
            except tk.TclError:
                return
            if state["step"] < steps:
                self._anim_job = self.window.after(12, tick)

        tick()

    def hide(self, animate: bool = True) -> None:
        if self._closing:
            return
        self._closing = True
        settings = self.app.store.settings
        if self._anim_job and self.window is not None:
            try:
                self.window.after_cancel(self._anim_job)
            except tk.TclError:
                pass
            self._anim_job = None

        is_radial = self.layout is not None and self.layout.style in ("ring", "fan")
        if animate and settings.animations and self.window is not None and not is_radial:
            steps = {"left": 4}

            def tick() -> None:
                if self.window is None or not self.window.winfo_exists():
                    self._destroy()
                    return
                steps["left"] -= 1
                try:
                    self.window.attributes("-alpha", self._panel_opacity() * max(0, steps["left"]) / 4)
                except tk.TclError:
                    self._destroy()
                    return
                if steps["left"] <= 0:
                    self._destroy()
                else:
                    self._anim_job = self.window.after(12, tick)

            tick()
            return
        self._destroy()

    def _destroy(self) -> None:
        self.app._panel_closed(self)
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
        self.window = None
        self.canvas = None

    def is_alive(self) -> bool:
        return self.window is not None and bool(self.window.winfo_exists())

    def contains_point(self, x: int, y: int) -> bool:
        if not self.is_alive() or self.window is None:
            return False
        try:
            left = self.window.winfo_rootx()
            top = self.window.winfo_rooty()
            return left <= x < left + self.window.winfo_width() and top <= y < top + self.window.winfo_height()
        except tk.TclError:
            return False

    def rebuild(self) -> None:
        """Redraw the panel after the dock's items or style changed."""
        if self.window is None:
            return
        anchor = self._anchor_rect()
        self._icon_size = self._resolve_icon_size()
        scale = getattr(self.monitor, "scale", 1.0) or 1.0
        self.layout = layout_mod.build_layout(
            self.folder.style,
            len(self.folder.items),
            icon=self._icon_size,
            gap=int(10 * scale),
            padding=14,
            labels=self.app.store.settings.show_labels or self.folder.show_labels,
            max_width=self.monitor.work[2] - 60,
            max_height=self.monitor.work[3] - 60,
            min_cell_width=self._label_cell_width(),
        )
        self.layout_origin = layout_mod.place_panel(anchor, self.layout, self.monitor.work)
        origin_x, origin_y = self.layout_origin
        self.window.geometry(str(self.layout.width) + "x" + str(self.layout.height) + "+" + str(origin_x) + "+" + str(origin_y))
        if self.canvas is not None:
            self.canvas.configure(width=self.layout.width, height=self.layout.height)
        self._hover_index = -1
        self._draw()

    def _anchor_rect(self) -> tuple[int, int, int, int]:
        dock = self.app.docks.get(self.folder.id)
        if dock is not None:
            return dock.rect()
        if self.folder.position:
            return (self.folder.position[0], self.folder.position[1], self.folder.icon_size, self.folder.icon_size)
        return (0, 0, self.folder.icon_size, self.folder.icon_size)


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _fit_label(text: str, available: int) -> str:
    """Shorten a name on one line until it fits within available pixels."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        measure = tkfont.Font(font=theme.font(8)).measure
    except (tk.TclError, AttributeError):
        return _truncate(text, max(6, available // 7))
    if measure(text) <= available:
        return text
    shortened = text
    while shortened and measure(shortened + "\u2026") > available:
        shortened = shortened[:-1]
    return (shortened.rstrip() + "\u2026") if shortened else "\u2026"
