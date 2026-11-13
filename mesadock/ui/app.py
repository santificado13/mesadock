"""Application controller: owns the store, the dock windows and the panels."""
from __future__ import annotations

import logging
import time
import queue
import tkinter as tk
from pathlib import Path

from ..core import archive as archive_mod
from ..core import layout as layout_mod
from ..core import paths
from ..core.models import DockFolder, DockItem, Profile
from ..core.store import Store
from ..win32 import desktop, monitors, shell
from ..win32 import desktop_enabled
from . import theme
from .images import ImageCache
from .panel import Panel


class MesaDockApp:
    """Wires the stored profile to the live desktop."""

    def __init__(self, store: Store | None = None, show_manager: bool = False) -> None:
        paths.ensure_dirs()
        self.store = store or Store().load()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("MesaDock")
        theme.apply_ttk_theme(self.root)
        self.images = ImageCache()
        self.docks: dict[str, "DockWindow"] = {}
        self.panels: dict[str, Panel] = {}
        self.manager = None
        self.tray = None
        self._tk_queue = queue.Queue()
        self._pointer_job: str | None = None
        self._open_timer: str | None = None
        self._close_timer: str | None = None
        self._pointer_in_panel = False
        self._last_pointer = (0, 0)
        self._last_pressed = 0.0
        self._running = True
        self._monitor_cache: list = []
        self._monitor_cache_at = 0.0

    # -- monitors ----------------------------------------------------------
    def monitors(self, refresh: bool = False):
        now = time.monotonic()
        if refresh or not self._monitor_cache or now - self._monitor_cache_at > 15:
            self._monitor_cache = monitors.list_monitors()
            self._monitor_cache_at = now
        return self._monitor_cache

    def primary_monitor(self):
        return self.monitors()[0]

    def monitor_for(self, point: tuple[int, int]):
        for monitor in self.monitors():
            left, top, width, height = monitor.rect
            if left <= point[0] < left + width and top <= point[1] < top + height:
                return monitor
        return self.primary_monitor()

    def icon_cell(self, monitor) -> tuple[int, int]:
        return desktop.icon_grid_cell(monitor)

    # -- cross-thread Tk marshalling ---------------------------------------
    def _enqueue_tk(self, callback) -> None:
        """Queue a callback to run on the main/Tk thread (thread-safe)."""
        try:
            self._tk_queue.put(callback)
        except Exception:
            pass

    def _drain_tk_queue(self) -> None:
        """Run queued cross-thread callbacks on the Tk thread, then re-arm."""
        try:
            while True:
                callback = self._tk_queue.get_nowait()
                try:
                    callback()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.root.after(30, self._drain_tk_queue)
        except tk.TclError:
            pass

    # -- lifecycle ---------------------------------------------------------
    def start(self, minimized: bool | None = None) -> None:
        self.sync_docks()
        self._drain_tk_queue()
        self.start_pointer_loop()
        self.start_drop_watcher()
        self.start_tray()
        self.start_show_watcher()
        self.watch_monitors()
        if not (self.store.settings.start_minimized if minimized is None else minimized):
            self.open_manager()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.bind_all("<Control-Shift-M>", lambda _e: self.open_manager())
        self.root.bind_all("<Control-Shift-D>", lambda _e: self.add_dock("New dock", "grid"))
        # Escape has to reach the app level, not just the panel widget: with a ring
        # or fan panel the window sits on top of its own dock, so there was no way
        # to dismiss it and get back to the dock icon.
        self.root.bind_all("<Escape>", lambda _e: self.close_all_panels())
        if self.store.settings.auto_start != shell.autostart_enabled():
            shell.set_autostart(self.store.settings.auto_start)

    def start_show_watcher(self) -> None:
        """Open the Manager when another launch asks this instance to show it.

        The tray window already receives the message; this file check is the
        fallback for when the shell has no tray (Explorer restarting, lock
        screen) and covers a second launch from a different session.
        """
        try:
            request = paths.show_request_file()
            if request.exists():
                request.unlink()
                self.open_manager()
        except OSError:
            pass
        if self._running:
            self.root.after(700, self.start_show_watcher)

    def start_tray(self) -> None:
        """Add the tray icon when the shell accepts one."""
        self.tray = None
        if not desktop_enabled():
            return
        try:
            from .tray import TrayIcon

            icon = None
            try:
                from ..core import icons as icon_art

                icon = str(icon_art.save_png(icon_art.dock_icon("grid", 64, item_count=0),
                                             paths.icons_cache_dir() / "tray.png"))
            except Exception:
                icon = None
            self.tray = TrayIcon(self, icon)
            if not self.tray.start():
                logging.getLogger("mesadock").warning(
                    "Tray icon unavailable (%s); the app keeps running", self.tray.error)
                self.tray = None
        except Exception as exc:
            logging.getLogger("mesadock").warning("Tray icon failed: %s", exc)
            self.tray = None

    def watch_monitors(self) -> None:
        """Re-place docks when displays change (DPI, resolution, unplug)."""
        signature = self._monitor_signature()
        if signature != getattr(self, "_monitor_signature_value", None):
            first_run = getattr(self, "_monitor_signature_value", None) is None
            self._monitor_signature_value = signature
            self.monitors(refresh=True)
            if not first_run:
                for dock in self.docks.values():
                    dock._place_on_desktop()
                    dock.refresh()
        if self._running:
            self.root.after(4000, self.watch_monitors)

    def _monitor_signature(self) -> tuple:
        try:
            return tuple((m.rect, round(m.scale, 2)) for m in self.monitors())
        except Exception:
            return ()


        self.start()
        self.root.mainloop()

    def quit(self) -> None:
        self._running = False
        try:
            self.save()
        except Exception:
            pass
        for dock in list(self.docks.values()):
            dock.destroy()
        self.docks.clear()
        for panel in list(self.panels.values()):
            panel.hide(animate=False)
        if self.manager is not None:
            self.manager.close()
        if self.tray is not None:
            self.tray.stop()
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    # -- persistence -------------------------------------------------------
    def touch(self) -> None:
        self.store.dirty = True
        if getattr(self, "_save_job", None):
            try:
                self.root.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.root.after(800, self.save)

    def save(self) -> None:
        self._save_job = None
        try:
            self.store.save()
        except Exception as exc:  # pragma: no cover - reported to the user
            self.notify("Could not save: " + str(exc), error=True)

    # -- docks -------------------------------------------------------------
    def sync_docks(self) -> None:
        """Make the desktop match the active profile."""
        wanted = {folder.id: folder for folder in self.store.folders}
        for folder_id in list(self.docks):
            if folder_id not in wanted:
                self.docks.pop(folder_id).destroy()
                panel = self.panels.pop(folder_id, None)
                if panel is not None:
                    panel.hide(animate=False)
        for folder in self.store.folders:
            dock = self.docks.get(folder.id)
            if dock is None:
                from .dockwindow import DockWindow

                self.docks[folder.id] = DockWindow(self, folder)
            else:
                dock.folder = folder
                dock.refresh()

    def prompt_new_dock(self) -> DockFolder | None:
        """Ask for a name, then create the dock (used by the tray menu)."""
        from tkinter import simpledialog

        name = simpledialog.askstring("New dock", "Name this dock:", parent=self.root) or ""
        name = name.strip()
        if not name:
            return None
        return self.add_dock(name, "grid")


    def add_dock(self, name: str = "New dock", style: str = "grid") -> DockFolder:
        folder = DockFolder(name=name, style=style)
        monitor = self.primary_monitor()
        cell_w, cell_h = self.icon_cell(monitor)
        # Reserve the cells of the docks that already exist, otherwise a new dock
        # is placed exactly on top of an older one and looks like nothing happened.
        rects = list(desktop.icon_rects())
        size = self._dock_pixel_size(folder)
        for dock in self.docks.values():
            left, top, width, height = dock.rect()
            rects.append((int(left), int(top), max(int(width), size), max(int(height), size)))
        occupied = layout_mod.Occupancy(rects)
        x, y = layout_mod.first_free_cell(
            monitor.rect, (cell_w, cell_h), occupied,
            preferred=(monitor.rect[0], monitor.rect[1]), icon=size)
        folder.position = (int(x), int(y))
        self.store.add_folder(folder)
        self.touch()
        self.sync_docks()
        return folder

    def _dock_pixel_size(self, folder: DockFolder) -> int:
        """Side of a dock icon window in physical pixels for this monitor."""
        monitor = self.monitor_for(tuple(folder.position)) if folder.position else self.primary_monitor()
        scale = getattr(monitor, "scale", 1.0) or 1.0
        icon = folder.icon_size or self.store.settings.icon_size
        return int(max(48, min(160, round(icon * scale)))) + 12
    def remove_dock(self, folder_id: str, restore: bool = True) -> None:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return
        if restore:
            archiver = archive_mod.Archiver(self.store.active_profile.name, self.store.settings.archive_mode)
            archiver.restore_all(folder.items)
        self.store.remove_folder(folder_id)
        self.touch()
        self.sync_docks()

    def rename_dock(self, folder_id: str, name: str) -> None:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return
        folder.name = (name or "").strip() or folder.name
        self.touch()
        dock = self.docks.get(folder_id)
        if dock is not None:
            dock.refresh()

    def set_dock_style(self, folder_id: str, style: str) -> None:
        folder = self.store.folder_by_id(folder_id)
        if folder is None or style not in ("grid", "column", "row", "fan", "ring"):
            return
        folder.style = style
        self.touch()
        dock = self.docks.get(folder_id)
        if dock is not None:
            dock.refresh()
        panel = self.panels.get(folder_id)
        if panel is not None:
            panel.rebuild()

    def set_dock_icon(self, folder_id: str, image_path: str) -> None:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return
        folder.icon = image_path
        self.images.clear()
        self.touch()
        dock = self.docks.get(folder_id)
        if dock is not None:
            dock.refresh()

    # -- items -------------------------------------------------------------
    def add_paths_to_dock(self, folder_id: str, paths: list[str]) -> int:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return 0
        archiver = archive_mod.Archiver(self.store.active_profile.name, self.store.settings.archive_mode)
        added = 0
        logging.getLogger("mesadock").info("add: archiving %d path(s)", len(paths))
        for path in paths:
            result = archiver.add_from_path(path, folder.id)
            if result.ok and result.item is not None:
                folder.add_item(result.item)
                added += 1
        logging.getLogger("mesadock").info("add: archived, added=%d", added)
        if added:
            self.touch()
            dock = self.docks.get(folder_id)
            if dock is not None:
                dock.refresh()
                logging.getLogger("mesadock").info("add: dock refreshed")
            panel = self.panels.get(folder_id)
            if panel is not None:
                panel.rebuild()
                logging.getLogger("mesadock").info("add: panel rebuilt")
            logging.getLogger("mesadock").info("add: scheduling notify (deferred)")
            _msg = str(added) + (" item added" if added == 1 else " items added")
            try:
                self.root.after(0, lambda m=_msg: self.notify(m))
            except tk.TclError:
                self.notify(_msg)
            logging.getLogger("mesadock").info("add: add_paths_to_dock done")
        else:
            _msg = "Nothing could be added"
            try:
                self.root.after(0, lambda: self.notify(_msg, error=True))
            except tk.TclError:
                self.notify(_msg, error=True)
        return added

    def add_url_to_dock(self, folder_id: str, url: str, name: str = "") -> bool:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return False
        archiver = archive_mod.Archiver(self.store.active_profile.name, self.store.settings.archive_mode)
        result = archiver.add_url(url, folder.id, name=name or None)
        if not result.ok or result.item is None:
            self.notify(result.message or "Could not add link", error=True)
            return False
        folder.add_item(result.item)
        self.touch()
        dock = self.docks.get(folder_id)
        if dock is not None:
            dock.refresh()
        panel = self.panels.get(folder_id)
        if panel is not None:
            panel.rebuild()
        return True

    def remove_item(self, folder_id: str, item_id: str, restore: bool = True) -> None:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return
        item = folder.item_by_id(item_id)
        if item is None:
            return
        if restore:
            archiver = archive_mod.Archiver(self.store.active_profile.name, self.store.settings.archive_mode)
            archiver.release_item(item)
        folder.remove_item(item_id)
        self.touch()
        dock = self.docks.get(folder_id)
        if dock is not None:
            dock.refresh()
        panel = self.panels.get(folder_id)
        if panel is not None:
            panel.rebuild()

    def launch_item(self, folder: DockFolder, item: DockItem) -> None:
        path = item.path or item.target
        if item.kind == "url":
            ok = shell.launch(item.target or path)
        elif item.kind == "folder":
            ok = shell.open_with(item.target or path, "open")
        else:
            ok = shell.launch(path)
        if not ok:
            self.notify("Could not open " + (item.name or path), error=True)

    # -- panels ------------------------------------------------------------
    def open_panel(self, folder: DockFolder, force: bool = False) -> None:
        existing = self.panels.get(folder.id)
        if existing is not None and existing.is_alive():
            return
        dock = self.docks.get(folder.id)
        anchor = dock.rect() if dock is not None else (0, 0, 64, 64)
        monitor = self.monitor_for((anchor[0] + anchor[2] // 2, anchor[1] + anchor[3] // 2))
        panel = Panel(
            self,
            folder,
            anchor,
            monitor,
            on_launch=self.launch_item,
            on_edit=lambda f, item_id: self.open_manager(select=f.id, select_item=item_id),
            on_menu=self.show_panel_menu,
            on_close=lambda p: self.panels.pop(folder.id, None),
        )
        self.panels[folder.id] = panel

    def close_panel(self, folder_id: str) -> None:
        panel = self.panels.pop(folder_id, None)
        if panel is not None:
            panel.hide()

    def close_panels(self, except_dock: str | None = None) -> None:
        for folder_id in list(self.panels):
            if folder_id != except_dock:
                self.close_panel(folder_id)

    def close_all_panels(self) -> None:
        """Dismiss every open panel so the dock icons are reachable again.

        Ring and Fan panels centre on their dock and cover it, so the dock icon
        itself cannot be clicked to toggle the panel shut. Escape is the way out,
        but the global binding pointed at a method that was never defined, which
        made the shortcut fail silently with AttributeError.
        """
        self._cancel_timer("open")
        self._cancel_timer("close")
        self.close_panels()
    def toggle_panel(self, folder: DockFolder) -> None:
        panel = self.panels.get(folder.id)
        if panel is not None and panel.is_alive():
            self.close_panel(folder.id)
        else:
            self.close_panels()
            self.open_panel(folder)

    def _panel_opened(self, panel: Panel) -> None:
        self._cancel_timer("open")
        for folder_id, other in list(self.panels.items()):
            if other is not panel:
                self.close_panel(folder_id)
        self.panels[panel.folder.id] = panel

    def _panel_closed(self, panel: Panel) -> None:
        self.panels.pop(panel.folder.id, None)

    def _pointer_inside_panel(self, panel: Panel, inside: bool) -> None:
        self._pointer_in_panel = inside
        if inside:
            self._cancel_timer("close")

    def _panel_pressed(self, panel: Panel) -> None:
        self._last_pressed = time.monotonic()

    # -- hover / auto-close loop -------------------------------------------
    def start_pointer_loop(self) -> None:
        if self._pointer_job is None:
            self._pointer_job = self.root.after(70, self._poll_pointer)

    def _poll_pointer(self) -> None:
        self._pointer_job = None
        if not self._running:
            return
        try:
            x, y = self.root.winfo_pointerxy()
        except tk.TclError:
            return
        self._last_pointer = (x, y)
        over_dock = next((d for d in self.docks.values() if d.contains_point(x, y)), None)
        over_panel = next((p for p in self.panels.values() if p.contains_point(x, y)), None)
        if over_panel is not None:
            self._cancel_timer("close")
        if self._opens_on_hover():
            if over_dock is not None:
                self._cancel_timer("close")
                if over_dock.folder.id not in self.panels:
                    self._schedule_open(over_dock.folder)
            elif over_panel is None:
                self._schedule_close()
        elif self.panels and over_panel is None and over_dock is None:
            # Click mode used to have no closing gesture at all: once a panel was
            # open, moving the pointer away left it on screen forever. Closing when
            # the pointer leaves both the panel and its dock is the expected
            # behaviour in either mode.
            self._schedule_close()
        self._pointer_job = self.root.after(70, self._poll_pointer)
    def _schedule_open(self, folder: DockFolder) -> None:
        if self._open_timer is not None:
            return
        delay = max(0, int(self.store.settings.hover_delay_ms))
        self._open_timer = self.root.after(delay, lambda: self._open_now(folder))

    def _open_now(self, folder: DockFolder) -> None:
        self._open_timer = None
        self.close_panels(except_dock=folder.id)
        self.open_panel(folder)

    def _schedule_close(self) -> None:
        if self._close_timer is not None:
            return
        self._close_timer = self.root.after(320, self._close_now)

    def _close_now(self) -> None:
        self._close_timer = None
        if not self.panels:
            return
        if not self._hover_enabled():
            return
        # Only auto-close when the pointer really left both the panel and its dock.
        for panel in list(self.panels.values()):
            if not panel.is_alive():
                self._panel_closed(panel)
                continue
            dock = self.docks.get(panel.folder.id)
            if panel.contains_point(*self._last_pointer):
                return
            if dock is not None and dock.contains_point(*self._last_pointer):
                return
            self.close_panel(panel.folder.id)

    def _hover_enabled(self) -> bool:
        """True when the pointer can open a panel and should close it again."""
        return not getattr(self, "_pin_panels", False)

    def _opens_on_hover(self) -> bool:
        """True only when hovering is the configured open gesture."""
        return self.store.settings.open_trigger == "hover" and not getattr(self, "_pin_panels", False)

    def pin_panels(self, pinned: bool = True) -> None:
        """Keep panels open regardless of pointer movement (previews, tests)."""
        self._pin_panels = pinned

    def _cancel_timer(self, which: str) -> None:
        attribute = "_open_timer" if which == "open" else "_close_timer"
        job = getattr(self, attribute)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
            setattr(self, attribute, None)

    def pointer_entered_dock(self, dock) -> None:
        if self.store.settings.open_trigger == "hover":
            self._cancel_timer("close")
            self._schedule_open(dock.folder)
    def pointer_left_dock(self, dock) -> None:
        if self.store.settings.open_trigger == "hover":
            self._schedule_close()

    def dock_pressed(self, dock) -> None:
        self._last_pressed = time.monotonic()

    # -- window layering ---------------------------------------------------
    def _attach_to_desktop(self, window) -> bool:
        """Keep a window on the desktop layer instead of floating over apps.

        send_to_bottom pushed the window *below the wallpaper*, where it stayed
        invisible. sit_above_desktop parks it just above the desktop instead, so
        it is visible and clickable while still sitting behind normal windows.
        """
        if not self.store.settings.attach_to_desktop:
            return False
        try:
            hwnd = int(window.winfo_id())
        except tk.TclError:
            return False
        desktop.apply_desktop_window_styles(hwnd)
        return desktop.sit_above_desktop(hwnd)

    def register_drop_target(self, window, callback) -> None:
        try:
            from ..win32 import drops

            def deferred(paths):
                # The drop callback fires inside a Windows message callback (the
                # WM_DROPFILES WNDPROC). add_paths_to_dock drives Tk (canvas
                # redraws, geometry changes), which is not re-entrant, so it must
                # run on the Tk event loop, outside the message handler.
                # No Tcl call here: the WNDPROC runs inside Tk's own event loop,
                # so calling root.after re-enters Tcl and panics (abort). Queue it
                # and let _drain_tk_queue run it on the Tk thread instead.
                self._enqueue_tk(lambda p=paths: callback(p))

            drops.accept_drops(window, deferred)
        except Exception:
            pass

    def start_drop_watcher(self) -> None:
        """Highlight the dock under the pointer during a drag, and drop on release."""
        try:
            from ..win32 import drops

            self._drop_watcher = drops.DropWatcher(
                self,
                hit_test=self._dock_at,
                on_enter=self._drop_enter,
                on_leave=self._drop_leave,
                on_drop=self._drop_finish,
            )
            self._drop_watcher.start()
        except Exception:
            self._drop_watcher = None

    def _dock_at(self, x: int, y: int):
        for dock in self.docks.values():
            if dock.contains_point(x, y):
                return dock
        return None

    def _drop_enter(self, dock) -> None:
        dock.set_drop_highlight(True)

    def _drop_leave(self, dock) -> None:
        dock.set_drop_highlight(False)

    def _drop_finish(self, dock, paths: list[str]) -> None:
        dock.set_drop_highlight(False)
        self.add_paths_to_dock(dock.folder.id, paths)


    # -- menus -------------------------------------------------------------
    def show_dock_menu(self, folder: DockFolder, x: int, y: int) -> None:
        menu = tk.Menu(self.root, tearoff=0, bg=theme.BG_ELEVATED, fg=theme.TEXT,
                       activebackground=theme.ACCENT_SOFT, activeforeground=theme.TEXT,
                       borderwidth=0, font=theme.font(9))
        menu.add_command(label="Open", command=lambda: self.toggle_panel(folder))
        menu.add_command(label="Open Manager", command=lambda: self.open_manager(select=folder.id))
        menu.add_separator()
        for style, label in (("grid", "Grid"), ("column", "Column"), ("row", "Row"), ("fan", "Fan"), ("ring", "Ring")):
            menu.add_command(label="Style: " + label, command=lambda s=style: self.set_dock_style(folder.id, s))
        menu.add_separator()
        menu.add_command(label="Add shortcuts...", command=lambda: self.add_items_via_dialog(folder.id))
        menu.add_command(label="Add web link...", command=lambda: self.add_link_via_dialog(folder.id))
        menu.add_separator()
        menu.add_command(label="Remove dock (restores items)", command=lambda: self.confirm_remove_dock(folder.id))
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def confirm_remove_dock(self, folder_id: str) -> None:
        from tkinter import messagebox

        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return
        if messagebox.askyesno("Remove dock", "Remove \"" + folder.name + "\"?\n\nItems are put back on the desktop."):
            self.remove_dock(folder_id, restore=True)

    def add_items_via_dialog(self, folder_id: str) -> None:
        from tkinter import filedialog

        files = filedialog.askopenfilenames(title="Add shortcuts and files")
        if files:
            self.add_paths_to_dock(folder_id, list(files))

    def add_link_via_dialog(self, folder_id: str) -> None:
        from tkinter import simpledialog

        url = simpledialog.askstring("Add web link", "Address:", parent=self.root)
        if url:
            self.add_url_to_dock(folder_id, url)

    def show_panel_menu(self, folder: DockFolder, item: DockItem, x: int, y: int) -> None:
        menu = tk.Menu(self.root, tearoff=0, bg=theme.BG_ELEVATED, fg=theme.TEXT,
                       activebackground=theme.ACCENT_SOFT, activeforeground=theme.TEXT,
                       borderwidth=0, font=theme.font(9))
        menu.add_command(label="Open", command=lambda: self.launch_item(folder, item))
        menu.add_separator()
        menu.add_command(label="Remove from dock (puts it back on the desktop)",
                         command=lambda: self.confirm_remove(folder, item, restore=True))
        menu.add_command(label="Remove from dock (leaves the original alone)",
                         command=lambda: self.confirm_remove(folder, item, restore=False))
        menu.add_separator()
        menu.add_command(label="Manage this dock...",
                         command=lambda: self.open_manager(select=folder.id, select_item=item.id))
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def confirm_remove(self, folder: DockFolder, item: DockItem, restore: bool = True) -> None:
        """Ask before dropping an item from a dock.

        Removing used to happen on a single menu click with no confirmation, so a
        stray double-click on the menu silently took a shortcut out of the dock.
        """
        from tkinter import messagebox

        if restore:
            detail = "The shortcut goes back to the desktop."
        else:
            detail = "The shortcut itself is not touched, it just leaves the dock."
        if not messagebox.askyesno(
            "Remove from dock",
            "Remove \"" + item.name + "\" from " + folder.name + "?\n\n" + detail,
            parent=self.root,
        ):
            return
        self.remove_item(folder.id, item.id, restore=restore)
    # -- manager / tray ----------------------------------------------------
    def open_manager(self, select: str | None = None, select_item: str | None = None) -> None:
        from .manager import ManagerWindow

        if self.manager is not None and self.manager.is_alive():
            self.manager.show()
            if select:
                self.manager.select_folder(select)
            return
        self.manager = ManagerWindow(self, select=select, select_item=select_item)
        self.manager.show()

    def closed_manager(self) -> None:
        self.manager = None

    def notify(self, message: str, error: bool = False) -> None:
        """Show a short toast; falls back to the status bar or console."""
        if self.manager is not None and self.manager.is_alive():
            self.manager.set_status(message, error=error)
            return
        if self.tray is not None:
            try:
                if self.tray.notify(message):
                    return
            except Exception:
                pass
        print(("[error] " if error else "") + message)

    # -- profiles ----------------------------------------------------------
    def switch_profile(self, index: int) -> None:
        for panel in list(self.panels.values()):
            panel.hide(animate=False)
        self.panels.clear()
        self.store.select_profile(index)
        self.touch()
        self.sync_docks()

    def add_profile(self, name: str) -> None:
        self.store.add_profile(name)
        self.touch()
        self.switch_profile(len(self.store.profiles) - 1)

    def delete_profile(self, index: int) -> None:
        if self.store.delete_profile(index):
            self.touch()
            self.switch_profile(self.store.active_profile_index)

    # -- settings ----------------------------------------------------------
    def apply_settings(self) -> None:
        settings = self.store.settings
        for dock in self.docks.values():
            dock.refresh()
        for panel in list(self.panels.values()):
            panel.rebuild()
        if shell.is_windows() and settings.auto_start != shell.autostart_enabled():
            shell.set_autostart(settings.auto_start)
        self.touch()

    def emergency_restore_all(self) -> int:
        """Put every archived desktop item back (uninstall-time safety net)."""
        archiver = archive_mod.Archiver(self.store.active_profile.name, self.store.settings.archive_mode)
        restored = 0
        for profile in self.store.profiles:
            local = archive_mod.Archiver(profile.name, self.store.settings.archive_mode)
            for folder in profile.folders:
                restored += local.restore_all(folder.items)
        directories = [paths.archive_dir()]
        for directory in directories:
            if not directory.exists():
                continue
            for sub in list(directory.iterdir()):
                try:
                    from ..core.archive import user_desktop_dirs

                    target_dir = user_desktop_dirs()[0] if user_desktop_dirs() else Path.home() / "Desktop"
                    if sub.is_dir():
                        for child in list(sub.iterdir()):
                            name = child.name.split("_", 1)[-1] if "_" in child.name else child.name
                            destination = target_dir / name
                            if not destination.exists():
                                import shutil

                                shutil.move(str(child), str(destination))
                                restored += 1
                except OSError:
                    continue
        return restored
