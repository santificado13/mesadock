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

WINDOW_SIZE = (1040, 680)
SIDEBAR_WIDTH = 250


def classify_target(target: str, kind: str = "") -> str:
    """Classify target into App, Web, Folder, Script or File."""
    target_clean = (target or "").strip()
    target_lower = target_clean.lower()
    if target_lower.startswith(("http://", "https://", "ftp://", "mailto:")) or kind == "url":
        return tr("Web")
    if kind == "folder" or (target_clean and os.path.isdir(target_clean)):
        return tr("Folder")
    if target_lower.endswith((".exe", ".lnk")) or kind == "app":
        return tr("App")
    if target_lower.endswith((".bat", ".cmd", ".ps1", ".py", ".vbs")):
        return tr("Script")
    return tr("File")


def shorten_target(target: str) -> str:
    """Shorten path into '...\\folder\\file.ext' format."""
    t = (target or "").strip()
    if not t:
        return ""
    if t.lower().startswith(("http://", "https://")):
        if len(t) > 42:
            return t[:39] + "\u2026"
        return t
    p = Path(t)
    name = p.name or t
    parent = p.parent.name
    sep = "\\" if "\\" in t or "/" not in t else "/"
    if parent:
        return f"\u2026{sep}{parent}{sep}{name}"
    return name


