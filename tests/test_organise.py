"""Automatic rules, tabs inside a dock, backup/restore and profile switching."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import zipfile

import pytest

from mesadock.core import backup, rules
from mesadock.core.models import DockFolder, DockItem

tk = pytest.importorskip("tkinter")


# --- rules ----------------------------------------------------------------
def test_rules_are_parsed_trimmed_and_deduplicated():
    assert rules.parse(" *.pdf , relatorio*;*.pdf\n .docx ") == ["*.pdf", "relatorio*", ".docx"]
    assert rules.clean(" a ;; b ") == "a, b"
    assert rules.parse("") == [] and rules.clean("  ,  ") == ""


@pytest.mark.parametrize("name, pattern, expected", [
    ("Relatório Anual.pdf", "*.pdf", True),
    ("Relatório Anual.pdf", "relatorio*", True),      # accents and case are ignored
    ("Relatório Anual.pdf", ".pdf", True),
    ("Relatório Anual.pdf", ".PDF", True),
    ("Relatório Anual.pdf", "anual", True),            # plain text: contained in the name
    ("Relatório Anual.pdf", ".docx", False),
    ("Steam.lnk", "steam", True),
    ("Steam.lnk", "ste?m", True),                      # wildcard against the visible name
    ("Steam.lnk", "*.lnk", True),
    ("Steam.lnk", "lnk", False),                       # ".lnk" is not part of what people see
    ("notas.txt", "*.pdf", False),
])
def test_rule_matching(name, pattern, expected):
    assert rules.matches(name, [pattern]) is expected


def test_the_first_dock_with_a_matching_rule_takes_the_item():
    docs = DockFolder(name="Docs", rules="*.pdf, .docx")
    games = DockFolder(name="Jogos", rules="steam, *.pdf")
    mirror = DockFolder(name="Pasta", portal="C:/x", rules="*")   # folder docks never take items
    plain = DockFolder(name="Sem regra")
    docks = [mirror, plain, docs, games]
    assert rules.pick_dock("manual.pdf", docks) is docs
    assert rules.pick_dock("Steam.lnk", docks) is games
    assert rules.pick_dock("foto.png", docks) is None
    assert rules.any_rules(docks) and not rules.any_rules([mirror, plain])


# --- backup ---------------------------------------------------------------
def _database(path, marker, home=None):
    """A real MesaDock database whose only dock is named after ``marker``."""
    document = {"profiles": [{"name": "Default", "folders": [{
        "name": marker, "id": "f_1",
        "items": [{"name": "a", "id": "i_1", "path": str((home or path.parent) / "items" / "f_1" / "a.lnk"),
                   "icon": ""}]}]}]}
    connection = sqlite3.connect(str(path))
    with connection:
        connection.execute("CREATE TABLE IF NOT EXISTS document (id INTEGER PRIMARY KEY CHECK (id = 1), "
                           "payload TEXT NOT NULL)")
        connection.execute("INSERT OR REPLACE INTO document (id, payload) VALUES (1, ?)", (json.dumps(document),))
    connection.close()


def _dock_name(path):
    connection = sqlite3.connect(str(path))
    try:
        payload = connection.execute("SELECT payload FROM document WHERE id = 1").fetchone()[0]
    finally:
        connection.close()
    return json.loads(payload)["profiles"][0]["folders"][0]["name"]


def _data(home, marker):
    home.mkdir(parents=True, exist_ok=True)
    _database(home / "store.db", marker)
    (home / "items" / "f_1").mkdir(parents=True, exist_ok=True)
    (home / "items" / "f_1" / "a.lnk").write_text("lnk-" + marker, encoding="utf-8")
    (home / "archived" / "Default").mkdir(parents=True, exist_ok=True)
    (home / "archived" / "Default" / "b.lnk").write_text("arc-" + marker, encoding="utf-8")
    (home / "logs").mkdir(exist_ok=True)
    (home / "logs" / "mesadock.log").write_text("log", encoding="utf-8")


def test_backup_round_trip_keeps_what_it_replaces(tmp_path):
    home = tmp_path / "home"
    _data(home, "one")
    archive = backup.create(tmp_path / "out" / "copy.zip", home, version="9.9")
    manifest = backup.read_manifest(archive)
    assert manifest["app"] == "MesaDock" and manifest["version"] == "9.9"
    assert set(manifest["entries"]) == {"store.db", "items", "archived"}
    with zipfile.ZipFile(archive) as packed:
        assert not any(name.startswith("logs") for name in packed.namelist()), "logs are not backed up"
    assert not list((tmp_path / "out").glob("*.part")) and not list((tmp_path / "out").glob("*.db"))

    _data(home, "two")
    (home / "items" / "f_1" / "extra.lnk").write_text("new", encoding="utf-8")
    (home / "archived" / "Default" / "later.lnk").write_text("archived after the backup", encoding="utf-8")
    kept = backup.restore(archive, home)

    assert _dock_name(home / "store.db") == "one"
    assert (home / "items" / "f_1" / "a.lnk").read_text(encoding="utf-8") == "lnk-one"
    assert not (home / "items" / "f_1" / "extra.lnk").exists()
    assert (home / "archived" / "Default" / "b.lnk").read_text(encoding="utf-8") == "arc-one"
    # an original archived after the backup stays reachable, it is not left behind
    assert (home / "archived" / "Default" / "later.lnk").exists()
    # what was there before the restore is still on disk
    assert _dock_name(kept / "store.db") == "two"
    assert (kept / "items" / "f_1" / "extra.lnk").read_text(encoding="utf-8") == "new"
    assert not list(home.glob("restore-*")), "the staging folder is removed"


def test_restore_fails_cleanly_when_a_file_is_in_use(tmp_path):
    """A document opened from a dock keeps its copy in items/ locked. The restore
    must then change nothing at all, not move half of the folder."""
    home = tmp_path / "home"
    _data(home, "one")
    archive = backup.create(tmp_path / "copy.zip", home)
    _data(home, "two")
    for index in range(5):
        (home / "items" / "f_1" / ("doc%d.txt" % index)).write_text("x", encoding="utf-8")
    before = sorted(p.name for p in (home / "items" / "f_1").iterdir())

    with open(home / "items" / "f_1" / "doc2.txt", "rb"):   # held open, as a viewer would
        with pytest.raises(backup.BackupError):
            backup.restore(archive, home)

    assert sorted(p.name for p in (home / "items" / "f_1").iterdir()) == before, "items/ is untouched"
    assert _dock_name(home / "store.db") == "two", "and so is the database"
    assert (home / "archived" / "Default" / "b.lnk").read_text(encoding="utf-8") == "arc-two"
    assert not list(home.glob("restore-*"))
    kept = backup.restore(archive, home)                     # once the file is closed it works
    assert _dock_name(home / "store.db") == "one" and kept.is_dir()


def test_restore_refuses_files_that_are_not_backups(tmp_path):
    home = tmp_path / "home"
    _data(home, "keep")
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as packed:
        packed.writestr("store.db", "x")
    with pytest.raises(backup.BackupError):
        backup.restore(plain, home)
    text = tmp_path / "note.zip"
    text.write_text("not a zip", encoding="utf-8")
    with pytest.raises(backup.BackupError):
        backup.read_manifest(text)
    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(newer, "w") as packed:
        packed.writestr(backup.MANIFEST, json.dumps({"app": "MesaDock", "format": 99}))
    with pytest.raises(backup.BackupError):
        backup.read_manifest(newer)
    assert _dock_name(home / "store.db") == "keep"


@pytest.mark.parametrize("member", ["../evil.txt", "items/../../evil.txt", "C:/evil.txt", "other/file.txt",
                                    "store.db/inner", "items", "archived", "items//x"])
def test_restore_refuses_paths_outside_the_data_entries(tmp_path, member):
    home = tmp_path / "home"
    _data(home, "keep")
    good = tmp_path / "good.db"
    _database(good, "evil")
    crafted = tmp_path / "crafted.zip"
    with zipfile.ZipFile(crafted, "w") as packed:
        packed.writestr(backup.MANIFEST, json.dumps({"app": "MesaDock", "format": 1}))
        packed.write(good, "store.db")
        packed.writestr(member, "evil")
    with pytest.raises(backup.BackupError):
        backup.restore(crafted, home)
    assert _dock_name(home / "store.db") == "keep"
    assert (home / "items").is_dir() and (home / "archived").is_dir()
    assert not (tmp_path / "evil.txt").exists()


def test_restore_refuses_a_database_that_cannot_be_read(tmp_path):
    """Otherwise the app would reload an empty profile and report success."""
    home = tmp_path / "home"
    _data(home, "keep")
    crafted = tmp_path / "broken.zip"
    with zipfile.ZipFile(crafted, "w") as packed:
        packed.writestr(backup.MANIFEST, json.dumps({"app": "MesaDock", "format": 1}))
        packed.writestr("store.db", "garbage, not SQLite")
    with pytest.raises(backup.BackupError):
        backup.restore(crafted, home)
    assert _dock_name(home / "store.db") == "keep"
    assert (home / "items" / "f_1" / "a.lnk").exists()


def test_restore_on_another_data_folder_repoints_the_stored_paths(tmp_path):
    """Item paths are absolute; a backup taken as another user or on another PC
    would otherwise restore docks whose every item is broken."""
    old_home = tmp_path / "UserA" / "MesaDock"
    _data(old_home, "one")
    archive = backup.create(tmp_path / "copy.zip", old_home)
    new_home = tmp_path / "UserB" / "MesaDock"
    new_home.mkdir(parents=True)
    backup.restore(archive, new_home)
    connection = sqlite3.connect(str(new_home / "store.db"))
    document = json.loads(connection.execute("SELECT payload FROM document").fetchone()[0])
    connection.close()
    item_path = document["profiles"][0]["folders"][0]["items"][0]["path"]
    assert item_path == str(new_home / "items" / "f_1" / "a.lnk")
    assert (new_home / "items" / "f_1" / "a.lnk").exists()


def test_backup_survives_a_file_dated_before_1980(tmp_path):
    home = tmp_path / "home"
    _data(home, "one")
    old = home / "items" / "f_1" / "old.txt"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (86400 * 365, 86400 * 365))               # 1971
    archive = backup.create(tmp_path / "copy.zip", home)
    with zipfile.ZipFile(archive) as packed:
        assert "items/f_1/old.txt" in packed.namelist()


def test_automatic_backup_is_daily_and_keeps_only_the_newest(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert backup.auto_backup(home) is None, "nothing to back up before the first save"
    _data(home, "x")
    first = backup.auto_backup(home, keep=2)
    assert first is not None and first.parent == backup.backups_dir(home)
    assert backup.auto_backup(home, keep=2) is None, "one already exists today"
    for index in range(3):
        time.sleep(1.05)  # names carry the second
        assert backup.auto_backup(home, keep=2, min_hours=0) is not None, index
    assert len(list(backup.backups_dir(home).glob("auto-*.zip"))) == 2


# --- the app ---------------------------------------------------------------
@pytest.fixture(scope="module")
def tk_available():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk")
    root.destroy()
    return True


def _app(home, style="grid", names=("Chrome", "Steam", "Notepad", "Epic"), background_watch=True):
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    store.settings.animations = False
    store.settings.show_labels = True
    folder = DockFolder(name="Work", style=style, position=(60, 90))
    for name in names:
        folder.add_item(DockItem(name=name, kind="shortcut", target="C:/Windows/notepad.exe"))
    store.profiles[0].folders = [folder]
    store.save()
    app = MesaDockApp(store=store)
    app.background_watch = background_watch
    app.start(minimized=True)
    app.root.update()
    return app, folder


def test_tabs_are_created_tidied_and_filter_the_panel(home, tk_available):
    app, folder = _app(home)
    try:
        chrome, steam, notepad, epic = folder.items
        app.set_item_tab(folder.id, steam.id, "  Jogos  ")
        app.set_item_tab(folder.id, epic.id, "Jogos")
        app.set_item_tab(folder.id, chrome.id, "Web")
        assert folder.tabs == ["Jogos", "Web"] and steam.tab == "Jogos"

        app.pin_panels(True)
        app.open_panel(folder, force=True)
        app.root.update()
        panel = app.panels[folder.id]
        assert [name for name, *_box in panel._tab_boxes] == ["", "Jogos", "Web"]
        assert len(panel._items) == 4, "no tab selected: everything is shown"
        tall = panel.layout.height

        # Clicking a tab button selects it and the panel shows only its items.
        _name, left, top, right, bottom = panel._tab_boxes[1]

        class Click:
            x, y = (left + right) // 2, (top + bottom) // 2

        panel._on_click(Click)
        assert folder.active_tab == "Jogos"
        assert [item.name for item in panel._items] == ["Steam", "Epic"]
        # The panel keeps its size on every tab, so the tab strip stays under the pointer.
        assert panel.layout.height == tall and len(panel._hovered_items) == 2
        assert panel._index_at(*[int(v) for v in (panel._hovered_items[0][0] + 5, panel._hovered_items[0][1] + 5)]) == 0

        # Removing the last item of a tab removes the tab too (no empty, orphan tab).
        app.remove_item(folder.id, chrome.id, restore=False)
        assert folder.tabs == ["Jogos"]

        # Emptying a tab removes it, and the selection falls back to "all".
        app.set_item_tab(folder.id, steam.id, "")
        app.set_item_tab(folder.id, epic.id, "")
        assert folder.tabs == [] and folder.active_tab == ""
        assert len(app.panels[folder.id]._items) == 3
    finally:
        app.quit()


def test_ring_panels_show_every_item_and_no_tab_bar(home, tk_available):
    app, folder = _app(home, style="ring")
    try:
        app.set_item_tab(folder.id, folder.items[0].id, "Web")
        folder.active_tab = "Web"
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        app.root.update()
        panel = app.panels[folder.id]
        assert panel._tab_boxes == [] and len(panel._items) == 4
    finally:
        app.quit()


def test_rules_file_only_new_stable_desktop_items(home, tk_available, tmp_path, monkeypatch):
    from mesadock.core import archive

    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "antigo.pdf").write_text("old", encoding="utf-8")
    monkeypatch.setattr(archive, "user_desktop_dirs", lambda: [desktop])
    app, folder = _app(home, names=(), background_watch=False)
    try:
        queued = []
        monkeypatch.setattr(app, "_enqueue_tk", lambda callback: queued.append(callback))

        app._scan_desktop_arrivals()
        assert app._desktop_known is None, "no dock has rules: nothing is watched"

        assert app.set_dock_rules(folder.id, " *.pdf ; relatorio* ") == "*.pdf, relatorio*"
        app._scan_desktop_arrivals()                       # baseline: what is there stays there
        assert not queued and str(desktop / "antigo.pdf") in app._desktop_known

        new = desktop / "novo.pdf"
        new.write_text("a", encoding="utf-8")
        (desktop / "foto.png").write_text("p", encoding="utf-8")
        app._scan_desktop_arrivals()
        assert not queued, "a file must look the same on two passes before it is taken"
        app._scan_desktop_arrivals()
        assert len(queued) == 1
        queued.pop()()                                     # run it as the Tk thread would
        assert [item.name for item in folder.items] == ["novo"], "only the .pdf; the .png matches no rule"

        app._scan_desktop_arrivals()
        app._scan_desktop_arrivals()
        assert not queued, "already filed: not taken again"

        # A file MesaDock itself puts back on the desktop is not a new arrival.
        app.remove_item(folder.id, folder.items[0].id, restore=True)
        (desktop / "devolvido.pdf").write_text("r", encoding="utf-8")
        app._scan_desktop_arrivals()
        app._scan_desktop_arrivals()
        assert not queued and folder.items == []
    finally:
        app.quit()


def test_backup_and_restore_through_the_app(home, tk_available, tmp_path):
    app, folder = _app(home)
    try:
        target = tmp_path / "saved.zip"
        assert app.backup_to(str(target)) and target.is_file()

        app.rename_dock(folder.id, "Mudou")
        app.add_dock("Outra", "grid")
        app.store.save()
        assert len(app.store.folders) == 2

        assert app.restore_from(str(target))
        assert [f.name for f in app.store.folders] == ["Work"]
        assert set(app.docks) == {app.store.folders[0].id}, "the docks on screen follow the restored data"
        assert not app.restore_from(str(tmp_path / "missing.zip"))
        assert [f.name for f in app.store.folders] == ["Work"]
    finally:
        app.quit()


def test_next_profile_cycles_and_does_nothing_with_one(home, tk_available):
    app, _folder = _app(home)
    try:
        app.next_profile()
        assert app.store.active_profile_index == 0
        app.add_profile("Casa")
        app.switch_profile(0)
        app.next_profile()
        assert app.store.active_profile.name == "Casa" and app.docks == {}
        app.next_profile()
        assert app.store.active_profile_index == 0 and len(app.docks) == 1
    finally:
        app.quit()


def test_rules_ignore_downloads_in_progress_and_empty_files(home, tk_available, tmp_path, monkeypatch):
    from mesadock.core import archive

    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(archive, "user_desktop_dirs", lambda: [desktop])
    app, folder = _app(home, names=(), background_watch=False)
    try:
        queued = []
        monkeypatch.setattr(app, "_enqueue_tk", lambda callback: queued.append(callback))
        app.set_dock_rules(folder.id, "*.pdf, relatorio")
        app._scan_desktop_arrivals()                                    # baseline

        (desktop / "relatorio.pdf.crdownload").write_text("partial", encoding="utf-8")   # Chrome
        (desktop / "manual.pdf").write_text("", encoding="utf-8")                        # Firefox placeholder...
        (desktop / "manual.pdf.part").write_text("partial", encoding="utf-8")            # ...next to its .part
        (desktop / "vazio.pdf").write_text("", encoding="utf-8")                         # nothing in it yet
        for _ in range(3):
            app._scan_desktop_arrivals()
        assert not queued, "nothing is complete yet"

        (desktop / "manual.pdf.part").unlink()                           # the download finished
        (desktop / "manual.pdf").write_text("%PDF", encoding="utf-8")
        app._scan_desktop_arrivals()
        app._scan_desktop_arrivals()
        assert len(queued) == 1
        queued.pop()()
        assert [item.name for item in folder.items] == ["manual"]
    finally:
        app.quit()


def test_files_put_back_by_mesadock_are_never_taken_again(home, tk_available, tmp_path, monkeypatch):
    """Whenever the scan happens around a restore (before, during or after it),
    the returned file must not go back into a dock."""
    from mesadock.core import archive

    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(archive, "user_desktop_dirs", lambda: [desktop])
    app, folder = _app(home, names=("Antigo",), background_watch=False)
    try:
        queued = []
        monkeypatch.setattr(app, "_enqueue_tk", lambda callback: queued.append(callback))
        app.set_dock_rules(folder.id, "*.pdf")
        app._scan_desktop_arrivals()

        # A scan that already queued an arrival just before the restore began:
        (desktop / "a.pdf").write_text("x", encoding="utf-8")
        app._scan_desktop_arrivals()
        app._scan_desktop_arrivals()
        assert len(queued) == 1
        app.remove_item(folder.id, folder.items[0].id, restore=True)     # starts the quiet period
        queued.pop()()
        assert folder.items == [], "the queued arrival is dropped"

        # A scan in the middle of the restore, then the file lands on the desktop:
        app._scan_desktop_arrivals()
        (desktop / "devolvido.pdf").write_text("x", encoding="utf-8")
        for _ in range(3):
            app._scan_desktop_arrivals()
        assert not queued and folder.items == []

        # After the quiet period new files are filed normally again.
        app._desktop_quiet_until = 0.0
        (desktop / "novo.pdf").write_text("x", encoding="utf-8")
        app._scan_desktop_arrivals()
        app._scan_desktop_arrivals()
        assert len(queued) == 1
        queued.pop()()
        assert [item.name for item in folder.items] == ["novo"]
    finally:
        app.quit()


def test_an_open_menu_or_dialog_keeps_the_panel_open(home, tk_available):
    """Choosing a tab from the item menu moved the pointer off the panel, and the
    auto-close shut the panel in the middle of it."""
    app, folder = _app(home)
    try:
        app.open_panel(folder, force=True)
        app.root.update()
        assert folder.id in app.panels
        with app.hold_panels():
            app._schedule_close()
            assert app._close_timer is None, "no close is even scheduled while held"
            app._close_now()                       # a timer already running when the menu opened
            assert folder.id in app.panels and app.panels[folder.id].is_alive()
        assert app._held == 0
        app._schedule_close()
        assert app._close_timer is not None, "auto-close works again afterwards"
    finally:
        app.quit()


def test_several_items_can_be_filed_under_a_new_tab_at_once(home, tk_available, monkeypatch):
    from tkinter import simpledialog

    app, folder = _app(home)
    try:
        chrome, steam, _notepad, epic = folder.items
        held = []
        monkeypatch.setattr(simpledialog, "askstring", lambda *a, **k: held.append(app._held) or "  Jogos ")
        app.prompt_items_tab(folder.id, [steam.id, epic.id])
        assert held == [1], "the panel is held while the name is typed"
        assert steam.tab == epic.tab == "Jogos" and chrome.tab == ""
        assert folder.tabs == ["Jogos"]

        # the tab menu marks the tab that all the selected items share
        menu = app.tab_menu(folder, [steam, epic])
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
        assert labels[0].startswith("✓") and "Jogos" in labels[0]
        assert any("Sem aba" in label or "No tab" in label for label in labels)

        app.set_items_tab(folder.id, [steam.id, epic.id], "")
        assert folder.tabs == [] and steam.tab == ""

        monkeypatch.setattr(simpledialog, "askstring", lambda *a, **k: "   ")
        app.prompt_items_tab(folder.id, [chrome.id])
        assert chrome.tab == "" and folder.tabs == [], "an empty name changes nothing"
    finally:
        app.quit()
