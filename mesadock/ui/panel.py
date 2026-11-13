"""The expanding panel that a dock fans out into.

One Toplevel per open panel, drawn on a single canvas: a rounded translucent
card with the dock's items laid out by core.layout. Items highlight on hover and
launch on click; the panel closes itself when the pointer leaves both the panel
and its dock icon.
"""
from __future__ import annotations

import math
import tkinter as tk
import logging
from typing import Callable

from PIL import ImageTk

from ..core import layout as layout_mod
from ..core.models import DockFolder, DockItem
from ..win32 import desktop
from . import theme
from .images import ImageCache, folder_source, item_source, prepare_canvas

LAUNCH_ICON = 40

# Orbit chrome. The radiating menus are drawn as an instrument dial: a dark
# disc, a lit rim and thin dashed rings that turn slowly. The cool teal is
# deliberately not one of the per-style accents so it never competes with the
# dock's own colour; it reads as "surface", not "content".
ORBIT_RIM = "#22d3ee"
ORBIT_RIM_SOFT = "#0e7490"
ORBIT_GLOW = "#164e63"
ORBIT_RING = "#06b6d4"
ORBIT_RING_DIM = "#155e75"
ORBIT_DASH = "#38bdf8"
HUB_FILL = "#04121a"
HUB_RING = "#22d3ee"
HUB_GLOW = "#0e7490"
# Degrees per animation tick. Slow enough to read as a slow mechanism rather
# than a spinner, and cheap enough that the panel stays idle-looking.
ORBIT_STEP = 1.6
# 1.6 deg per 55 ms is roughly one turn every twelve seconds: slow enough to
# read as a mechanism, fast enough that the movement is actually visible.
ORBIT_INTERVAL = 55
# The same language on the square cards: a dotted hairline inside the edge.
CARD_MARKS = "#24343f"
# Dash phase is what moves, not the geometry: shifting it one pixel per tick
# walks the dots along the frame, which is cheap enough to run on every style.
MARKS_STEP = 1


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
        self._orbit_job: str | None = None
        self._orbit_phase = 0.0
        self._marks_job: str | None = None
        self._marks_phase = 0
        self._hovered_items: list[tuple[int, int, int, int]] = []
        self._icon_size = self._resolve_icon_size()
        self._build(anchor_rect)

    # -- construction ------------------------------------------------------
    def _resolve_icon_size(self) -> int:
        settings = self.app.store.settings
        size = self.folder.icon_size or settings.icon_size
        scale = getattr(self.monitor, "scale", 1.0) or 1.0
        # Floor raised from 36px: a labelled cell is sized from the icon, so a tiny
        # icon left the name almost no room and long shortcut names were cut to a
        # few characters. 56px keeps every realistic name readable and still small.
        return int(max(56, min(128, round(size * 0.78 * scale))))

    def _panel_opacity(self) -> float:
        """Window opacity, forced solid for the radiating styles.

        A translucent disc lets whatever is behind it show through the middle of
        the dial, and that reads as a smudge instead of a surface. The dial only
        looks like an instrument when it is opaque, so ring and fan ignore the
        card opacity setting; Grid/Column/Row keep honouring it.
        """
        if self.layout is not None and self.layout.style in ("ring", "fan"):
            return 1.0
        try:
            return float(self.app.store.settings.panel_opacity)
        except (TypeError, ValueError):
            return 0.92

    def _label_cell_width(self) -> int:
        """Width the cell needs so the widest name fits without an ellipsis.

        The cell used to be sized from the icon alone, so a dock whose names were
        longer than the icon got every one of them cut ("Web Bankin..."). Here the
        real names are measured with the font that will draw them, which is the only
        way to satisfy names of very different lengths at the same time.
        """
        labels = self.app.store.settings.show_labels or self.folder.show_labels
        if not labels or not self.folder.items:
            return 0
        try:
            # tk.font is a submodule: it is not on the tkinter package until it is
            # imported explicitly, and the AttributeError used to be swallowed here,
            # silently disabling the whole measurement and clipping every long name.
            import tkinter.font as tkfont

            measure = tkfont.Font(font=theme.font(8), root=self.app.root).measure
        except (tk.TclError, AttributeError):
            return 0
        widest = max((measure(item.name or "") for item in self.folder.items), default=0)
        # A little slack so the ellipsis never appears on an exact fit.
        return int(widest) + 6

    def _theme_colours(self) -> tuple[str, str, str]:
        settings = self.app.store.settings
        use_light = False
        if settings.panel_theme == "light":
            use_light = True
        elif settings.panel_theme == "auto":
            use_light = False
        if use_light:
            return theme.PANEL_LIGHT_BG, theme.PANEL_LIGHT_BORDER, theme.PANEL_LIGHT_TEXT
        return "#151a23", "#2c3646", theme.TEXT

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
        # The expanded panel is an interactive menu: it floats above apps even
        # when the docks sit on the desktop layer, so it stays visible/clickable.
        # Keep it non-activating so opening it never steals focus.
        window.attributes("-topmost", True)
        try:
            desktop.apply_desktop_window_styles(int(window.winfo_id()))
        except tk.TclError:
            pass
        try:
            window.attributes("-alpha", 0.0 if settings.animations else self._panel_opacity())
        except tk.TclError:
            pass
        window.geometry(str(self.layout.width) + "x" + str(self.layout.height) + "+" + str(x) + "+" + str(y))
        window.configure(bg=theme.TRANSPARENT_KEY)
        prepare_canvas(window, theme.TRANSPARENT_KEY)
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
        # The panel is the biggest target on screen while it is open, so it has to
        # accept a drop too. The canvas and the toplevel are different HWNDs, so
        # both are registered.
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
        if settings.animations:
            self._fade_in()
        self.after_open()

    def after_open(self) -> None:
        """Hook for the controller (used to cancel the auto-close timer)."""
        self.app._panel_opened(self)

    # -- drawing -----------------------------------------------------------
    def _draw(self) -> None:
        if self.canvas is None or self.layout is None:
            return
        bg, border, text_colour = self._theme_colours()
        canvas = self.canvas
        canvas.delete("all")
        width, height = self.layout.width, self.layout.height
        # Ring and Fan radiate from the dock, so a rounded card behind them looked
        # like a box the items had fallen into. They get a soft disc instead, which
        # is what makes the radiating styles read as circular.
        is_radial = self.layout.style in ("ring", "fan")
        if is_radial:
            self._draw_disc(canvas, width, height, bg, border)
            if self.layout.cells:
                hub_x, hub_y, _orbit, _cw, _ch, hub_radius = self._ring_geometry()
                if hub_radius:
                    self._draw_hub(canvas, hub_x, hub_y, hub_radius, text_colour)
        else:
            # Layered chrome: outer shadow -> body -> inner hairline. A single flat
            # rounded rectangle read as a grey box; the extra passes give it depth.
            for step, alpha in ((4, "#05070c"), (2, border)):
                theme.rounded_rect(canvas, 1 - step + 1, 1 - step + 1,
                                   width - 1 + step, height - 1 + step,
                                   radius=16 + step, fill=alpha, outline="")
            theme.rounded_rect(canvas, 1, 1, width - 1, height - 1, radius=16,
                               fill=bg, outline=border, width=1)
            theme.rounded_rect(canvas, 2, 2, width - 2, height - 2, radius=15,
                               fill="", outline=theme.lighten(bg, 0.10), width=1)
            # The cards were flat slabs next to the dial. A dotted hairline just
            # inside the edge gives them the same instrument language: one more
            # rectangle, animated by its dash phase rather than by redrawing.
            canvas.create_rectangle(7, 7, width - 7, height - 7,
                                    outline=CARD_MARKS, width=1,
                                    dash=(1, 7), tags=("chrome", "marks"))
        if not self.folder.items:
            canvas.create_text(width / 2, height / 2 - 8, text="This dock is empty", fill=text_colour, font=theme.font(10, "bold"))
            canvas.create_text(width / 2, height / 2 + 12, text="Right-click a dock to add shortcuts", fill="#8b98ad", font=theme.font(8))
            self._hovered_items = []
            # The rings are chrome, not content: draw them under the message so an
            # empty dock still looks like the same dial instead of a bare disc.
            self._start_orbit()
            self._start_marks()
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
            # Icon and name are both centred in the cell. Anchoring them on the
            # icon's own width left every item wedged against the left edge of a
            # wider cell, and in a column the name (which uses the cell width)
            # then hung off the panel entirely.
            icon_x = cell_x + (cell_width - self._icon_size) / 2
            icon_y = cell_y + max(0.0, (cell_height - self._icon_size) / 2 - 4)
            try:
                photo = cache.photo(item_source(item), self._icon_size)
            except Exception:
                photo = None
            large = None
            if photo is not None:
                try:
                    large = cache.photo(item_source(item), int(self._icon_size * 1.18))
                except Exception:
                    large = None
            if photo is not None:
                canvas.create_image(icon_x + self._icon_size / 2, icon_y + self._icon_size / 2, image=photo, tags=("icon", "item" + str(index), "iconitem" + str(index)))
                self._keep(photo)
                if large is not None:
                    self._keep(large)
            self._item_photos.append((photo, large))
            if labels:
                # The label gets the full cell width, which is wider than the icon on
                # purpose: giving it only the icon's own width clipped names like
                # "Web Banking C6 Bank" while the cell beside it sat empty.
                label_width = max(self._icon_size + 8, cell_width)
                label = _fit_label(item.name, label_width)
                canvas.create_text(
                    cell_x + cell_width / 2,
                    icon_y + self._icon_size + 6,
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
        # Rings run only while a radiating dock is open; every other style, and the
        # closed panel, stops the timer so nothing ticks in the background.
        if is_radial and self.layout.style == "ring":
            self._start_orbit()
        else:
            self._stop_orbit()
            self._start_marks()

    def _draw_disc(self, canvas, width: int, height: int, bg: str, border: str) -> None:
        """Soft circular backdrop used by the radiating styles."""
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 2
        # Base: the darkest fill, then stacked rings that lighten towards the
        # middle. A canvas cannot do a real radial gradient, and an exported
        # image would clash with the transparency key, so this is the closest
        # honest approximation.
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                           fill="#04070c", outline="", tags=("chrome",))
        # More passes than the eye reads as separate rings: the point is that the
        # steps are too small to see as bands, so the disc reads as a gradient
        # while staying a handful of flat ovals the canvas can draw quickly.
        for step in range(14, 0, -1):
            shrink = step * radius / 26
            shade = theme.blend("#0d1322", bg, step / 16)
            canvas.create_oval(cx - radius + shrink, cy - radius + shrink,
                               cx + radius - shrink, cy + radius - shrink,
                               fill=shade, outline="", tags=("chrome",))
        # Lit rim: a wide, dim bloom just inside the edge, the rim itself, then a
        # hairline further in. Three passes are what give the disc its glow.
        for offset, colour, line_width in (
            (0, ORBIT_GLOW, 6),
            (2, ORBIT_RIM_SOFT, 3),
            (5, ORBIT_RIM, 2),
            (11, theme.blend(border, ORBIT_RIM, 0.45), 1),
        ):
            canvas.create_oval(cx - radius + offset, cy - radius + offset,
                               cx + radius - offset, cy + radius - offset,
                               outline=colour, width=line_width, tags=("chrome",))

    def _ring_geometry(self) -> tuple[float, float, float, int, int, float]:
        """Centre, item-orbit radius and hub radius of the panel.

        The hub has to fit in the empty middle. The closest a cell can come to
        the centre is its orbit radius minus half its own diagonal, so that
        clearance is the hard ceiling. A dock with two or three items has almost
        no middle at all, so the hub is dropped rather than drawn as a cramped
        dot in the gaps.
        """
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
        hub_radius = min(clearance * 0.55, min(width, height) * 0.28)
        if hub_radius < 46:
            hub_radius = 0.0
        return cx, cy, orbit, cell_w, cell_h, hub_radius

    def _draw_hub(self, canvas, cx: float, cy: float, hub_radius: float, text_colour: str) -> None:
        """Identity plate in the middle: the dock's icon, its name and item count."""
        canvas.create_oval(cx - hub_radius - 3, cy - hub_radius - 3,
                           cx + hub_radius + 3, cy + hub_radius + 3,
                           outline=HUB_GLOW, width=1, tags=("hub", "chrome"))
        canvas.create_oval(cx - hub_radius, cy - hub_radius,
                           cx + hub_radius, cy + hub_radius,
                           fill=HUB_FILL, outline=HUB_RING, width=2, tags=("hub", "chrome"))
        canvas.create_oval(cx - hub_radius + 6, cy - hub_radius + 6,
                           cx + hub_radius - 6, cy + hub_radius - 6,
                           outline=HUB_GLOW, width=1, tags=("hub",))
        icon_side = max(20, int(hub_radius * 0.78))
        try:
            photo = self.app.images.photo(folder_source(self.folder), icon_side)
        except Exception:
            photo = None
        if photo is not None:
            self._keep(photo)
            canvas.create_image(cx, cy - hub_radius * 0.30, image=photo, tags=("hub",))
        name = _fit_label(self.folder.name, int(hub_radius * 1.6)).upper()
        if name:
            canvas.create_text(cx, cy + hub_radius * 0.26, text=name,
                               fill=text_colour, font=theme.font(9, "bold"), tags=("hub",))
        count = len(self.folder.items)
        status = "%d ITEM" % count if count == 1 else "%d ITEMS" % count
        canvas.create_text(cx, cy + hub_radius * 0.60, text=status,
                           fill=theme.SUCCESS, font=theme.font(7, "bold"), tags=("hub",))

    # -- chrome animation ---------------------------------------------------
    def _start_marks(self) -> None:
        """Walk the dotted hairline on the square cards.

        Grid, Column and Row are hand-placed rectangles, so they cannot orbit
        anything. What they can do is carry the same dot pattern as the dial and
        let its phase drift, which gives the panel the same quiet movement
        without inventing geometry it does not have.
        """
        self._stop_marks()
        if self.layout is None or self.layout.style in ("ring", "fan"):
            return
        self._marks_phase = 0
        if not self.app.store.settings.animations:
            return
        self._marks_frame()

    def _stop_marks(self) -> None:
        job = self._marks_job
        self._marks_job = None
        if job is None or self.window is None:
            return
        try:
            self.window.after_cancel(job)
        except tk.TclError:
            pass

    def _marks_frame(self) -> None:
        self._marks_job = None
        if not self.is_alive() or self.canvas is None:
            return
        marks = self.canvas.find_withtag("marks")
        if not marks:
            return
        self._marks_phase = (self._marks_phase + MARKS_STEP) % 8
        try:
            for item in marks:
                self.canvas.itemconfigure(item, dashoffset=self._marks_phase)
        except tk.TclError:
            return
        try:
            self._marks_job = self.window.after(ORBIT_INTERVAL, self._marks_frame)
        except tk.TclError:
            self._marks_job = None

    # -- rotating orbit ----------------------------------------------------
    def _start_orbit(self) -> None:
        """(Re)start the rotating rings, honouring the animations setting."""
        self._stop_orbit()
        if self.layout is None or self.layout.style != "ring":
            return
        self._orbit_phase = 0.0
        if not self.app.store.settings.animations:
            # Still drawn, just frozen: the rings are part of the look, not only
            # of the motion.
            self._draw_orbit()
            return
        self._orbit_frame()

    def _stop_orbit(self) -> None:
        job = self._orbit_job
        self._orbit_job = None
        if job is None or self.window is None:
            return
        try:
            self.window.after_cancel(job)
        except tk.TclError:
            pass

    def _orbit_frame(self) -> None:
        self._orbit_job = None
        if not self.is_alive() or self.canvas is None:
            return
        if self.layout is None or self.layout.style != "ring":
            return
        self._draw_orbit()
        self._orbit_phase = (self._orbit_phase + ORBIT_STEP) % 360.0
        try:
            self._orbit_job = self.window.after(ORBIT_INTERVAL, self._orbit_frame)
        except tk.TclError:
            self._orbit_job = None

    def _draw_orbit(self) -> None:
        """The moving part: two dashed rings and one dash between each item pair."""
        canvas = self.canvas
        if canvas is None:
            return
        canvas.delete("orbit")
        cx, cy, orbit, cell_w, cell_h, hub_radius = self._ring_geometry()
        disc_radius = min(self.layout.width, self.layout.height) / 2 - 2
        phase = self._orbit_phase
        # Outer dotted ring, hugging the rim.
        outer = disc_radius - 15
        if outer > 24:
            canvas.create_arc(cx - outer, cy - outer, cx + outer, cy + outer,
                              start=phase, extent=359.99, style="arc",
                              outline=ORBIT_RING, width=1, dash=(1, 6),
                              tags=("orbit",))
        # Inner dashed ring, spinning the other way. Opposing rotation is what
        # makes the dial read as a mechanism instead of one turning picture.
        inner = orbit - (math.hypot(cell_w, cell_h) / 2 + 14)
        if inner > hub_radius + 12:
            canvas.create_arc(cx - inner, cy - inner, cx + inner, cy + inner,
                              start=-phase * 0.75, extent=359.99, style="arc",
                              outline=ORBIT_RING_DIM, width=1, dash=(2, 8),
                              tags=("orbit",))
        # One short dash exactly between each pair of items, on their own orbit:
        # that segmentation is what the reference menu uses instead of a solid line.
        count = len(self.layout.cells)
        if count >= 2:
            step = 360.0 / count
            length = min(16.0, max(6.0, orbit * math.sin(math.radians(step / 2)) * 0.5))
            spin = phase * 0.5
            for index in range(count):
                angle = math.radians(spin + step * index + step / 2)
                dx, dy = math.cos(angle), math.sin(angle)
                tx, ty = -dy, dx
                canvas.create_line(cx + orbit * dx - tx * length / 2,
                                   cy + orbit * dy - ty * length / 2,
                                   cx + orbit * dx + tx * length / 2,
                                   cy + orbit * dy + ty * length / 2,
                                   fill=ORBIT_DASH, width=1, tags=("orbit",))
        # Moving parts sit above the disc but under the hub and the icons.
        if canvas.find_withtag("hub"):
            canvas.tag_lower("orbit", "hub")
        elif canvas.find_withtag("icon"):
            canvas.tag_lower("orbit", "icon")

    def _keep(self, photo: ImageTk.PhotoImage) -> None:
        # PhotoImage objects are garbage collected unless a reference survives.
        if not hasattr(self, "_photos"):
            self._photos = []
        if photo not in self._photos:
            self._photos.append(photo)

    def _highlight(self, index: int, active: bool) -> None:
        logging.getLogger("mesadock").info("hover: highlight idx=%s active=%s", index, active)
        if self.canvas is None or index >= len(self._hovered_items):
            return
        tag = "hl" + str(index)
        self.canvas.delete(tag)
        # Magnify: grow the hovered icon, restore it on leave.
        if index < len(getattr(self, "_item_photos", ())):
            normal, large = self._item_photos[index]
            target = large if (active and large is not None) else normal
            if target is not None:
                self.canvas.itemconfigure("iconitem" + str(index), image=target)
        if not active:
            return
        x, y, w, h = self._hovered_items[index]
        # Visible accent highlight: soft blue-tinted fill plus a bright blue border.
        theme.rounded_rect(self.canvas, x - 6, y - 6, x + w + 6, y + h + 6, radius=12,
                           fill="#0e7490",
                           outline="#67e8f9", width=2, tags=("hover", tag))
        self.canvas.tag_raise("item" + str(index))

    # -- interaction -------------------------------------------------------
    def _index_at(self, x: int, y: int) -> int:
        for index, (cx, cy, cw, ch) in enumerate(self._hovered_items):
            if cx - 6 <= x < cx + cw + 6 and cy - 6 <= y < cy + ch + 6:
                return index
        return -1

    def _on_motion(self, event) -> None:
        index = self._index_at(event.x, event.y)
        logging.getLogger("mesadock").info("hover: motion x=%s y=%s idx=%s (hover_index=%s)", event.x, event.y, index, self._hover_index)
        if index != self._hover_index:
            if self._hover_index >= 0:
                self._highlight(self._hover_index, False)
            self._hover_index = index
            if index >= 0:
                self._highlight(index, True)
            self._update_cursor(index)
        self.app._pointer_inside_panel(self, True)

    def _update_cursor(self, index: int) -> None:
        if self.canvas is None:
            return
        self.canvas.configure(cursor="hand2" if index >= 0 else "arrow")

    def _probe_pointer(self) -> None:
        """Mark the panel as hovered when it opens under the pointer."""
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
            # Right-clicking an item must offer actions on that item (Open / Remove).
            # It used to jump straight to the Manager, hiding the Remove commands.
            self.on_menu(self.folder, self.folder.items[index], event.x_root, event.y_root)
        else:
            self.app.show_dock_menu(self.folder, event.x_root, event.y_root)

    # -- lifetime ----------------------------------------------------------
    def _fade_in(self) -> None:
        settings = self.app.store.settings
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
        # Stop the orbit before the fade: an animation timer that outlives the
        # window would keep firing into a destroyed canvas.
        self._stop_orbit()
        self._stop_marks()
        settings = self.app.store.settings
        if self._anim_job and self.window is not None:
            try:
                self.window.after_cancel(self._anim_job)
            except tk.TclError:
                pass
            self._anim_job = None
        if animate and settings.animations and self.window is not None:
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
        self._stop_orbit()
        self._stop_marks()
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
        position = (self.window.winfo_rootx(), self.window.winfo_rooty())
        self._icon_size = self._resolve_icon_size()
        scale = getattr(self.monitor, "scale", 1.0) or 1.0
        # This must match _build exactly. It used to hard-code gap=10 while _build
        # scaled it, so every style change silently shrank the panel and left the
        # old, larger window frame behind on screen.
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
        # Re-place against the dock: the same anchor logic as _build, otherwise a
        # style change kept the panel at its old spot regardless of the new size.
        self.layout_origin = layout_mod.place_panel(anchor, self.layout, self.monitor.work)
        origin_x, origin_y = self.layout_origin
        position = (origin_x, origin_y)
        self.window.geometry(str(self.layout.width) + "x" + str(self.layout.height) + "+" + str(position[0]) + "+" + str(position[1]))
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
    """Shorten a name until it measurably fits, so it cannot overlap its neighbour.

    Measuring with the real font beats counting characters: "WWWW" is far wider
    than "iiii" at the same length, so a fixed character limit both clipped short
    names and let wide ones spill over the next cell.
    """
    text = (text or "").strip()
    if not text:
        return ""
    try:
        measure = tk.font.Font(font=theme.font(8)).measure
    except (tk.TclError, AttributeError):
        return _truncate(text, max(6, available // 7))
    if measure(text) <= available:
        return text
    shortened = text
    while shortened and measure(shortened + "\u2026") > available:
        shortened = shortened[:-1]
    return (shortened.rstrip() + "\u2026") if shortened else "\u2026"