class ManagerWindow:
    """The single window where docks are created and configured."""

    def __init__(self, app, select: str | None = None, select_item: str | None = None) -> None:
        self.app = app
        self.selected_id = select
        self.selected_item_id = select_item
        self._closed = False
        self._photos: list = []
        self._row_widgets: dict[str, dict] = {}
        self._style_buttons: dict[str, tk.Button] = {}
        self._status_job = None
        self._drag_item_id: str | None = None

        self.window = tk.Toplevel(app.root)
        self.window.title(tr("MesaDock Manager"))
        theme.apply_window_icon(self.window)
        self.window.geometry(str(WINDOW_SIZE[0]) + "x" + str(WINDOW_SIZE[1]))
        self.window.minsize(880, 560)
        self.window.configure(bg=theme.BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.bind("<Delete>", lambda _event: self._remove_item())
        self.window.bind("<Control-a>", lambda _event: self._add_files())

        # Layout hierarchy:
        # 1. Sidebar on left
        # 2. Status bar at bottom (packed before main so it is NEVER cut off)
        # 3. Main container with tabs
        self._build_sidebar()
        self._build_status()
        self._build_main()

        self.refresh_docks()
        if self.selected_id is None and self.app.store.folders:
            self.selected_id = self.app.store.folders[0].id
        self.select_folder(self.selected_id)
        if select_item:
            self.select_item(select_item)

    # -- sidebar -----------------------------------------------------------
    def _build_sidebar(self) -> None:
        sidebar = tk.Frame(self.window, bg=theme.BG_SIDEBAR, width=SIDEBAR_WIDTH)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Title
        title_box = tk.Frame(sidebar, bg=theme.BG_SIDEBAR)
        title_box.pack(fill="x", padx=16, pady=(16, 12))
        tk.Label(title_box, text="MesaDock", bg=theme.BG_SIDEBAR, fg=theme.TEXT,
                 font=theme.font(16, "bold")).pack(anchor="w")
        tk.Label(title_box, text=tr("Manager"), bg=theme.BG_SIDEBAR, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(anchor="w")

        # Docks section header
        head = tk.Frame(sidebar, bg=theme.BG_SIDEBAR)
        head.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(head, text=tr("DOCKS"), bg=theme.BG_SIDEBAR, fg=theme.TEXT_DIM,
                 font=theme.font(8, "bold")).pack(side="left")
        ttk.Button(head, text=tr("+ New dock"), style="Ghost.TButton",
                   command=self._new_dock).pack(side="right")
        ttk.Button(sidebar, text=tr("+ Folder dock"), style="Ghost.TButton",
                   command=self._new_portal).pack(anchor="e", padx=14, pady=(0, 8))

        # Footer (profile & language)
        footer = tk.Frame(sidebar, bg=theme.BG_SIDEBAR)
        footer.pack(side="bottom", fill="x", padx=14, pady=12)

        ttk.Separator(footer, orient="horizontal").pack(fill="x", pady=(0, 10))

        prof_row = tk.Frame(footer, bg=theme.BG_SIDEBAR)
        prof_row.pack(fill="x")
        tk.Label(prof_row, text=tr("Profile"), bg=theme.BG_SIDEBAR, fg=theme.TEXT_MUTED,
                 font=theme.font(8, "bold")).pack(anchor="w")

        prof_box_row = tk.Frame(prof_row, bg=theme.BG_SIDEBAR)
        prof_box_row.pack(fill="x", pady=(3, 8))
        self.profile_var = tk.StringVar(value=self.app.store.active_profile.name)
        self.profile_box = ttk.Combobox(prof_box_row, textvariable=self.profile_var, state="readonly",
                                        width=12, values=self._profile_names())
        self.profile_box.pack(side="left", fill="x", expand=True)
        self.profile_box.bind("<<ComboboxSelected>>", self._on_profile_changed)
        ttk.Button(prof_box_row, text="+", width=3, style="Ghost.TButton",
                   command=self._new_profile).pack(side="left", padx=(4, 0))

        # Language segment PT | EN
        lang_row = tk.Frame(footer, bg=theme.BG_SIDEBAR)
        lang_row.pack(fill="x")
        tk.Label(lang_row, text=tr("Language"), bg=theme.BG_SIDEBAR, fg=theme.TEXT_MUTED,
                 font=theme.font(8, "bold")).pack(side="left")
        self._build_lang_segment(lang_row)

        # Middle scrollable dock list
        wrapper = tk.Frame(sidebar, bg=theme.BG_SIDEBAR)
        wrapper.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.dock_canvas = tk.Canvas(wrapper, bg=theme.BG_SIDEBAR, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(wrapper, orient="vertical", command=self.dock_canvas.yview)
        self.dock_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.dock_canvas.pack(side="left", fill="both", expand=True)
        self.dock_list = tk.Frame(self.dock_canvas, bg=theme.BG_SIDEBAR)
        self._dock_window = self.dock_canvas.create_window((0, 0), window=self.dock_list, anchor="nw")
        self.dock_list.bind("<Configure>", lambda _e: self.dock_canvas.configure(scrollregion=self.dock_canvas.bbox("all")))
        self.dock_canvas.bind("<Configure>", self._resize_dock_list)

    def _build_lang_segment(self, parent: tk.Frame) -> None:
        frame = tk.Frame(parent, bg=theme.BG_SIDEBAR)
        frame.pack(side="right")
        current_lang = i18n.get_lang()
        for code, label in (("pt", "PT"), ("en", "EN")):
            active = (code == current_lang)
            btn = tk.Button(
                frame,
                text=label,
                bg=theme.ACCENT if active else theme.BG_INPUT,
                fg="#08111f" if active else theme.TEXT_MUTED,
                font=theme.font(8, "bold" if active else "normal"),
                relief="flat",
                bd=0,
                padx=8,
                pady=2,
                cursor="hand2",
                command=lambda c=code: self._switch_lang(c),
            )
            btn.pack(side="left", padx=1)

    def _switch_lang(self, code: str) -> None:
        if code != i18n.get_lang():
            i18n.set_lang(code)
            self.app.store.settings.language = code
            self.app.touch()
            self.window.destroy()
            self.app.closed_manager()
            self.app.open_manager(select=self.selected_id, select_item=self.selected_item_id)

    def _profile_names(self) -> list[str]:
        return [profile.name for profile in self.app.store.profiles]

    def _resize_dock_list(self, event) -> None:
        self.dock_canvas.itemconfigure(self._dock_window, width=event.width)

    # -- status bar --------------------------------------------------------
    def _build_status(self) -> None:
        bar = tk.Frame(self.window, bg=theme.BG_SIDEBAR, height=28)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.status_label = tk.Label(bar, text=tr("Ready"), bg=theme.BG_SIDEBAR,
                                     fg=theme.TEXT_MUTED, font=theme.font(8), anchor="w")
        self.status_label.pack(side="left", padx=16, pady=5)

    def set_status(self, message: str, error: bool = False) -> None:
        if self._closed:
            return
        try:
            self.status_label.configure(text=tr(message), fg=theme.DANGER if error else theme.TEXT_MUTED)
        except tk.TclError:
            return
        if self._status_job is not None:
            try:
                self.window.after_cancel(self._status_job)
            except tk.TclError:
                pass
        self._status_job = self.window.after(6000, lambda: self.set_status(tr("Ready")))

    # -- main container ----------------------------------------------------
    def _build_main(self) -> None:
        main = tk.Frame(self.window, bg=theme.BG)
        main.pack(side="left", fill="both", expand=True, padx=16, pady=12)

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

        # Header: Icon (44px), editable Name, Subtitle ("N atalhos"), and "Excluir dock" on right
        head = tk.Frame(tab, bg=theme.BG_ELEVATED)
        head.pack(fill="x", padx=20, pady=(16, 10))

        icon_button = tk.Button(
            head,
            bg=theme.BG_INPUT,
            activebackground=theme.BORDER,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            cursor="hand2",
            command=self._choose_icon,
            width=44,
            height=44,
        )
        icon_button.pack(side="left", padx=(0, 14))
        self.icon_button = icon_button

        titles = tk.Frame(head, bg=theme.BG_ELEVATED)
        titles.pack(side="left", fill="x", expand=True)
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(titles, textvariable=self.name_var, font=theme.font(14, "bold"))
        name_entry.pack(fill="x")
        self.name_entry = name_entry
        name_entry.bind("<FocusOut>", lambda _e: self._rename_dock())
        name_entry.bind("<Return>", lambda _e: self._rename_dock())
        self.item_count_label = tk.Label(titles, text="", bg=theme.BG_ELEVATED,
                                         fg=theme.TEXT_MUTED, font=theme.font(9))
        self.item_count_label.pack(anchor="w", pady=(3, 0))

        # Discreet Danger Delete dock button
        ttk.Button(head, text=tr("Delete dock"), style="Danger.TButton",
                   command=self._delete_dock).pack(side="right", padx=(12, 0))

        # Expand style segmented buttons
        style_frame = tk.Frame(tab, bg=theme.BG_ELEVATED)
        style_frame.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(style_frame, text=tr("Expand style") + ":", bg=theme.BG_ELEVATED,
                 fg=theme.TEXT_MUTED, font=theme.font(9)).pack(side="left", padx=(0, 10))

        self.style_var = tk.StringVar()
        style_seg = tk.Frame(style_frame, bg=theme.BG_INPUT)
        style_seg.pack(side="left")

        self._style_buttons.clear()
        for style_key in DOCK_STYLES:
            style_label = tr(DOCK_STYLE_LABELS.get(style_key, style_key))
            btn = tk.Button(
                style_seg,
                text=style_label,
                relief="flat",
                bd=0,
                padx=10,
                pady=4,
                font=theme.font(9),
                cursor="hand2",
                command=lambda s=style_key: self._on_style_button_clicked(s),
            )
            btn.pack(side="left", padx=1, pady=1)
            self._style_buttons[style_key] = btn

        # Actions bar: "Add shortcuts..." as the ONLY Accent action
        actions = tk.Frame(tab, bg=theme.BG_ELEVATED)
        actions.pack(fill="x", padx=20, pady=(0, 12))
        ttk.Button(actions, text=tr("Add shortcuts..."), style="Accent.TButton",
                   command=self._add_files).pack(side="left")
        ttk.Button(actions, text=tr("Add web link..."), style="Ghost.TButton",
                   command=self._add_link).pack(side="left", padx=8)
        ttk.Button(actions, text=tr("Add desktop shortcuts"), style="Ghost.TButton",
                   command=self._add_desktop_shortcuts).pack(side="left")

        # Items Table
        table = tk.Frame(tab, bg=theme.BG_ELEVATED)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        columns = ("kind", "target")
        self.items = ttk.Treeview(table, columns=columns, show="tree headings", selectmode="browse")
        self.items.heading("#0", text=tr("Item"), anchor="w")
        self.items.heading("kind", text=tr("Type"), anchor="w")
        self.items.heading("target", text=tr("Target"), anchor="w")
        self.items.column("#0", width=250, minwidth=170, anchor="w")
        self.items.column("kind", width=80, minwidth=60, anchor="w")
        self.items.column("target", width=380, minwidth=200, anchor="w")

        scroll = ttk.Scrollbar(table, orient="vertical", command=self.items.yview)
        self.items.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.items.pack(side="left", fill="both", expand=True)

        self.items.bind("<Double-1>", lambda _e: self._open_selected_item())
        self.items.bind("<<TreeviewSelect>>", self._on_item_selected)

        # Drag-and-drop reordering
        self.items.bind("<ButtonPress-1>", self._on_tree_press, add="+")
        self.items.bind("<ButtonRelease-1>", self._on_tree_release, add="+")

        # Bottom row: small up/down arrow buttons, small Open and Remove buttons
        row = tk.Frame(tab, bg=theme.BG_ELEVATED)
        row.pack(fill="x", padx=20, pady=(0, 14))
        ttk.Button(row, text="▲", width=3, style="Ghost.TButton",
                   command=lambda: self._move_item(-1)).pack(side="left")
        ttk.Button(row, text="▼", width=3, style="Ghost.TButton",
                   command=lambda: self._move_item(1)).pack(side="left", padx=(4, 8))
        ttk.Button(row, text=tr("Open"), style="Ghost.TButton",
                   command=self._open_selected_item).pack(side="left")
        ttk.Button(row, text=tr("Icon..."), style="Ghost.TButton",
                   command=self._choose_item_icon).pack(side="left", padx=(4, 0))
        ttk.Button(row, text=tr("Remove"), style="Danger.TButton",
                   command=self._remove_item).pack(side="right")

    def _choose_item_icon(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        selection = self.items.selection()
        if folder is None or not selection:
            self.set_status(tr("Select an item first"), error=True)
            return
        item_id = selection[0]
        self.app.choose_item_icon(folder.id, item_id, parent=self.window)
        self._refresh_items()
        if self.items.exists(item_id):
            self.items.selection_set(item_id)

    def _update_style_buttons(self, active_style: str) -> None:
        for style_key, btn in self._style_buttons.items():
            if style_key == active_style:
                btn.configure(bg=theme.ACCENT, fg="#08111f", font=theme.font(9, "bold"))
            else:
                btn.configure(bg=theme.BG_INPUT, fg=theme.TEXT_MUTED, font=theme.font(9))

    def _on_style_button_clicked(self, style: str) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        self.app.set_dock_style(folder.id, style)
        self.style_var.set(DOCK_STYLE_LABELS.get(style, style))
        self._update_style_buttons(style)
        self.refresh_docks()
        self.set_status(tr("Style set to ") + tr(DOCK_STYLE_LABELS.get(style, style)))

    # -- drag and drop on treeview -----------------------------------------
    def _on_tree_press(self, event) -> None:
        self._drag_item_id = self.items.identify_row(event.y)

    def _on_tree_release(self, event) -> None:
        target_id = self.items.identify_row(event.y)
        source_id = self._drag_item_id
        self._drag_item_id = None
        if source_id and target_id and source_id != target_id:
            folder = self.app.store.folder_by_id(self.selected_id or "")
            if folder:
                ids = [i.id for i in folder.items]
                if source_id in ids and target_id in ids:
                    from_idx = ids.index(source_id)
                    to_idx = ids.index(target_id)
                    folder.items.insert(to_idx, folder.items.pop(from_idx))
                    self.app.touch()
                    self._refresh_items()
                    self.items.selection_set(source_id)
                    dock = self.app.docks.get(folder.id)
                    if dock is not None:
                        dock.refresh()

    # -- dock list ---------------------------------------------------------
    def refresh_docks(self) -> None:
        for child in self.dock_list.winfo_children():
            child.destroy()
        self._row_widgets.clear()
        self._photos.clear()

        for folder in self.app.store.folders:
            count = len(folder.items)
            is_empty = (count == 0)

            row = tk.Frame(self.dock_list, bg=theme.BG_SIDEBAR, cursor="hand2")
            row.pack(fill="x", pady=2, padx=4)

            try:
                photo = self.app.images.photo(folder_source(folder), 28)
                self._photos.append(photo)
                icon = tk.Label(row, image=photo, bg=theme.BG_SIDEBAR)
                icon.pack(side="left", padx=(8, 8), pady=6)
                icon.bind("<Button-1>", lambda _e, fid=folder.id: self.select_folder(fid))
            except Exception:
                icon = None

            text = tk.Frame(row, bg=theme.BG_SIDEBAR)
            text.pack(side="left", fill="x", expand=True)
            name_fg = theme.TEXT_DIM if is_empty else theme.TEXT
            name = tk.Label(text, text=folder.name, bg=theme.BG_SIDEBAR, fg=name_fg,
                            font=theme.font(10, "normal" if is_empty else "bold"), anchor="w")
            name.pack(anchor="w", pady=(5, 0))

            style_name = tr(DOCK_STYLE_LABELS.get(folder.style, folder.style))
            meta = tk.Label(text, text=style_name, bg=theme.BG_SIDEBAR,
                            fg=theme.TEXT_DIM, font=theme.font(8), anchor="w")
            meta.pack(anchor="w", pady=(0, 5))

            # Pill badge with count
            pill_bg = theme.BG_INPUT if not is_empty else theme.BG_SIDEBAR
            pill_fg = theme.ACCENT if not is_empty else theme.TEXT_DIM
            pill = tk.Label(row, text=str(count), bg=pill_bg, fg=pill_fg,
                            font=theme.font(8, "bold"), padx=6, pady=2)
            pill.pack(side="right", padx=(4, 8))

            for widget in (row, text, name, meta, pill):
                widget.bind("<Button-1>", lambda _e, fid=folder.id: self.select_folder(fid))

            self._row_widgets[folder.id] = {
                "row": row,
                "text": text,
                "name": name,
                "meta": meta,
                "pill": pill,
                "icon": icon,
            }

        if not self.app.store.folders:
            tk.Label(self.dock_list, text=tr("No docks yet.\nClick + New dock to start."),
                     bg=theme.BG_SIDEBAR, fg=theme.TEXT_DIM, font=theme.font(9),
                     justify="left").pack(anchor="w", padx=14, pady=18)
        self._highlight_selected()

    def _highlight_selected(self) -> None:
        for folder_id, widgets in self._row_widgets.items():
            active = (folder_id == self.selected_id)
            colour = theme.ACCENT_SOFT if active else theme.BG_SIDEBAR
            row = widgets["row"]
            row.configure(bg=colour)
            widgets["text"].configure(bg=colour)
            widgets["name"].configure(bg=colour)
            widgets["meta"].configure(bg=colour)
            if widgets["icon"]:
                widgets["icon"].configure(bg=colour)
            if active:
                widgets["pill"].configure(bg=theme.blend(theme.ACCENT_SOFT, theme.ACCENT, 0.3), fg=theme.TEXT)
            else:
                folder = self.app.store.folder_by_id(folder_id)
                count = len(folder.items) if folder else 0
                widgets["pill"].configure(bg=theme.BG_INPUT if count else theme.BG_SIDEBAR,
                                          fg=theme.ACCENT if count else theme.TEXT_DIM)

    def select_folder(self, folder_id: str | None) -> None:
        if folder_id is None:
            return
        folder = self.app.store.folder_by_id(folder_id)
        if folder is None:
            return
        self.selected_id = folder.id
        self.name_var.set(folder.name)
        self.style_var.set(DOCK_STYLE_LABELS.get(folder.style, folder.style))
        self._update_style_buttons(folder.style)
        self._refresh_icon()
        count = len(folder.items)
        sub_text = f"{count} " + (tr("1 shortcut") if count == 1 else tr(" shortcuts"))
        if folder.portal:
            sub_text += "  \u00b7  " + tr("shows the folder ") + folder.portal
        self.item_count_label.configure(text=sub_text)
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
            photo = self.app.images.photo(folder_source(folder), 44)
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
            shortened = shorten_target(target)
            kind_label = classify_target(target, item.kind)
            self.items.insert("", "end", iid=item.id, text=" " + item.name,
                              values=(kind_label, shortened), image=photo or "")
        if self.selected_item_id and self.items.exists(self.selected_item_id):
            self.items.selection_set(self.selected_item_id)

    # -- actions -----------------------------------------------------------
    def _new_portal(self) -> None:
        folder = self.app.prompt_new_portal(parent=self.window)
        if folder is None:
            return
        self.refresh_docks()
        self.select_folder(folder.id)
        self.set_status(tr("Dock \"{name}\" created.").format(name=folder.name))

    def _new_dock(self) -> None:
        name = _ask_string(self.window, tr("New dock"), tr("Name this dock:"))
        name = (name or "").strip()
        if not name:
            self.set_status(tr("Dock creation cancelled."))
            return
        folder = self.app.add_dock(name, "grid")
        self.refresh_docks()
        self.select_folder(folder.id)
        self.set_status(tr("Dock \"{name}\" created.").format(name=folder.name))

    def _delete_dock(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        if not messagebox.askyesno(tr("Delete dock"), f"{tr('Delete')} \"{folder.name}\"?", parent=self.window):
            return
        self.app.remove_dock(folder.id, restore=True)
        self.selected_id = self.app.store.folders[0].id if self.app.store.folders else None
        self.refresh_docks()
        self.select_folder(self.selected_id)
        self.set_status(tr("Dock deleted"))

    def _rename_dock(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        name = self.name_var.get().strip()
        if name and name != folder.name:
            self.app.rename_dock(folder.id, name)
            self.refresh_docks()
            self.set_status(tr("Renamed to ") + name)

    def _on_style_changed(self, _event=None) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        label = self.style_var.get()
        for style, style_label in DOCK_STYLE_LABELS.items():
            if style_label == label or tr(style_label) == label:
                self.app.set_dock_style(folder.id, style)
                self._update_style_buttons(style)
                self.refresh_docks()
                self.set_status(tr("Style set to ") + tr(style_label))
                return

    def _choose_icon(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        path = filedialog.askopenfilename(
            parent=self.window,
            title=tr("Choose a dock icon"),
            filetypes=[("Images", "*.png *.ico *.jpg *.jpeg *.bmp"), ("All files", "*.*")],
        )
        if not path:
            return
        self.app.set_dock_icon(folder.id, path)
        self._refresh_icon()
        self.set_status(tr("Icon updated"))

    def _add_files(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        files = filedialog.askopenfilenames(
            parent=self.window,
            title=tr("Add shortcuts and files"),
            filetypes=[(tr("Shortcuts"), "*.lnk *.url"), (tr("All files"), "*.*")],
        )
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
            self.set_status(tr("No shortcuts found on the desktop"), error=True)
            return
        if self.app.store.settings.archive_mode == "move":
            if not messagebox.askyesno(
                tr("Add desktop shortcuts"),
                tr("Add {count} desktop shortcut(s) to \"{name}\"?").format(count=len(shortcuts), name=folder.name),
                parent=self.window,
            ):
                self.set_status(tr("Cancelled. Nothing was moved."))
                return
        added = self.app.add_paths_to_dock(folder.id, shortcuts)
        self._after_items_changed(added)

    def _add_link(self) -> None:
        folder = self.app.store.folder_by_id(self.selected_id or "")
        if folder is None:
            return
        url = _ask_string(self.window, tr("Add web link..."), tr("Address (https://...)"))
        if not url:
            return
        if self.app.add_url_to_dock(folder.id, url):
            self._after_items_changed(1)

    def _after_items_changed(self, added: int) -> None:
        self.refresh_docks()
        self.select_folder(self.selected_id)
        if added:
            self.set_status(f"{added} " + (tr("item") if added == 1 else tr("items")))

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
        if folder.portal:
            self.set_status(tr("A folder dock follows the order of its folder"), error=True)
            return
        folder.move_item(selection[0], delta)
        self.app.touch()
        self._refresh_items()
        self.items.selection_set(selection[0])
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
        if folder.portal:
            self.set_status(tr("This dock shows a folder. Remove the file from the folder itself."), error=True)
            return
        if not messagebox.askyesno(
            tr("Remove"),
            f"{tr('Remove')} \"{item.name}\"?",
            parent=self.window,
        ):
            return
        self.app.remove_item(folder.id, item.id, restore=True)
        self._after_items_changed(0)
        self.set_status(tr("Item removed; original restored if it was archived"))

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
                self.set_status(tr("Switched to profile ") + name)
                return

    def _new_profile(self) -> None:
        name = _ask_string(self.window, tr("New profile"), tr("Profile name"))
        if not name:
            return
        self.app.add_profile(name)
        self.profile_box.configure(values=self._profile_names())
        self.profile_var.set(self.app.store.active_profile.name)
        self.selected_id = None
        self.refresh_docks()
        self.set_status(tr("Profile {name} created").format(name=name))

    # -- settings tab ------------------------------------------------------
    def _build_settings_tab(self) -> None:
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
        self.hide_dblclick_var = tk.BooleanVar(value=settings.hide_on_double_click)
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

        pad = {"padx": 18, "pady": (14, 4)}

        def section(title: str) -> tk.Frame:
            tk.Label(inner, text=tr(title).upper(), bg=theme.BG_ELEVATED, fg=theme.TEXT_DIM,
                     font=theme.font(8, "bold")).pack(anchor="w", **pad)
            card = tk.Frame(inner, bg=theme.BG_ELEVATED)
            card.pack(fill="x", padx=18, pady=(0, 6))
            return card

        open_card = section("Opening")
        for value, label in (("hover", "Open on hover"), ("click", "Open on click")):
            ttk.Radiobutton(open_card, text=tr(label), value=value, variable=self.open_trigger_var,
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
            ttk.Radiobutton(look_card, text=tr(label), value=value, variable=self.background_var,
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
            ttk.Radiobutton(behaviour, text=tr(label), value=value, variable=self.archive_var,
                            style="Card.TRadiobutton", command=self._apply_settings).pack(anchor="w", pady=2)
        ttk.Checkbutton(behaviour, text=tr("Snap docks to the desktop icon grid"), variable=self.snap_var,
                        style="Card.TCheckbutton", command=self._apply_settings).pack(anchor="w", pady=(8, 2))
        ttk.Checkbutton(behaviour, text=tr("Double-click the desktop to hide or show the docks"),
                        variable=self.hide_dblclick_var, style="Card.TCheckbutton",
                        command=self._apply_settings).pack(anchor="w", pady=2)
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
            text=tr("On: docks stay above the wallpaper but behind apps.\n"
                    "Off: docks float above every window."),
            bg=theme.BG_ELEVATED, fg=theme.TEXT_DIM, font=theme.font(8),
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

    def _labelled_scale(self, parent, label: str, variable, low: float, high: float, step: float) -> None:
        row = tk.Frame(parent, bg=theme.BG_ELEVATED)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text=tr(label), bg=theme.BG_ELEVATED, fg=theme.TEXT_MUTED,
                 font=theme.font(9), width=18, anchor="w").pack(side="left")
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

    # -- about tab ---------------------------------------------------------
    def _build_about_tab(self) -> None:
        tab = self.about_tab
        tk.Label(tab, text="MesaDock " + __version__, bg=theme.BG_ELEVATED, fg=theme.TEXT,
                 font=theme.font(16, "bold")).pack(anchor="w", padx=18, pady=(18, 2))
        tk.Label(tab, text=tr("Every shortcut group, one desktop icon."), bg=theme.BG_ELEVATED,
                 fg=theme.TEXT_MUTED, font=theme.font(9)).pack(anchor="w", padx=18)
        tk.Label(tab, text=tr("Data folder"), bg=theme.BG_ELEVATED, fg=theme.TEXT_DIM,
                 font=theme.font(8, "bold")).pack(anchor="w", padx=18, pady=(18, 2))
        tk.Label(tab, text=str(paths.home_dir()), bg=theme.BG_ELEVATED, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(anchor="w", padx=18)

        row = tk.Frame(tab, bg=theme.BG_ELEVATED)
        row.pack(anchor="w", padx=18, pady=(16, 0))
        ttk.Button(row, text=tr("Open data folder"), style="Ghost.TButton",
                   command=self._open_data_folder).pack(side="left")
        ttk.Button(row, text=tr("Restore all archived shortcuts"), style="Ghost.TButton",
                   command=self._restore_archived).pack(side="left", padx=8)

        danger = tk.Frame(tab, bg=theme.BG_ELEVATED)
        danger.pack(anchor="w", padx=18, pady=(26, 0))
        ttk.Button(danger, text=tr("Quit MesaDock"), style="Danger.TButton",
                   command=lambda: self.app.quit("Manager > About > Quit button")).pack(side="left")

    def _apply_settings(self) -> None:
        if not getattr(self, "_settings_ready", True):
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
            settings.hide_on_double_click = bool(self.hide_dblclick_var.get())
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
            self.set_status(tr("Could not open ") + str(paths.home_dir()), error=True)

    def _restore_archived(self) -> None:
        restored = self.app.emergency_restore_all()
        self.set_status(tr("Restored {count} archived item(s)").format(count=restored))

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
    from tkinter import simpledialog

    return simpledialog.askstring(title, prompt, parent=parent) or ""

