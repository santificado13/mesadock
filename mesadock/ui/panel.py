"""The expanding panel that a dock fans out into.

One Toplevel per open panel. The whole panel is composed as a single RGBA
picture (card or disc, shadow, icons, names) and presented with per-pixel
alpha (win32.layered), so it has a real soft shadow, smooth corners and a
background that is actually translucent. The Tk canvas inside only receives
the mouse: items highlight on hover and launch on click, and the panel closes
itself when the pointer leaves both the panel and its dock icon.
"""
from __future__ import annotations

import logging
import math
import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from ..core import icons as icon_art
from ..core import layout as layout_mod
from ..core.i18n import tr
from ..core.models import DockFolder, DockItem
from ..win32 import desktop, layered
from . import paint, theme
from .images import ImageCache, folder_source, item_source, prepare_canvas

LAUNCH_ICON = 40
# Transparent margin around the card that holds its shadow.
SHADOW_PAD = 18
FADE_IN_STEPS = 7
FADE_OUT_STEPS = 4
SLIDE_PIXELS = 10


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
        self.layout_origin: tuple[int, int] = (0, 0)
        self._hover_index = -1
        self._closing = False
        self._anim_job: str | None = None
        self._hovered_items: list[tuple[int, int, int, int]] = []
        self._icon_size = self._resolve_icon_size()
        self._photos: list[ImageTk.PhotoImage] = []
        # None = not tried yet, True = per-pixel alpha works, False = colour-key fallback
        self._layered: bool | None = None
        self._backdrop: Image.Image | None = None
        self._idle: Image.Image | None = None
        self._image: Image.Image | None = None
        self._opacity = 1.0
        self._slide = 0
        self._build(anchor_rect)

    # -- construction ------------------------------------------------------
    def _resolve_icon_size(self) -> int:
        scale = getattr(self.monitor, "scale", 1.0) or 1.0
        return int(max(36, min(96, round(LAUNCH_ICON * scale))))

    def _dpi(self) -> float:
        """DPI of the monitor this panel is on (Tk only knows the primary one)."""
        return 96.0 * float(getattr(self.monitor, "scale", 1.0) or 1.0)

    def _font(self, points: float, weight: str = "normal"):
        return paint.font(paint.points_to_pixels(points, self._dpi()), weight)

    def _is_radial(self) -> bool:
        return self.layout is not None and self.layout.style in ("ring", "fan")

    def _show_labels(self) -> bool:
        return bool(self.app.store.settings.show_labels or self.folder.show_labels)

    def _background_alpha(self) -> int:
        """Alpha of the card itself; icons and names stay fully opaque."""
        settings = self.app.store.settings
        if settings.panel_background == "solid":
            return 255
        try:
            opacity = float(settings.panel_opacity)
        except (TypeError, ValueError):
            opacity = 0.92
        # The same for every style. Ring and fan open on top of their own dock,
        # which would show through the disc: the dock hides itself meanwhile
        # (see covers_dock) instead of the disc ignoring this setting.
        return int(255 * max(0.35, min(1.0, opacity)))

    def covers_dock(self) -> bool:
        """True while this panel's disc really sits on top of its own dock.

        Ring and fan are centred on the dock when there is room; near a screen
        edge the disc is pushed aside and the dock stays next to it, in which
        case it must remain visible.
        """
        if not (self._is_radial() and not self._closing and self.is_alive()):
            return False
        anchor = getattr(self, "_anchor", None)
        if not anchor or self.layout is None:
            return False
        dock_x, dock_y = anchor[0] + anchor[2] / 2, anchor[1] + anchor[3] / 2
        centre_x = self.layout_origin[0] + self.layout.width / 2
        centre_y = self.layout_origin[1] + self.layout.height / 2
        radius = min(self.layout.width, self.layout.height) / 2
        return math.hypot(dock_x - centre_x, dock_y - centre_y) < radius

    def _label_cell_width(self) -> int:
        if not self._show_labels() or not self.folder.items:
            return 0
        face = self._font(8)
        widest = max((paint.text_width(item.name or "", face) for item in self.folder.items), default=0)
        return int(widest) + 16

    def _theme_colours(self) -> tuple[str, str, str]:
        settings = self.app.store.settings
        if settings.panel_theme == "light":
            return theme.PANEL_LIGHT_BG, theme.PANEL_LIGHT_BORDER, theme.PANEL_LIGHT_TEXT
        return theme.BG_ELEVATED, theme.BORDER, theme.TEXT

    def _make_layout(self) -> None:
        scale = getattr(self.monitor, "scale", 1.0) or 1.0
        self.layout = layout_mod.build_layout(
            self.folder.style,
            len(self.folder.items),
            icon=self._icon_size,
            gap=int(10 * scale),
            padding=14,
            labels=self._show_labels(),
            max_width=self.monitor.work[2] - 60,
            max_height=self.monitor.work[3] - 60,
            min_cell_width=self._label_cell_width(),
        )

    def _window_size(self) -> tuple[int, int]:
        return self.layout.width + SHADOW_PAD * 2, self.layout.height + SHADOW_PAD * 2

    def _window_origin(self) -> tuple[int, int]:
        return self.layout_origin[0] - SHADOW_PAD, self.layout_origin[1] - SHADOW_PAD

    def _apply_geometry(self) -> None:
        width, height = self._window_size()
        x, y = self._window_origin()
        self.window.geometry(str(width) + "x" + str(height) + "+" + str(x) + "+" + str(y))
        if self.canvas is not None:
            self.canvas.configure(width=width, height=height)

    def _build(self, anchor_rect: tuple[int, int, int, int]) -> None:
        settings = self.app.store.settings
        self._make_layout()
        self._anchor = anchor_rect
        self.layout_origin = layout_mod.place_panel(anchor_rect, self.layout, self.monitor.work)
        window = tk.Toplevel(self.app.root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        try:
            desktop.apply_desktop_window_styles(int(window.winfo_id()))
        except tk.TclError:
            pass
        window.configure(bg=theme.TRANSPARENT_KEY)
        self.window = window
        width, height = self._window_size()
        canvas = tk.Canvas(window, width=width, height=height, bg=theme.TRANSPARENT_KEY,
                           highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas
        self._apply_geometry()

        animate = bool(settings.animations)
        self._opacity = 0.0 if animate else 1.0
        self._slide = SLIDE_PIXELS if animate and not self._is_radial() else 0
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
        if animate:
            self._fade_in()
        self.after_open()

    def after_open(self) -> None:
        self.app._panel_opened(self)

    # -- drawing -----------------------------------------------------------
    def _draw(self) -> None:
        """Lay the items out and paint the whole panel."""
        if self.canvas is None or self.layout is None:
            return
        self._backdrop = None
        self._hovered_items = []
        if self.folder.items:
            labels = self._show_labels()
            cell_width, cell_height = self.layout.cell_size()
            if not cell_width or not cell_height:
                cell_width = cell_height = self._icon_size
            for index, _item in enumerate(self.folder.items):
                if index >= len(self.layout.cells):
                    break
                cell_x, cell_y = self.layout.cells[index]
                icon_x = SHADOW_PAD + cell_x + (cell_width - self._icon_size) / 2
                icon_y = SHADOW_PAD + cell_y + max(0.0, (cell_height - self._icon_size) / 2 - (6 if labels else 0))
                self._hovered_items.append((icon_x, icon_y, self._icon_size, self._icon_size))
        self._render()

    def _render(self) -> None:
        """Compose the picture for the current hover state and show it."""
        if self.window is None or self.layout is None:
            return
        self._image = self._compose()
        self._present()

    def _accent(self) -> tuple[int, int, int]:
        return icon_art.accent_rgb(self.folder)

    def _compose_backdrop(self) -> Image.Image:
        """Shadow plus card (or disc): everything that does not change on hover."""
        bg, border, _text = self._theme_colours()
        accent = self._accent()
        size = self._window_size()
        width, height = self.layout.width, self.layout.height
        alpha = self._background_alpha()
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        pad = SHADOW_PAD
        if self._is_radial():
            cx, cy = pad + width / 2, pad + height / 2
            radius = min(width, height) / 2 - 2
            box = (cx - radius, cy - radius, cx + radius, cy + radius)
            image.alpha_composite(paint.outer_shadow(size, box, 0, blur=11, offset=(0, 6), opacity=120,
                                                     round_shape=True))
            image.alpha_composite(paint.ellipse(size, box, fill=paint.rgba(bg, alpha),
                                                outline=paint.rgba(paint.mix(border, accent, 0.35), 255), width=1))
            image.alpha_composite(paint.ellipse(
                size, (box[0] + 4, box[1] + 4, box[2] - 4, box[3] - 4),
                outline=paint.rgba(paint.mix(bg, (255, 255, 255), 0.10), 150), width=1))
        else:
            box = (pad + 1, pad + 1, pad + width - 1, pad + height - 1)
            image.alpha_composite(paint.outer_shadow(size, box, 14, blur=11, offset=(0, 6), opacity=120))
            image.alpha_composite(paint.rounded(size, box, 14, fill=paint.rgba(bg, alpha),
                                                outline=paint.rgba(paint.mix(border, accent, 0.30), 255), width=1))
            image.alpha_composite(paint.rounded(
                size, (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), 13,
                outline=paint.rgba(paint.mix(bg, (255, 255, 255), 0.10), 140), width=1))
            self._clear_over_dock(image)
        return image

    def _clear_over_dock(self, image: Image.Image) -> None:
        """Erase the shadow where the panel window overlaps its dock.

        The shadow margin is wider than the gap to the dock, so the panel's
        window covered a strip of the dock: the shadow was painted over the
        dock's name and that strip stopped taking clicks.
        """
        anchor = getattr(self, "_anchor", None)
        if not anchor:
            return
        origin_x, origin_y = self._window_origin()
        left = max(0, int(anchor[0] - origin_x))
        top = max(0, int(anchor[1] - origin_y))
        right = min(image.width, int(anchor[0] + anchor[2] - origin_x))
        bottom = min(image.height, int(anchor[1] + anchor[3] - origin_y))
        if right > left and bottom > top:
            image.paste((0, 0, 0, 0), (left, top, right, bottom))

    def _item_icon(self, item: DockItem, size: int) -> Image.Image | None:
        cache: ImageCache = self.app.images
        try:
            picture = cache.pillow(item_source(item), size).convert("RGBA")
        except Exception:
            return None
        if self.folder.tint:
            picture = paint.tint(picture, self._accent())
        return picture

    def _compose(self) -> Image.Image:
        """The panel picture for the current hover state.

        Painting every icon and name takes tens of milliseconds on a big dock, too
        slow to follow the pointer. So the resting picture is painted once and
        kept; a hover only repaints the item under the pointer (and the ring hub).
        """
        if self._backdrop is None:
            self._backdrop = self._compose_backdrop()
            self._idle = None
        _bg, _border, text_colour = self._theme_colours()
        width, height = self._window_size()

        if not self.folder.items:
            image = self._backdrop.copy()
            paint.draw_text(image, (width / 2, height / 2 - 9), tr("Empty dock"),
                            self._font(10, "bold"), paint.rgba(text_colour))
            paint.draw_text(image, (width / 2, height / 2 + 11), tr("Add shortcuts..."),
                            self._font(8), paint.rgba(theme.TEXT_MUTED))
            return image

        hub = self._ring_geometry() if self.layout.style == "ring" else None
        if hub is not None and not hub[5]:
            hub = None
        if self._idle is None:
            idle = self._backdrop.copy()
            if hub is not None:
                self._compose_hub(idle, hub[0], hub[1], hub[5], text_colour, -1)
            for index in range(len(self._hovered_items)):
                self._paint_item(idle, index, False)
            self._idle = idle

        image = self._idle.copy()
        hovered = self._hover_index
        if 0 <= hovered < len(self._hovered_items):
            self._restore(image, self._item_box(hovered))
            self._paint_item(image, hovered, True)
            if hub is not None:
                radius = hub[5] + 2
                self._restore(image, (hub[0] - radius, hub[1] - radius, hub[0] + radius, hub[1] + radius))
                self._compose_hub(image, hub[0], hub[1], hub[5], text_colour, hovered)
        return image

    def _restore(self, image: Image.Image, box) -> None:
        """Put the bare backdrop back inside ``box`` before repainting there."""
        left, top = max(0, int(box[0])), max(0, int(box[1]))
        right, bottom = min(image.width, int(box[2]) + 1), min(image.height, int(box[3]) + 1)
        if right > left and bottom > top:
            image.paste(self._backdrop.crop((left, top, right, bottom)), (left, top))

    def _label_width(self, centre_x: float, side: float) -> int:
        """Never wider than what fits between the item and the nearest side of the
        panel: a long name on the edge of a ring was cut off there."""
        cell_width, _cell_height = self.layout.cell_size()
        if not cell_width:
            cell_width = self._icon_size
        width, _height = self._window_size()
        inner_left, inner_right = SHADOW_PAD + 8, width - SHADOW_PAD - 8
        room = 2 * min(centre_x - inner_left, inner_right - centre_x)
        return int(max(side, min(max(side + 8, cell_width - 4), room)))

    def _item_box(self, index: int) -> tuple[float, float, float, float]:
        """Everything one item paints: hover plate, enlarged icon and its name."""
        icon_x, icon_y, side, _side = self._hovered_items[index]
        centre_x = icon_x + side / 2
        half = max(side * 1.15 / 2 + 8, (self._label_width(centre_x, side) / 2 + 6) if self._show_labels() else 0)
        line = paint.points_to_pixels(8, self._dpi()) + 12
        return (centre_x - half, icon_y - side * 0.08 - 8, centre_x + half,
                icon_y + side + 8 + (line if self._show_labels() else side * 0.08))

    def _paint_item(self, image: Image.Image, index: int, hovered: bool) -> None:
        bg, _border, text_colour = self._theme_colours()
        accent = self._accent()
        item = self.folder.items[index]
        icon_x, icon_y, side, _side = self._hovered_items[index]
        centre = (icon_x + side / 2, icon_y + side / 2)
        if hovered:
            pad = 6
            plate = paint.rounded(
                (side + pad * 2, side + pad * 2), (0, 0, side + pad * 2, side + pad * 2), 10,
                fill=paint.rgba(accent, 52), outline=paint.rgba(accent, 150), width=1)
            paint.paste_centre(image, plate, centre)
        picture = self._item_icon(item, int(side * 1.15) if hovered else side)
        if picture is not None:
            paint.paste_centre(image, picture, centre)
        if self._show_labels():
            face = self._font(8)
            text = paint.fit_text(item.name, face, self._label_width(centre[0], side))
            colour = paint.rgba(paint.mix(text_colour, accent, 0.35) if hovered else text_colour)
            # On a see-through card the names get an outline in the card's colour.
            halo = paint.rgba(bg, 205) if self._background_alpha() < 215 else None
            paint.draw_text(image, (centre[0], icon_y + side + 5), text, face, colour, anchor="ma", halo=halo)

    def _ring_geometry(self) -> tuple[float, float, float, int, int, float]:
        """Hub centre (window coordinates), orbit, cell size and hub radius."""
        width, height = self.layout.width, self.layout.height
        cx, cy = width / 2, height / 2
        cell_w, cell_h = self.layout.cell_size()
        if not cell_w or not cell_h:
            cell_w = cell_h = self._icon_size
        if not self.layout.cells:
            return cx + SHADOW_PAD, cy + SHADOW_PAD, 0.0, cell_w, cell_h, 0.0
        cell_x, cell_y = self.layout.cells[0]
        orbit = math.hypot(cell_x + cell_w / 2 - cx, cell_y + cell_h / 2 - cy)
        clearance = orbit - math.hypot(cell_w, cell_h) / 2
        hub_radius = min(clearance * 0.58, min(width, height) * 0.28)
        if hub_radius < 40:
            hub_radius = 0.0
        return cx + SHADOW_PAD, cy + SHADOW_PAD, orbit, cell_w, cell_h, hub_radius

    def _compose_hub(self, image: Image.Image, cx: float, cy: float, hub_radius: float, text_colour: str,
                     hover_index: int) -> None:
        """Centre plate: the hovered item's name, or the dock's when nothing is hovered."""
        accent = self._accent()
        side = int(hub_radius * 2) + 2
        plate = paint.ellipse((side, side), (1, 1, side - 1, side - 1),
                              fill=paint.rgba(theme.BG_SIDEBAR if self.app.store.settings.panel_theme != "light"
                                              else paint.mix(theme.PANEL_LIGHT_BG, (0, 0, 0), 0.05), 235),
                              outline=paint.rgba(paint.mix(theme.BORDER, accent, 0.45), 255), width=1)
        paint.paste_centre(image, plate, (cx, cy))
        icon_side = max(18, int(hub_radius * 0.65))
        name_face = self._font(9, "bold")
        small_face = self._font(8)
        hovered = 0 <= hover_index < len(self.folder.items)
        if hovered:
            item = self.folder.items[hover_index]
            picture = self._item_icon(item, icon_side)
            title = item.name
            title_colour = paint.rgba(accent)
            subtitle = _classify_kind(item.target or item.path, item.kind)
            subtitle_colour = paint.rgba(theme.TEXT_MUTED)
        else:
            try:
                picture = self.app.images.pillow(folder_source(self.folder), icon_side).convert("RGBA")
            except Exception:
                picture = None
            title = self.folder.name
            title_colour = paint.rgba(text_colour)
            count = len(self.folder.items)
            subtitle = f"{count} " + (tr("item") if count == 1 else tr("items"))
            subtitle_colour = paint.rgba(accent)
        if picture is not None:
            paint.paste_centre(image, picture, (cx, cy - hub_radius * 0.28))
        paint.draw_text(image, (cx, cy + hub_radius * 0.24), paint.fit_text(title, name_face, int(hub_radius * 1.6)),
                        name_face, title_colour)
        paint.draw_text(image, (cx, cy + hub_radius * 0.58), subtitle, small_face, subtitle_colour)

    def _present(self) -> None:
        if self.window is None or self._image is None:
            return
        x, y = self._window_origin()
        if self._layered is not False:
            try:
                self.window.update_idletasks()
                shown = layered.present(int(self.window.winfo_id()), self._image,
                                        position=(x, y + self._slide), opacity=self._opacity)
            except tk.TclError:
                return
            if shown:
                self._layered = True
                return
            self._layered = False
            prepare_canvas(self.window, theme.TRANSPARENT_KEY)
        # Fallback: the same picture on the canvas, see-through by colour key.
        backdrop = Image.new("RGBA", self._image.size, paint.rgba(theme.TRANSPARENT_KEY))
        solid = self._image.copy()
        solid.putalpha(self._image.getchannel("A").point(lambda v: 255 if v >= 64 else 0))
        backdrop.alpha_composite(solid)
        photo = ImageTk.PhotoImage(backdrop)
        self._photos = [photo]
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=photo, anchor="nw")
        try:
            self.window.attributes("-alpha", max(0.0, min(1.0, self._opacity)))
        except tk.TclError:
            pass

    # -- interaction -------------------------------------------------------
    def _index_at(self, x: int, y: int) -> int:
        for index, (cx, cy, cw, ch) in enumerate(self._hovered_items):
            if cx - 6 <= x < cx + cw + 6 and cy - 6 <= y < cy + ch + 6:
                return index
        return -1

    def _set_hover(self, index: int) -> None:
        if index == self._hover_index:
            return
        logging.getLogger("mesadock").debug("hover: item %s", index)
        self._hover_index = index
        self._update_cursor(index)
        self._render()

    def _on_motion(self, event) -> None:
        self._set_hover(self._index_at(event.x, event.y))
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
            origin_x, origin_y = self._window_origin()
            self._set_hover(self._index_at(x - origin_x, y - origin_y - self._slide))

    def _on_leave(self, _event) -> None:
        self._set_hover(-1)
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
    def _cancel_animation(self) -> None:
        if self._anim_job and self.window is not None:
            try:
                self.window.after_cancel(self._anim_job)
            except tk.TclError:
                pass
        self._anim_job = None

    def _fade_in(self) -> None:
        """Fade in while the panel rises a few pixels into place."""
        slide_from = self._slide
        state = {"step": 0}

        def tick() -> None:
            self._anim_job = None
            if self.window is None or self._closing or not self.window.winfo_exists():
                return
            state["step"] += 1
            progress = min(1.0, state["step"] / FADE_IN_STEPS)
            eased = 1.0 - (1.0 - progress) ** 3  # ease-out: fast start, soft landing
            self._opacity = eased
            self._slide = int(round(slide_from * (1.0 - eased)))
            self._present()
            if progress < 1.0:
                self._anim_job = self.window.after(14, tick)

        tick()

    def hide(self, animate: bool = True) -> None:
        if self._closing:
            return
        self._closing = True
        self._cancel_animation()
        self.app._redraw_dock(self.folder.id)  # the dock under a ring/fan comes back
        if animate and self.app.store.settings.animations and self.window is not None:
            start = max(0.05, self._opacity)
            steps = {"left": FADE_OUT_STEPS}

            def tick() -> None:
                self._anim_job = None
                if self.window is None or not self.window.winfo_exists():
                    self._destroy()
                    return
                steps["left"] -= 1
                self._opacity = start * max(0, steps["left"]) / FADE_OUT_STEPS
                if steps["left"] <= 0:
                    self._destroy()
                    return
                self._present()
                self._anim_job = self.window.after(14, tick)

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
        """True over the card itself; the shadow margin around it does not count."""
        if not self.is_alive() or self.window is None or self.layout is None:
            return False
        left, top = self.layout_origin
        return left <= x < left + self.layout.width and top <= y < top + self.layout.height

    def rebuild(self) -> None:
        """Redraw the panel after the dock's items, style or look changed."""
        # Not while it is closing: cancelling the fade-out here left a fully
        # visible panel that could never be closed again.
        if self.window is None or self._closing:
            return
        self._cancel_animation()
        self._icon_size = self._resolve_icon_size()
        self._make_layout()
        self._anchor = self._anchor_rect()
        self.layout_origin = layout_mod.place_panel(self._anchor, self.layout, self.monitor.work)
        self._apply_geometry()
        self._hover_index = -1
        self._opacity = 1.0
        self._slide = 0
        self._draw()

    def _anchor_rect(self) -> tuple[int, int, int, int]:
        dock = self.app.docks.get(self.folder.id)
        if dock is not None:
            return dock.rect()
        if self.folder.position:
            return (self.folder.position[0], self.folder.position[1], self.folder.icon_size, self.folder.icon_size)
        return (0, 0, self.folder.icon_size, self.folder.icon_size)
