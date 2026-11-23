"""Application controller: owns the store, the dock windows and the panels."""
from __future__ import annotations

import logging
import time
import queue
import tkinter as tk
from typing import TYPE_CHECKING
from pathlib import Path

from ..core import archive as archive_mod
from ..core import layout as layout_mod
from ..core import paths
from ..core import portal as portal_mod
from ..core.i18n import set_lang, tr
from ..core.models import DockFolder, DockItem
from ..core.store import Store
from ..win32 import desktop, monitors, shell
from ..win32 import desktop_enabled
from . import theme
from .images import ImageCache
from .panel import Panel

if TYPE_CHECKING:
    from .dockwindow import DockWindow


class MesaDockApp:
    """Wires the stored profile to the live desktop."""

    def __init__(self, store: Store | None = None, show_manager: bool = False) -> None:
        paths.ensure_dirs()
        self.store = store or Store().load()
        if self.store.settings.language:
            set_lang(self.store.settings.language)
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("MesaDock")
        theme.apply_window_icon(self.root)
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
        self.peek_active = False
        self.docks_hidden = False
        self.search = None
        self._portal_signatures: dict[str, tuple] = {}
        self._portal_thread = None
        self._lbutton_down = False
        self._last_desktop_click: tuple[float, int, int] | None = None

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
                except Exception as exc:
                    logging.getLogger("mesadock").exception("Erro na fila Tk: %s", exc)
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
        self.start_portal_watcher()
        if not (self.store.settings.start_minimized if minimized is None else minimized):
            self.open_manager()
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.quit("main window closed"))
        self.root.bind_all("<Control-Shift-M>", lambda _e: self.open_manager())
        self.root.bind_all("<Control-Shift-D>", lambda _e: self.add_dock(tr("New dock"), "grid"))
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

                icon = str(icon_art.save_png(icon_art.dock_icon("grid", 64, item_count=0, dock_index=len(self.docks) + 1),
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

    def quit(self, reason: str = "unspecified") -> None:
        """Close every window and stop the app.

        ``reason`` goes to the log: when the docks vanished there was no way to
        tell a click on Quit from a crash or a Windows logoff.
        """
        if not self._running:
            return
        logging.getLogger("mesadock").info("Quit requested: %s", reason)
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
            self.notify(tr("Could not save: ") + str(exc), error=True)

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
                if self.docks_hidden:
                    self.docks[folder.id].set_hidden(True)
            else:
                dock.folder = folder
                dock.refresh()

    def prompt_new_dock(self) -> DockFolder | None:
        """Ask for a name, then create the dock (used by the tray menu)."""
        from tkinter import simpledialog

        name = simpledialog.askstring(tr("New dock"), tr("Name this dock:"), parent=self.root) or ""
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
        # No icon file is generated here: a new dock uses the built-in glyph for
        # its style, which follows the theme and the style the user picks later.
        self.touch()
        self.sync_docks()
        return folder

    # -- folder portals ----------------------------------------------------
    def prompt_new_portal(self, parent=None) -> DockFolder | None:
        """Ask for a folder and create a dock that mirrors it."""
        from tkinter import filedialog

        path = filedialog.askdirectory(parent=parent or self.root, mustexist=True,
                                       title=tr("Choose the folder this dock will show"))
        if not path:
            return None
        return self.add_portal(path)

    def add_portal(self, path: str, name: str | None = None) -> DockFolder:
        path = str(Path(path))
        folder = self.add_dock(name or portal_mod.default_name(path), "grid")
        folder.portal = path
        self._portal_signatures[folder.id] = portal_mod.signature(path)
        portal_mod.sync_items(folder)
        self.touch()
        self._refresh_dock_views(folder.id)
        return folder

    def set_portal_folder(self, folder_id: str, parent=None) -> None:
        from tkinter import filedialog

        folder = self.store.folder_by_id(folder_id)
        if folder is None or not folder.portal:
            return
        path = filedialog.askdirectory(parent=parent or self.root, mustexist=True, initialdir=folder.portal,
                                       title=tr("Choose the folder this dock will show"))
        if not path:
            return
        folder.portal = str(Path(path))
        self._portal_signatures[folder.id] = portal_mod.signature(folder.portal)
        portal_mod.sync_items(folder)
        self.touch()
        self._refresh_dock_views(folder.id)

    def open_portal_folder(self, folder: DockFolder) -> None:
        if not shell.launch(folder.portal):
            self.notify(tr("Could not open ") + folder.portal, error=True)

    def _refresh_dock_views(self, folder_id: str) -> None:
        dock = self.docks.get(folder_id)
        if dock is not None:
            dock.refresh()
        panel = self.panels.get(folder_id)
        if panel is not None:
            panel.rebuild()
        if self.manager is not None and self.manager.is_alive():
            self.manager.refresh_docks()
            if self.manager.selected_id == folder_id:
                self.manager.select_folder(folder_id)

    def start_portal_watcher(self) -> None:
        """Refresh portal docks now, then watch their folders in the background.

        The folders are read on a worker thread: a sleeping drive or an offline
        network share can take seconds to answer, and that must never freeze the
        docks. Only the result is handed to the Tk thread.
        """
        import threading

        # No scan here: the worker's first pass does it, so a slow share cannot
        # delay start-up. Until then the dock shows the items saved last time.
        if self._portal_thread is None:
            self._portal_thread = threading.Thread(target=self._watch_portals, name="mesadock-portals", daemon=True)
            self._portal_thread.start()

    def _watch_portals(self) -> None:
        log = logging.getLogger("mesadock")
        while self._running:
            try:
                watched = [(f.id, f.portal) for f in list(self.store.folders) if f.portal]
            except Exception:
                watched = []
            for folder_id, path in watched:
                if not self._running:
                    return
                try:
                    current = portal_mod.signature(path)
                    if current == self._portal_signatures.get(folder_id):
                        continue
                    entries = portal_mod.scan(path)
                except Exception as exc:  # one bad path must not stop the watcher
                    log.warning("portal: could not read %s: %s", path, exc)
                    continue
                self._enqueue_tk(lambda i=folder_id, p=path, s=current, e=entries: self._portal_changed(i, p, s, e))
            for _ in range(25):  # 2.5 s, in slices so quitting is not held up
                if not self._running:
                    return
                time.sleep(0.1)

    def _portal_changed(self, folder_id: str, path: str, current: tuple, entries: list | None) -> None:
        folder = self.store.folder_by_id(folder_id)
        if folder is None or folder.portal != path:
            return
        self._portal_signatures[folder_id] = current
        if entries is None:
            # Folder unreachable (drive unplugged, share offline): keep what the
            # dock shows, with its ids and custom icons, until it is back.
            return
        if portal_mod.sync_items(folder, entries):
            self.touch()
            self._refresh_dock_views(folder_id)

    def _portal_is_read_only(self, folder: DockFolder, adding: bool) -> bool:
        """Portal docks only mirror their folder; say so instead of changing it."""
        if not folder.portal:
            return False
        if adding:
            self.notify(tr("This dock shows a folder. Put the file in the folder itself."), error=True)
        else:
            self.notify(tr("This dock shows a folder. Remove the file from the folder itself."), error=True)
        return True

    # -- peek, hide and search ---------------------------------------------
    def toggle_peek(self) -> None:
        self.set_peek(not self.peek_active)

    def set_peek(self, active: bool) -> None:
        """Bring every dock above the open windows, or send them back."""
        if active and self.docks_hidden:
            self.set_docks_hidden(False)
        if active == self.peek_active:
            return
        self.peek_active = active
        if not active:
            self.close_all_panels()
        for dock in self.docks.values():
            dock.apply_layer()

    def toggle_docks_hidden(self) -> None:
        self.set_docks_hidden(not self.docks_hidden)

    def set_docks_hidden(self, hidden: bool) -> None:
        """Hide every dock for a clean desktop, or show them again."""
        if hidden == self.docks_hidden:
            return
        if hidden:
            self.peek_active = False
            self.close_all_panels()
        self.docks_hidden = hidden
        for dock in self.docks.values():
            dock.set_hidden(hidden)

    def open_search(self) -> None:
        from .search import SearchWindow

        if self.search is not None and self.search.is_alive():
            self.search.close()
            return
        self.search = SearchWindow(self)

    def _watch_desktop_double_click(self, x: int, y: int) -> None:
        """Double-click on empty wallpaper hides the docks; again shows them."""
        if not self.store.settings.hide_on_double_click or not desktop_enabled():
            return
        down, pressed_since = desktop.primary_button_state()
        pressed = pressed_since or (down and not self._lbutton_down)
        self._lbutton_down = down
        if not pressed:
            return
        now = time.monotonic()
        last = self._last_desktop_click
        if not desktop.is_desktop_background(x, y):
            self._last_desktop_click = None
            return
        if (last is not None and now - last[0] <= desktop.double_click_time()
                and abs(x - last[1]) <= 4 and abs(y - last[2]) <= 4):
            self._last_desktop_click = None
            # Give Explorer a moment to update the selection the click produced.
            self.root.after(140, self._desktop_double_clicked)
            return
        self._last_desktop_click = (now, x, y)

    def _desktop_double_clicked(self) -> None:
        if desktop.selected_icon_count() == 0:
            self.toggle_docks_hidden()

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
        self._portal_signatures.pop(folder_id, None)
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

    ITEM_ICON_TYPES = (".png", ".ico", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".exe", ".dll")

    def set_item_icon(self, folder_id: str, item_id: str, source: str | None) -> bool:
        """Give one item its own icon, or ``None`` to go back to the shortcut's.

        The chosen file is copied into the dock's data folder, so the icon keeps
        working if the original image is moved or deleted.
        """
        import shutil

        folder = self.store.folder_by_id(folder_id)
        item = folder.item_by_id(item_id) if folder is not None else None
        if item is None:
            return False
        old = item.icon
        if source:
            src = Path(source)
            if not src.is_file() or src.suffix.lower() not in self.ITEM_ICON_TYPES:
                self.notify(tr("Choose a PNG, ICO, JPG, BMP or EXE file"), error=True)
                return False
            target_dir = archive_mod.Archiver(self.store.active_profile.name).items_dir(folder.id) / "icons"
            target = target_dir / (item.id + src.suffix.lower())
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                if src.resolve() != target.resolve():
                    shutil.copy2(src, target)
            except OSError as exc:
                self.notify(tr("Could not save: ") + str(exc), error=True)
                return False
            item.icon = str(target)
        else:
            item.icon = ""
        # Drop cached renders of the old and the new source, then redraw.
        for source_path in {old, item.icon} - {""}:
            self.images.forget(source_path)
        self.images.clear()
        self.touch()
        panel = self.panels.get(folder_id)
        if panel is not None:
            panel.rebuild()
        dock = self.docks.get(folder_id)
        if dock is not None:
            dock.refresh()
        return True

    def choose_item_icon(self, folder_id: str, item_id: str, parent=None) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            parent=parent or self.root,
            title=tr("Choose an icon"),
            filetypes=[(tr("Images and programs"), " ".join("*" + ext for ext in self.ITEM_ICON_TYPES)),
                       (tr("All files"), "*.*")],
        )
        if path:
            self.set_item_icon(folder_id, item_id, path)

    # -- items -------------------------------------------------------------
    def add_paths_to_dock(self, folder_id: str, paths: list[str]) -> int:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return 0
        if self._portal_is_read_only(folder, adding=True):
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
            _msg = str(added) + (tr(" item added") if added == 1 else tr(" items added"))
            try:
                self.root.after(0, lambda m=_msg: self.notify(m))
            except tk.TclError:
                self.notify(_msg)
            logging.getLogger("mesadock").info("add: add_paths_to_dock done")
        else:
            _msg = tr("Nothing could be added")
            try:
                self.root.after(0, lambda: self.notify(_msg, error=True))
            except tk.TclError:
                self.notify(_msg, error=True)
        return added

    def add_url_to_dock(self, folder_id: str, url: str, name: str = "") -> bool:
        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return False
        if self._portal_is_read_only(folder, adding=True):
            return False
        archiver = archive_mod.Archiver(self.store.active_profile.name, self.store.settings.archive_mode)
        result = archiver.add_url(url, folder.id, name=name or None)
        if not result.ok or result.item is None:
            self.notify(result.message or tr("Could not add link"), error=True)
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
        if self._portal_is_read_only(folder, adding=False):
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
            self.notify(tr("Could not open ") + (item.name or path), error=True)
        elif self.peek_active:
            self.set_peek(False)

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
        self._watch_desktop_double_click(x, y)
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
            # Click mode closes when the pointer leaves both the panel and its dock
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
        
        try:
            px, py = self.root.winfo_pointerxy()
        except tk.TclError:
            px, py = -1, -1

        # Only auto-close when the pointer really left both the panel and its dock.
        for panel in list(self.panels.values()):
            if not panel.is_alive():
                self._panel_closed(panel)
                continue
            dock = self.docks.get(panel.folder.id)
            if panel.contains_point(px, py):
                return
            if dock is not None and dock.contains_point(px, py):
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
        menu.add_command(label=tr("Open"), command=lambda: self.toggle_panel(folder))
        menu.add_command(label=tr("Open Manager"), command=lambda: self.open_manager(select=folder.id))
        menu.add_separator()
        for style, label in (("grid", "Grid"), ("column", "Column"), ("row", "Row"), ("fan", "Fan"), ("ring", "Ring")):
            menu.add_command(label=tr("Style: ") + tr(label), command=lambda s=style: self.set_dock_style(folder.id, s))
        menu.add_separator()
        if folder.portal:
            menu.add_command(label=tr("Open folder"), command=lambda: self.open_portal_folder(folder))
            menu.add_command(label=tr("Change folder..."), command=lambda: self.set_portal_folder(folder.id))
        else:
            menu.add_command(label=tr("Add shortcuts..."), command=lambda: self.add_items_via_dialog(folder.id))
            menu.add_command(label=tr("Add web link") + "...", command=lambda: self.add_link_via_dialog(folder.id))
        menu.add_separator()
        menu.add_command(label=tr("Remove dock") if folder.portal else tr("Remove dock (restores items)"),
                         command=lambda: self.confirm_remove_dock(folder.id))
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def confirm_remove_dock(self, folder_id: str) -> None:
        from tkinter import messagebox

        folder = self.store.folder_by_id(folder_id)
        if folder is None:
            return
        if folder.portal:
            question = tr("Remove \"{name}\"?\n\nThe folder and its files are not touched.")
        else:
            question = tr("Remove \"{name}\"?\n\nItems are put back on the desktop.")
        if messagebox.askyesno(tr("Remove dock"), question.format(name=folder.name)):
            self.remove_dock(folder_id, restore=True)

    def add_items_via_dialog(self, folder_id: str) -> None:
        from tkinter import filedialog

        files = filedialog.askopenfilenames(title=tr("Add shortcuts and files"))
        if files:
            self.add_paths_to_dock(folder_id, list(files))

    def add_link_via_dialog(self, folder_id: str) -> None:
        from tkinter import simpledialog

        url = simpledialog.askstring(tr("Add web link"), tr("Address:"), parent=self.root)
        if url:
            self.add_url_to_dock(folder_id, url)

    def show_panel_menu(self, folder: DockFolder, item: DockItem, x: int, y: int) -> None:
        menu = tk.Menu(self.root, tearoff=0, bg=theme.BG_ELEVATED, fg=theme.TEXT,
                       activebackground=theme.ACCENT_SOFT, activeforeground=theme.TEXT,
                       borderwidth=0, font=theme.font(9))
        menu.add_command(label=tr("Open"), command=lambda: self.launch_item(folder, item))
        menu.add_separator()
        if folder.portal:
            menu.add_command(label=tr("Show in folder"), command=lambda: shell.reveal(item.path))
        else:
            menu.add_command(label=tr("Remove from dock (puts it back on the desktop)"),
                             command=lambda: self.confirm_remove(folder, item, restore=True))
            menu.add_command(label=tr("Remove from dock (leaves the original alone)"),
                             command=lambda: self.confirm_remove(folder, item, restore=False))
        menu.add_separator()
        menu.add_command(label=tr("Change icon..."),
                         command=lambda: self.choose_item_icon(folder.id, item.id))
        if item.icon:
            menu.add_command(label=tr("Use the original icon"),
                             command=lambda: self.set_item_icon(folder.id, item.id, None))
        menu.add_separator()
        menu.add_command(label=tr("Manage this dock..."),
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
            detail = tr("The shortcut goes back to the desktop.")
        else:
            detail = tr("The shortcut itself is not touched, it just leaves the dock.")
        if not messagebox.askyesno(
            tr("Remove from dock"),
            tr("Remove \"{item}\" from {dock}?").format(item=item.name, dock=folder.name) + "\n\n" + detail,
            parent=self.root,
        ):
            return
        self.remove_item(folder.id, item.id, restore=restore)
    # -- manager / tray ----------------------------------------------------
    def _apply_win11_effects(self, window) -> None:
        """Apply Windows 11 rounded corners and dark title bars via DWM."""
        try:
            import ctypes
            window.update_idletasks()
            
            # A forma mais infalivel: mandar o Windows procurar a janela pelo titulo exato
            title = window.title()
            hwnd = ctypes.windll.user32.FindWindowW(None, title)
            
            # Fallback caso mude de nome
            if not hwnd:
                hwnd = ctypes.windll.user32.GetParent(int(window.winfo_id()))
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            
            dwmapi = ctypes.windll.dwmapi
            
            # For ar barra de t tulo escura se o tema for dark
            if getattr(self.store.settings, "panel_theme", "dark") in ("dark", "auto"):
                value = ctypes.c_int(1)
                dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
                
            # For ar cantos arredondados nativos do Windows 11
            corner = ctypes.c_int(DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
        except Exception as exc:
            import logging
            logging.getLogger("mesadock").debug("Efeitos DWM ignorados (provavelmente SO incompativel): %s", exc)

    def open_manager(self, select: str | None = None, select_item: str | None = None) -> None:
        from .manager import ManagerWindow

        if self.manager is not None and self.manager.is_alive():
            self.manager.show()
            if select:
                self.manager.select_folder(select)
            if hasattr(self.manager, 'window'):
                self._apply_win11_effects(self.manager.window)
            return
        self.manager = ManagerWindow(self, select=select, select_item=select_item)
        self.manager.show()
        
        # Aplicamos com um pequeno delay para garantir que o Tkinter ja alocou o HWND da janela
        if hasattr(self.manager, 'window'):
            self.root.after(50, lambda: self._apply_win11_effects(self.manager.window))

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

