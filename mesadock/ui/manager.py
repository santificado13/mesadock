"""The Manager window: docks, items, settings, profiles and about.

One Toplevel owned by MesaDockApp. It edits the same Store the desktop docks
read from, so every change here is reflected on the desktop immediately.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from ..core import archive as archive_mod
from ..core import paths
from ..core.models import DOCK_STYLE_LABELS, DOCK_STYLES
from ..core import i18n
from ..core.i18n import tr
from . import theme
from .images import folder_source, item_source

WINDOW_SIZE = (1020, 680)
SIDEBAR_WIDTH = 250
KIND_LABELS = {
    "shortcut": "Shortcut",
    "file": "File",
    "folder": "Folder",
    "url": "Web link",
    "app": "App",
}


class ManagerWindow:
    """The single window where docks are created and configured."""

    def __init__(self, app, select: str | None = None, select_item: str | None = None) -> None:
        self.app = app
        self.selected_id = select
        self.selected_item_id = select_item
        self._closed = False
        self._photos: list = []
        self._row_widgets: dict[str, tk.Frame] = {}
        self._status_job = None

        self.window = tk.Toplevel(app.root)
        self.window.title("MesaDock Manager")
        theme.apply_window_icon(self.window)
        self.window.geometry(str(WINDOW_SIZE[0]) + "x" + str(WINDOW_SIZE[1]))
        self.window.minsize(880, 560)
        self.window.configure(bg=theme.BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda _event: self.close())
        # shortcuts the README advertises
        self.window.bind("<Delete>", lambda _event: self._remove_item())
        self.window.bind("<Control-a>", lambda _event: self._add_files())

        self._build_header()
        body = tk.Frame(self.window, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self._build_sidebar(body)
        self._build_main(body)
        self._build_status()

        self.refresh_docks()
        if self.selected_id is None and self.app.store.folders:
            self.selected_id = self.app.store.folders[0].id
        self.select_folder(self.selected_id)
        if select_item:
            self.select_item(select_item)

    # -- construction ------------------------------------------------------
    def _build_header(self) -> None:
        header = tk.Frame(self.window, bg=theme.BG)
        header.pack(fill="x", padx=18, pady=(16, 12))
        left = tk.Frame(header, bg=theme.BG)
        left.pack(side="left")
        tk.Label(left, text="MesaDock", bg=theme.BG, fg=theme.TEXT,
                 font=theme.font(17, "bold")).pack(anchor="w")
        tk.Label(left, text=tr("Manager"), bg=theme.BG, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(anchor="w")

        right = tk.Frame(header, bg=theme.BG)
        right.pack(side="right")
        tk.Label(right, text=tr("Profile"), bg=theme.BG, fg=theme.TEXT_MUTED,
                 font=theme.font(8)).pack(side="left", padx=(0, 8))
        self.profile_var = tk.StringVar(value=self.app.store.active_profile.name)
        self.profile_box = ttk.Combobox(right, textvariable=self.profile_var, state="readonly",
                                        width=18, values=self._profile_names())
        self.profile_box.pack(side="left")
        self.profile_box.bind("<<ComboboxSelected>>", self._on_profile_changed)
        ttk.Button(right, text=tr("New profile"), style="Ghost.TButton",
                   command=self._new_profile).pack(side="left", padx=(8, 0))
        ttk.Button(right, text="EN" if i18n.get_lang() == "pt" else "PT", style="Ghost.TButton",
                   command=self._toggle_lang).pack(side="left", padx=(8, 0))

    def _profile_names(self) -> list[str]:
        return [profile.name for profile in self.app.store.profiles]

    def _toggle_lang(self) -> None:
        """Toggle the UI language and rebuild the Manager."""
        i18n.set_lang("en" if i18n.get_lang() == "pt" else "pt")
        self.window.destroy()
        self.app.closed_manager()
        self.app.open_manager()

    def _build_sidebar(self, parent: tk.Frame) -> None:
        sidebar = tk.Frame(parent, bg=theme.BG_SIDEBAR, width=SIDEBAR_WIDTH)
        sidebar.pack(side="left", fill="y", padx=(0, 16))
        sidebar.pack_propagate(False)

        head = tk.Frame(sidebar, bg=theme.BG_SIDEBAR)
        head.pack(fill="x", padx=14, pady=(14, 8))
        tk.Label(head, text=tr("DOCKS"), bg=theme.BG_SIDEBAR, fg=theme.TEXT_DIM,
                 font=theme.font(8, "bold")).pack(side="left")
        ttk.Button(head, text=tr("+ New dock"), style="Ghost.TButton",
                   command=self._new_dock).pack(side="right")

        wrapper = tk.Frame(sidebar, bg=theme.BG_SIDEBAR)
        wrapper.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.dock_canvas = tk.Canvas(wrapper, bg=theme.BG_SIDEBAR, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(wrapper, orient="vertical", command=self.dock_canvas.yview)
        self.dock_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.dock_canvas.pack(side="left", fill="both", expand=True)
        self.dock_list = tk.Frame(self.dock_canvas, bg=theme.BG_SIDEBAR)
        self._dock_window = self.dock_canvas.create_window((0, 0), window=self.dock_list, anchor="nw")
        self.dock_list.bind("<Configure>", lambda _e: self.dock_canvas.configure(scrollregion=self.dock_canvas.bbox("all")))
        self.dock_canvas.bind("<Configure>", self._resize_dock_list)

    def _resize_dock_list(self, event) -> None:
        self.dock_canvas.itemconfigure(self._dock_window, width=event.width)

    def _build_main(self, parent: tk.Frame) -> None:
        main = tk.Frame(parent, bg=theme.BG)
        main.pack(side="left", fill="both", expand=True)

        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)

        self.dock_tab = tk.Frame(self.tabs, bg=theme.BG_ELEVATED)
        self.settings_tab = tk.Frame(self.tabs, bg=theme.BG_ELEVATED)
        self.about_tab = tk.Frame(self.tabs, bg=theme.BG_ELEVATED)
        self.tabs.add(self.dock_tab, text="  " + tr("Dock") + "  ")
        self.tabs.add(self.settings_tab, text="  " + tr("Settings") + "  ")
        self.tabs.add(self.about_tab, text="  " + tr("About") + "  ")

        self._build_dock_tab()
        self._build_settings_tab()
        self._build_about_tab()

    def _build_dock_tab(self) -> None:
        tab = self.dock_tab
        head = tk.Frame(tab, bg=theme.BG_ELEVATED)
        head.pack(fill="x", padx=18, pady=(16, 6))

        icon_button = tk.Button(head, bg=theme.BG_INPUT, activebackground=theme.BORDER, bd=0,
                                highlightthickness=0, cursor="hand2", command=self._choose_icon)
        icon_button.pack(side="left", padx=(0, 12))
        self.icon_button = icon_button

        titles = tk.Frame(head, bg=theme.BG_ELEVATED)
        titles.pack(side="left", fill="x", expand=True)
        self.name_var = tk.StringVar()
        # Kept on self so the dock-name field can be focused, selected and given a
        # visible hint: renaming was invisible, so created docks stayed "New dock".
        name_entry = ttk.Entry(titles, textvariable=self.name_var, font=theme.font(12, "bold"))
        name_entry.pack(fill="x")
        self.name_entry = name_entry
        name_entry.bind("<FocusOut>", lambda _e: self._rename_dock())
        name_entry.bind("<Return>", lambda _e: self._rename_dock())
        self.item_count_label = tk.Label(titles, text="", bg=theme.BG_ELEVATED,
                                         fg=theme.TEXT_MUTED, font=theme.font(8))
        self.item_count_label.pack(anchor="w", pady=(4, 0))

        style_box = tk.Frame(head, bg=theme.BG_ELEVATED)
        style_box.pack(side="right", padx=(12, 0))
        tk.Label(style_box, text=tr("Expand style"), bg=theme.BG_ELEVATED, fg=theme.TEXT_MUTED,
                 font=theme.font(8)).pack(anchor="w")
        self.style_var = tk.StringVar()
        self.style_box = ttk.Combobox(style_box, textvariable=self.style_var, state="readonly",
                                      width=12, values=[DOCK_STYLE_LABELS[s] for s in DOCK_STYLES])
        self.style_box.pack(anchor="w", pady=(4, 0))
        self.style_box.bind("<<ComboboxSelected>>", self._on_style_changed)

        actions = tk.Frame(tab, bg=theme.BG_ELEVATED)
        actions.pack(fill="x", padx=18, pady=(10, 8))
        ttk.Button(actions, text=tr("Add shortcuts..."), style="Accent.TButton",
                   command=self._add_files).pack(side="left")
        ttk.Button(actions, text=tr("Add web link..."), style="Ghost.TButton",
                   command=self._add_link).pack(side="left", padx=6)
        ttk.Button(actions, text=tr("Add desktop shortcuts"), style="Ghost.TButton",
                   command=self._add_desktop_shortcuts).pack(side="left")
        ttk.Button(actions, text=tr("Delete dock"), style="Danger.TButton",
                   command=self._delete_dock).pack(side="right")

        table = tk.Frame(tab, bg=theme.BG_ELEVATED)
        table.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        columns = ("kind", "target")
        self.items = ttk.Treeview(table, columns=columns, show="tree headings", selectmode="browse")
        self.items.heading("#0", text=tr("Item"))
        self.items.heading("kind", text=tr("Type"))
        self.items.heading("target", text=tr("Target"))
        self.items.column("#0", width=260, anchor="w")
        self.items.column("kind", width=90, anchor="w")
        self.items.column("target", width=420, anchor="w")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.items.yview)
        self.items.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.items.pack(side="left", fill="both", expand=True)
        self.items.bind("<Double-1>", lambda _e: self._open_selected_item())
        self.items.bind("<<TreeviewSelect>>", self._on_item_selected)

        row = tk.Frame(tab, bg=theme.BG_ELEVATED)
        row.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(row, text=tr("Open"), command=self._open_selected_item).pack(side="left")
        ttk.Button(row, text=tr("Move up"), style="Ghost.TButton",
                   command=lambda: self._move_item(-1)).pack(side="left", padx=6)
        ttk.Button(row, text=tr("Move down"), style="Ghost.TButton",
                   command=lambda: self._move_item(1)).pack(side="left")
        ttk.Button(row, text="Remove", style="Danger.TButton",
                   command=self._remove_item).pack(side="right")

    def _build_settings_tab(self) -> None:
        # Declare every bound variable up front so a change handler fired while
        # the tab is still being built can never read a missing attribute.
        settings = self.app.store.settings
        self.open_trigger_var = tk.StringVar(value=settings.open_trigger)
        self.delay_var = tk.IntVar(value=settings.hover_delay_ms)
        self.background_var = tk.StringVar(value=settings.panel_background)
        self.panel_theme_var = tk.StringVar(value=settings.panel_theme)
        self.opacity_var = tk.DoubleVar(value=settings.panel_opacity)
        self.icon_size_var = tk.DoubleVar(value=settings.icon_size)
        self.labels_var = tk.BooleanVar(value=settings.show_labels)
        self.archive_var = tk.StringVar(value=settings.archive_mode)
        self.snap_var = tk.BooleanVar(value=settings.snap_to_grid)
        self.animations_var = tk.BooleanVar(value=settings.animations)
        self.autostart_var = tk.BooleanVar(value=settings.auto_start)
        self.minimized_var = tk.BooleanVar(value=settings.start_minimized)
        self.attach_var = tk.BooleanVar(value=settings.attach_to_desktop)
        self._settings_ready = False
        self._build_settings_body()
        self._settings_ready = True

    def _build_settings_body(self) -> None:
        tab = self.settings_tab
        canvas = tk.Canvas(tab, bg=theme.BG_ELEVATED, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=theme.BG_ELEVATED)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        settings = self.app.store.settings
        pad = {"padx": 18, "pady": (14, 4)}

        def section(title: str) -> tk.Frame:
            tk.Label(inner, text=title.upper(), bg=theme.BG_ELEVATED, fg=theme.TEXT_DIM,
                     font=theme.font(8, "bold")).pack(anchor="w", **pad)
            card = tk.Frame(inner, bg=theme.BG_ELEVATED)
            card.pack(fill="x", padx=18, pady=(0, 6))
            return card

        open_card = section("Opening")
        for value, label in (("hover", "Open on hover"), ("click", "Open on click")):
            ttk.Radiobutton(open_card, text=label, value=value, variable=self.open_trigger_var,
                            style="Card.TRadiobutton", command=self._apply_settings).pack(anchor="w", pady=2)
        delay_row = tk.Frame(open_card, bg=theme.BG_ELEVATED)
        delay_row.pack(fill="x", pady=(6, 0))
        tk.Label(delay_row, text=tr("Hover delay (ms)"), bg=theme.BG_ELEVATED, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(side="left")
        spin = ttk.Spinbox(delay_row, from_=0, to=2000, increment=50, textvariable=self.delay_var,
                           width=8, command=self._apply_settings)
        spin.pack(side="right")
        spin.bind("<FocusOut>", lambda _e: self._apply_settings())

        look_card = section("Panel look")
        for value, label in (("translucent", "Translucent"), ("solid", "Solid")):
            ttk.Radiobutton(look_card, text=label, value=value, variable=self.background_var,
                            style="Card.TRadiobutton", command=self._apply_settings).pack(anchor="w", pady=2)
        theme_row = tk.Frame(look_card, bg=theme.BG_ELEVATED)
        theme_row.pack(fill="x", pady=(8, 0))
        tk.Label(theme_row, text=tr("Panel theme"), bg=theme.BG_ELEVATED, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(side="left")
        theme_box = ttk.Combobox(theme_row, textvariable=self.panel_theme_var, state="readonly", width=10,
                                 values=["dark", "light", "auto"])
        theme_box.pack(side="right")
        theme_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_settings())

        self._labelled_scale(look_card, "Opacity", self.opacity_var, 0.35, 1.0, 0.05)
        self._labelled_scale(look_card, "Icon size", self.icon_size_var, 32, 128, 4)

        ttk.Checkbutton(look_card, text=tr("Show item names under icons"), variable=self.labels_var,
                        style="Card.TCheckbutton", command=self._apply_settings).pack(anchor="w", pady=(8, 2))

        behaviour = section("Desktop")
        for value, label in (("move", "Move originals into the archive"), ("copy", "Keep originals where they are")):
            ttk.Radiobutton(behaviour, text=label, value=value, variable=self.archive_var,
                            style="Card.TRadiobutton", command=self._apply_settings).pack(anchor="w", pady=2)
        ttk.Checkbutton(behaviour, text=tr("Snap docks to the desktop icon grid"), variable=self.snap_var,
                        style="Card.TCheckbutton", command=self._apply_settings).pack(anchor="w", pady=(8, 2))
        ttk.Checkbutton(behaviour, text=tr("Animate panels"), variable=self.animations_var,
                        style="Card.TCheckbutton", command=self._apply_settings).pack(anchor="w", pady=2)
        ttk.Checkbutton(behaviour, text=tr("Start MesaDock when I sign in"), variable=self.autostart_var,
                        style="Card.TCheckbutton", command=self._apply_settings).pack(anchor="w", pady=2)
        ttk.Checkbutton(behaviour, text=tr("Start minimised (docks only)"), variable=self.minimized_var,
                        style="Card.TCheckbutton", command=self._apply_settings).pack(anchor="w", pady=(2, 2))
        ttk.Checkbutton(
            behaviour,
            text=tr("Keep docks behind normal windows (desktop layer)"),
            variable=self.attach_var,
            style="Card.TCheckbutton",
            command=self._apply_settings,
        ).pack(anchor="w", pady=(2, 2))
        tk.Label(
            behaviour,
            text="On: docks stay above the wallpaper but behind apps.\n"
                 "Off: docks float above every window.",
            bg=theme.BG_ELEVATED, fg=theme.TEXT_DIM, font=theme.font(8),
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

    def _labelled_scale(self, parent, label: str, variable, low: float, high: float, step: float) -> None:
        row = tk.Frame(parent, bg=theme.BG_ELEVATED)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text=label, bg=theme.BG_ELEVATED, fg=theme.TEXT_MUTED,
                 font=theme.font(9), width=12, anchor="w").pack(side="left")
        value_label = tk.Label(row, text="", bg=theme.BG_ELEVATED, fg=theme.TEXT,
                               font=theme.font(9), width=6)
        value_label.pack(side="right")

        def on_change(_value=None) -> None:
            value_label.configure(text=("%.2f" % variable.get()) if step < 1 else str(int(variable.get())))
            self._apply_settings()

        scale = ttk.Scale(row, from_=low, to=high, variable=variable, orient="horizontal",
                          style="Card.TScale", command=on_change)
        scale.pack(side="left", fill="x", expand=True, padx=8)
        on_change()

    def _build_about_tab(self) -> None:
        tab = self.about_tab
        tk.Label(tab, text="MesaDock " + __version__, bg=theme.BG_ELEVATED, fg=theme.TEXT,
                 font=theme.font(16, "bold")).pack(anchor="w", padx=18, pady=(18, 2))
        tk.Label(tab, text="Every shortcut group, one desktop icon.", bg=theme.BG_ELEVATED,
                 fg=theme.TEXT_MUTED, font=theme.font(9)).pack(anchor="w", padx=18)
        tk.Label(tab, text="Data folder", bg=theme.BG_ELEVATED, fg=theme.TEXT_DIM,
                 font=theme.font(8, "bold")).pack(anchor="w", padx=18, pady=(18, 2))
        tk.Label(tab, text=str(paths.home_dir()), bg=theme.BG_ELEVATED, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(anchor="w", padx=18)

        row = tk.Frame(tab, bg=theme.BG_ELEVATED)
        row.pack(anchor="w", padx=18, pady=(16, 0))
        ttk.Button(row, text="Open data folder", style="Ghost.TButton",
                   command=self._open_data_folder).pack(side="left")
        ttk.Button(row, text="Restore all archived shortcuts", style="Ghost.TButton",
                   command=self._restore_archived).pack(side="left", padx=8)

        danger = tk.Frame(tab, bg=theme.BG_ELEVATED)
        danger.pack(anchor="w", padx=18, pady=(26, 0))
        ttk.Button(danger, text="Quit MesaDock", style="Danger.TButton",
                   command=self.app.quit).pack(side="left")

    def _build_status(self) -> None:
        bar = tk.Frame(self.window, bg=theme.BG_SIDEBAR, height=30)
        bar.pack(fill="x", side="bottom")
        self.status_label = tk.Label(bar, text="Ready", bg=theme.BG_SIDEBAR, fg=theme.TEXT_MUTED,
                                     font=theme.font(8), anchor="w")
        self.status_label.pack(side="left", padx=18, pady=6)

    # -- status ------------------------------------------------------------
    def set_status(self, message: str, error: bool = False) -> None:
        if self._closed:
            return
        try:
            self.status_label.configure(text=message, fg=theme.DANGER if error else theme.TEXT_MUTED)
        except tk.TclError:
            return
        if self._status_job is not None:
            try:
                self.window.after_cancel(self._status_job)
            except tk.TclError:
                pass
        self._status_job = self.window.after(6000, lambda: self.set_status("Ready"))

    # -- dock list ---------------------------------------------------------
    def refresh_docks(self) -> None:
        for child in self.dock_list.winfo_children():
            child.destroy()
        self._row_widgets.clear()
        self._photos.clear()
        for folder in self.app.store.folders:
            row = tk.Frame(self.dock_list, bg=theme.BG_SIDEBAR, cursor="hand2")
            row.pack(fill="x", pady=2, padx=2)
            try:
                photo = self.app.images.photo(folder_source(folder), 28)
                self._photos.append(photo)
                icon = tk.Label(row, image=photo, bg=theme.BG_SIDEBAR)
                icon.pack(side="left", padx=(10, 8), pady=8)
                icon.bind("<Button-1>", lambda _e, fid=folder.id: self.select_folder(fid))
            except Exception:
                pass
            text = tk.Frame(row, bg=theme.BG_SIDEBAR)
            text.pack(side="left", fill="x", expand=True)
            name = tk.Label(text, text=folder.name, bg=theme.BG_SIDEBAR, fg=theme.TEXT,
                            font=theme.font(10), anchor="w")
            name.pack(anchor="w", pady=(7, 0))
            meta = tk.Label(text, text=DOCK_STYLE_LABELS.get(folder.style, folder.style) + "  -  " +
                            str(len(folder.items)) + " item(s)", bg=theme.BG_SIDEBAR,
                            fg=theme.TEXT_MUTED, font=theme.font(8), anchor="w")
            meta.pack(anchor="w", pady=(0, 7))
            for widget in (row, text, name, meta):
                widget.bind("<Button-1>", lambda _e, fid=folder.id: self.select_folder(fid))
            self._row_widgets[folder.id] = row
        if not self.app.store.folders:
            tk.Label(self.dock_list, text="No docks yet.\nClick + New dock to start.",
                     bg=theme.BG_SIDEBAR, fg=theme.TEXT_DIM, font=theme.font(9),
                     justify="left").pack(anchor="w", padx=14, pady=18)
        self._highlight_selected()

    def _highlight_selected(self) -> None:
        for folder_id, row in self._row_widgets.items():
            active = folder_id == self.selected_id
            colour = theme.ACCENT_SOFT if active else theme.BG_SIDEBAR
            row.configure(bg=colour)
            for child in row.winfo_children():
                try:
                    child.configure(bg=colour)
                    for grandchild in child.winfo_children():
                        grandchild.configure(bg=colour)
                except tk.TclError:
                    pass

    def select_folder(self, folder_id: str | None) -> None:
        if folder_id is None:
            return
        folder = self.app.store.folder_by_id(folder_id)
        if folder is None:
            return
        self.selected_id = folder.id
        self.name_var.set(folder.name)
        self.style_var.set(DOCK_STYLE_LABELS.get(folder.style, folder.style))
        self._refresh_icon()
        self.item_count_label.configure(text=str(len(folder.items)) + " item(s)")
        self._refresh_items()
        self._highlight_selected()

    def select_item(self, item_id: str) -> None:
        if self.items.exists(item_id):
            self.items.selection_set(item_id)
            self.items.see(item_id)

    def _refresh_icon(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        try:
            photo = self.app.images.photo(folder_source(folder), 46)
            self._photos.append(photo)
            self.icon_button.configure(image=photo, text="")
        except Exception:
            self.icon_button.configure(image="", text="icon")

    def _refresh_items(self) -> None:
        self.items.delete(*self.items.get_children())
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        for item in folder.items:
            try:
                photo = self.app.images.photo(item_source(item), 20)
                self._photos.append(photo)
            except Exception:
                photo = None
            target = item.target or item.path
            if len(target) > 70:
                target = target[:67] + "..."
            self.items.insert("", "end", iid=item.id, text=" " + item.name,
                              values=(KIND_LABELS.get(item.kind, item.kind), target), image=photo or "")
        if self.selected_item_id and self.items.exists(self.selected_item_id):
            self.items.selection_set(self.selected_item_id)

    # -- actions -----------------------------------------------------------
    def _new_dock(self) -> None:
        # Ask for the name up front: the dock used to be created silently as
        # "New dock" and nothing on the desktop said which dock was which.
        name = _ask_string(self.window, "New dock", "Name this dock:")
        name = (name or "").strip()
        if not name:
            self.set_status("Dock creation cancelled.")
            return
        folder = self.app.add_dock(name, "grid")
        self.refresh_docks()
        self.select_folder(folder.id)
        self.set_status("Dock \"" + folder.name + "\" created. Drag shortcuts onto it, or use Add shortcuts.")

    def _delete_dock(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        if not messagebox.askyesno("Delete dock", "Delete \"" + folder.name + "\"?\n\n"
                                   "Shortcuts that came from the desktop are put back.", parent=self.window):
            return
        self.app.remove_dock(folder.id, restore=True)
        self.selected_id = self.app.store.folders[0].id if self.app.store.folders else None
        self.refresh_docks()
        self.select_folder(self.selected_id)
        self.set_status("Dock deleted")

    def _rename_dock(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        name = self.name_var.get().strip()
        if name and name != folder.name:
            self.app.rename_dock(folder.id, name)
            self.refresh_docks()
            self.set_status("Renamed to " + name)

    def _on_style_changed(self, _event=None) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        label = self.style_var.get()
        for style, style_label in DOCK_STYLE_LABELS.items():
            if style_label == label:
                self.app.set_dock_style(folder.id, style)
                self.refresh_docks()
                self.set_status("Style set to " + style_label)
                return

    def _choose_icon(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        path = filedialog.askopenfilename(parent=self.window, title="Choose a dock icon",
                                          filetypes=[("Images", "*.png *.ico *.jpg *.jpeg *.bmp"), ("All files", "*.*")])
        if not path:
            return
        self.app.set_dock_icon(folder.id, path)
        self._refresh_icon()
        self.set_status("Icon updated")

    def _add_files(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        files = filedialog.askopenfilenames(parent=self.window, title="Add shortcuts and files",
                                            filetypes=[("Shortcuts", "*.lnk *.url"), ("All files", "*.*")])
        if not files:
            return
        added = self.app.add_paths_to_dock(folder.id, list(files))
        self._after_items_changed(added)

    def _add_desktop_shortcuts(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        shortcuts = [str(path) for path in archive_mod.desktop_shortcuts()]
        if not shortcuts:
            self.set_status("No shortcuts found on the desktop", error=True)
            return
        # In move mode this empties the desktop, which used to happen with no
        # warning at all. Confirm first so it is never a surprise.
        if self.app.store.settings.archive_mode == "move":
            if not messagebox.askyesno(
                    "Add desktop shortcuts",
                    "Add " + str(len(shortcuts)) + " desktop shortcut(s) to \"" + folder.name + "\"?"
                    "\n\nArchive mode is set to move, so they will be removed from the"
                    " desktop and kept inside MesaDock."
                    "\n\nYou can put them back later with Remove (restores original)."
                    "\nTo keep them on the desktop too, change Settings > Archive mode to copy.",
                    parent=self.window):
                self.set_status("Cancelled. Nothing was moved.")
                return
        added = self.app.add_paths_to_dock(folder.id, shortcuts)
        self._after_items_changed(added)
    def _add_link(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        url = _ask_string(self.window, "Add web link", "Address (https://...)")
        if not url:
            return
        if self.app.add_url_to_dock(folder.id, url):
            self._after_items_changed(1)

    def _after_items_changed(self, added: int) -> None:
        self.refresh_docks()
        self.select_folder(self.selected_id)
        if added:
            self.set_status(str(added) + (" item added" if added == 1 else " items added"))

    def _open_selected_item(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        selection = self.items.selection()
        if folder is None or not selection:
            return
        item = folder.item_by_id(selection[0])
        if item is not None:
            self.app.launch_item(folder, item)

    def _move_item(self, delta: int) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        selection = self.items.selection()
        if folder is None or not selection:
            return
        folder.move_item(selection[0], delta)
        self.app.touch()
        self._refresh_items()
        dock = self.app.docks.get(folder.id)
        if dock is not None:
            dock.refresh()

    def _remove_item(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        selection = self.items.selection()
        if folder is None or not selection:
            return
        item = folder.item_by_id(selection[0])
        if item is None:
            return
        if not messagebox.askyesno(
                "Remove item",
                "Remove \"" + item.name + "\" from this dock?"
                "\n\nThe shortcut itself is not deleted. It goes back to the desktop.",
                parent=self.window):
            return
        self.app.remove_item(folder.id, item.id, restore=True)
        self._after_items_changed(0)
        self.set_status("Item removed; original restored if it was archived")

    def _on_item_selected(self, _event=None) -> None:
        selection = self.items.selection()
        self.selected_item_id = selection[0] if selection else None

    def _on_profile_changed(self, _event=None) -> None:
        name = self.profile_var.get()
        for index, profile in enumerate(self.app.store.profiles):
            if profile.name == name:
                self.app.switch_profile(index)
                self.selected_id = self.app.store.folders[0].id if self.app.store.folders else None
                self.refresh_docks()
                self.select_folder(self.selected_id)
                self.set_status("Switched to profile " + name)
                return

    def _new_profile(self) -> None:
        name = _ask_string(self.window, "New profile", "Profile name")
        if not name:
            return
        self.app.add_profile(name)
        self.profile_box.configure(values=self._profile_names())
        self.profile_var.set(self.app.store.active_profile.name)
        self.selected_id = None
        self.refresh_docks()
        self.set_status("Profile " + name + " created")

    def _apply_settings(self) -> None:
        if not getattr(self, "_settings_ready", True):
            # A ttk.Scale fires its command while the tab is still being built.
            try:
                self.window.after(150, self._apply_settings)
            except tk.TclError:
                pass
            return
        settings = self.app.store.settings
        try:
            settings.open_trigger = self.open_trigger_var.get()
            settings.hover_delay_ms = int(self.delay_var.get())
            settings.panel_background = self.background_var.get()
            settings.panel_theme = self.panel_theme_var.get()
            settings.panel_opacity = float(self.opacity_var.get())
            settings.icon_size = int(self.icon_size_var.get())
            settings.show_labels = bool(self.labels_var.get())
            settings.archive_mode = self.archive_var.get()
            settings.snap_to_grid = bool(self.snap_var.get())
            settings.animations = bool(self.animations_var.get())
            settings.auto_start = bool(self.autostart_var.get())
            settings.start_minimized = bool(self.minimized_var.get())
            settings.attach_to_desktop = bool(self.attach_var.get())
        except (tk.TclError, ValueError):
            return
        self.app.apply_settings()

    def _open_data_folder(self) -> None:
        try:
            os.startfile(str(paths.home_dir()))
        except OSError:
            self.set_status("Could not open " + str(paths.home_dir()), error=True)

    def _restore_archived(self) -> None:
        restored = self.app.emergency_restore_all()
        self.set_status("Restored " + str(restored) + " archived item(s)")

    # -- window ------------------------------------------------------------
    def show(self) -> None:
        if self._closed:
            return
        try:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            self.refresh_docks()
            self.select_folder(self.selected_id)
            self.profile_box.configure(values=self._profile_names())
        except tk.TclError:
            pass

    def show_tab(self, name: str) -> None:
        """Switch to 'dock', 'settings' or 'about'."""
        tabs = {"dock": self.dock_tab, "settings": self.settings_tab, "about": self.about_tab}
        target = tabs.get(name.lower())
        if target is not None:
            self.tabs.select(target)

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        self.app.closed_manager()


def _ask_string(parent, title: str, prompt: str) -> str:
    """Small themed text prompt (simpledialog is modal and hard to style)."""
    from tkinter import simpledialog

    return simpledialog.askstring(title, prompt, parent=parent) or ""

