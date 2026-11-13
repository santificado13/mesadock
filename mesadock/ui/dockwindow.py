"""One collapsed dock on the desktop: a single icon that fans out on hover."""
from __future__ import annotations

import tkinter as tk
# tk.font is a submodule, not an attribute of the tkinter package: without this
# import every measurement raised AttributeError, was swallowed by the except
# below, and fell back to a character-count guess. That is why "IA ASSISTENTES"
# was cut to "IA ASSI..." even though the measuring code looked correct.
import tkinter.font as tkfont

from PIL import ImageTk

from ..core import layout as layout_mod
from ..core.models import DockFolder
from . import theme
from .images import ImageCache, folder_source, prepare_canvas

ICON_PAD = 8
DRAG_THRESHOLD = 5


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
        self._photos: list[ImageTk.PhotoImage] = []
        self._drop_target = None
        size = self._pixel_size()
        self.window = tk.Toplevel(app.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", False)
        self.window.configure(bg=theme.TRANSPARENT_KEY)
        x, y = self.position()
        self.window.geometry(str(size) + "x" + str(size) + "+" + str(x) + "+" + str(y))
        prepare_canvas(self.window, theme.TRANSPARENT_KEY)
        self.canvas = tk.Canvas(self.window, width=size, height=size, bg=theme.TRANSPARENT_KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._bind()
        self._draw()
        self.app.root.after(30, self._place_on_desktop)
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
        if not self.app.store.settings.attach_to_desktop:
            # "Off" means the dock floats above every window. This used to clear
            # -topmost instead, so the dock became an ordinary window and any
            # maximised app (a browser, Explorer) simply covered it: the dock
            # appeared to vanish until the app was restarted.
            self._set_topmost(True)
            return
        try:
            hwnd = int(self.window.winfo_id())
        except tk.TclError:
            return
        from ..win32 import desktop

        # Layering: keep the dock in the normal z-order, parked directly above the
        # desktop. Reparenting into Progman looked correct but placed the dock
        # behind SHELLDLL_DefView, so it was invisible; send_to_bottom alone put it
        # below the wallpaper. Siting it above the desktop is the only ordering that
        # stays visible while still sitting behind ordinary application windows.
        # -topmost must be cleared here too: after a stay in floating mode the dock
        # kept the flag and stayed above every window even in desktop mode.
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

    def _ensure_on_desktop(self) -> None:
        """Re-assert the layering after Tk recreates or moves the window.

        Tk destroys and recreates the toplevel when the geometry or -topmost
        changes, which silently drops the previous SetWindowPos: the dock then
        disappears behind other windows until the app is restarted. A single
        delayed retry raced with that recreation, so the call is repeated a few
        times over a short window; every step is idempotent.
        """
        if self._reassert_job is not None:
            try:
                self.app.root.after_cancel(self._reassert_job)
            except tk.TclError:
                pass
            self._reassert_job = None
        self._reassert_step(0)

    def _reassert_step(self, step: int) -> None:
        self._reassert_job = None
        if not self.is_alive():
            return
        if self.app.store.settings.attach_to_desktop:
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
        """Keep the dock above the desktop even after "Show desktop" (Win+D).

        Win+D raises Progman to the front of the z-order. The dock is anchored
        directly above the desktop, so it ended up *behind* it and looked like it
        had vanished until MesaDock was restarted. A cheap neighbour-chain check on
        a timer re-anchors it as soon as that happens, so the dock is always there.
        """
        self._watch_job = None
        if not self.is_alive():
            return
        try:
            from ..win32 import desktop

            if (
                self.app.store.settings.attach_to_desktop
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
        canvas = self.canvas
        canvas.delete("all")
        size = self._pixel_size()
        # The window is an icon plus a caption, so it is only as wide as the name
        # needs. Using the square icon size for both axes is what forced long
        # names to wrap and lose their last word.
        width = self._dock_width()
        icon_x = width / 2
        inset = ICON_PAD // 2
        # The name sits in a strip under the icon, so the window is taller than it
        # is wide. Without it every dock looked identical: a coloured glyph with a
        # count badge and no way to tell two docks apart.
        label = self._label_text()
        label_height = self._label_height() if label else 0
        icon_height = size
        if self._drop_highlight:
            theme.rounded_rect(canvas, 1, 1, width - 1, size - 1, radius=14,
                               fill=theme.blend("#0d1016", "#34d399", 0.28), outline="#34d399", width=2)
        elif self._hover:
            theme.rounded_rect(canvas, 1, 1, width - 1, size - 1, radius=14,
                               fill=theme.blend("#0d1016", "#5ea2ff", 0.16), outline="#3d5170", width=1)
        cache: ImageCache = self.app.images
        icon_size = size - ICON_PAD * 2
        source = folder_source(self.folder)
        try:
            photo = cache.photo(source, icon_size)
        except Exception:
            photo = None
        if photo is not None:
            self._photos = [photo]
            canvas.create_image(icon_x, icon_height / 2, image=photo)
        count = len(self.folder.items)
        if count:
            badge = self._badge(count, size)
            if badge is not None:
                self._photos.append(badge)
                canvas.create_image(width - inset - 4, inset + 4, image=badge, anchor="ne")
        else:
            pass
        if label:
            font = self._label_font()
            baseline = icon_height + label_height / 2
            # One-pixel shadow keeps the name legible over light wallpapers, where a
            # pale grey label used to wash out completely.
            canvas.create_text(
                icon_x + 1, baseline + 1,
                text=label, fill="#05070b", font=font,
                width=width - 2,
            )
            canvas.create_text(
                icon_x, baseline,
                text=label, fill=theme.TEXT if self._hover else "#e8eefb",
                font=font, width=width - 2,
            )
        self._resize_window(width, icon_height + label_height)

    def _label_font(self):
        return theme.font(9, "bold")

    def _label_text(self) -> str:
        """Dock name, shortened only when it cannot be shown in full.

        The measurement used to use font(8) while the label was drawn in
        font(9, bold), so it systematically under-measured by about 17%:
        "IA ASSISTENTES" measured 77px but was painted 90px wide, so Tk
        wrapped it to "IA ASSISTENT..." with the end of the word simply gone.
        Measuring with the font that actually draws is the only way the answer
        can be trusted.
        the only way the answer can be trusted.
        """
        name = (self.folder.name or "").strip()
        if not name:
            return ""
        available = self._label_space()
        try:
            measure = tkfont.Font(font=self._label_font(), root=self.app.root).measure
        except (tk.TclError, AttributeError):
            limit = max(6, int(available / 9))
            return name if len(name) <= limit else name[:max(1, limit - 1)].rstrip() + "\u2026"
        if measure(name) <= available:
            return name
        shortened = name
        while shortened and measure(shortened + "\u2026") > available:
            shortened = shortened[:-1]
        return (shortened.rstrip() + "\u2026") if shortened else "\u2026"

    def _label_space(self) -> int:
        """Pixels available for the name inside the dock window."""
        return max(24, self._dock_width() - 4)

    def _label_width(self) -> int:
        """Width the dock window needs so the whole name fits on one line.

        A dock is an icon with a caption, not a fixed square: widening it beats
        truncating the name, because the name is the only thing telling two
        docks apart. The icon stays centred over the wider strip.
        """
        name = (self.folder.name or "").strip()
        size = self._pixel_size()
        if not name:
            return size
        try:
            measure = tkfont.Font(font=self._label_font(), root=self.app.root).measure
        except (tk.TclError, AttributeError):
            return size
        # Long names would otherwise stretch a dock across the screen; past that
        # point the label falls back to an ellipsis, which _label_text handles.
        return int(min(max(size, measure(name) + 6), size * 2.6))

    def _dock_width(self) -> int:
        return max(self._pixel_size(), self._label_width())

    def _label_height(self) -> int:
        return int(18 * (getattr(self.app.monitor_for(self.position()), "scale", 1.0) or 1.0))

    def _resize_window(self, width: int, height: int) -> None:
        """Grow the window downwards so the name has room, keeping the icon in place."""
        try:
            x, y = self.position()
            current_h = self.window.winfo_height()
            if current_h == height and self.window.winfo_width() == width:
                return
            self.canvas.configure(height=height, width=width)
            self.window.geometry(str(int(width)) + "x" + str(int(height)) + "+" + str(int(x)) + "+" + str(int(y)))
        except tk.TclError:
            pass

    def _badge(self, count: int, size: int) -> ImageTk.PhotoImage | None:
        from ..core import icons as icon_art

        accent = icon_art.STYLE_COLOURS.get(self.folder.style, "blue")
        diameter = max(18, int(size * 0.30))
        image = icon_art.self_badge(diameter * 3, count, accent).resize((diameter, diameter))
        try:
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

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
            # Schedule panel toggle with delay to allow double-click detection
            if self._click_job is not None:
                try:
                    self.app.root.after_cancel(self._click_job)
                except tk.TclError:
                    pass
            self._click_job = self.app.root.after(200, lambda: self.app.toggle_panel(self.folder))
        self._drag_origin = None

    def _on_double_click(self, _event) -> None:
        # Cancel pending single-click action
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
        left, top, width, height = self.rect()
        return left <= x < left + width and top <= y < top + height
