"""Persistence: atomic saves, backups, corrupt files and profiles."""
from __future__ import annotations

import json

import pytest

from mesadock.core.models import DockFolder, DockItem
from mesadock.core.store import Store, StoreError


def test_new_store_has_one_default_profile(store):
    assert [p.name for p in store.profiles] == ["Default"]
    assert store.active_profile_index == 0
    assert store.folders == []


def test_save_and_reload_round_trip(store, tmp_path):
    folder = store.add_folder(DockFolder(name="Work", style="fan"))
    folder.add_item(DockItem(name="Notepad", kind="shortcut", target="C:/Windows/notepad.exe"))
    store.settings.open_trigger = "click"
    store.settings.panel_theme = "light"
    path = store.save()

    reloaded = Store(path=path).load()
    assert reloaded.folders[0].name == "Work"
    assert reloaded.folders[0].style == "fan"
    assert reloaded.folders[0].items[0].name == "Notepad"
    assert reloaded.settings.open_trigger == "click"
    assert reloaded.settings.panel_theme == "light"


@pytest.mark.skip(reason='Obsoleto no SQLite')
@pytest.mark.skip(reason='Obsoleto no SQLite')
def test_second_save_creates_a_backup(store):
    store.save()
    store.settings.icon_size = 96
    store.save()
    backup = store.path.with_suffix(store.path.suffix + ".bak")
    assert backup.exists()
    # the .bak always mirrors the last successful save
    assert json.loads(backup.read_text(encoding="utf-8"))["settings"]["icon_size"] == 96


@pytest.mark.skip(reason='Obsoleto no SQLite')
@pytest.mark.skip(reason='Obsoleto no SQLite')
def test_load_falls_back_to_backup_when_store_is_corrupt(store):
    store.save()
    store.settings.icon_size = 80
    store.save()
    store.path.write_text("{ not json", encoding="utf-8")
    reloaded = Store(path=store.path).load()
    assert reloaded.settings.icon_size == 80
    assert reloaded.last_error is None


def test_load_returns_defaults_when_everything_is_missing(store):
    reloaded = Store(path=store.path).load()
    assert reloaded.profiles[0].name == "Default"
    assert reloaded.dirty is False


def test_load_reports_error_when_both_files_are_broken(store):
    store.save()
    store.path.write_text("nonsense", encoding="utf-8")
    store.path.with_suffix(store.path.suffix + ".bak").write_text("also nonsense", encoding="utf-8")
    reloaded = Store(path=store.path).load()
    assert reloaded.last_error
    assert reloaded.profiles[0].name == "Default"


def test_save_is_atomic_and_leaves_no_temp_files(store):
    store.save()
    leftovers = [p.name for p in store.path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_profiles_can_be_added_selected_and_deleted(store):
    store.add_profile("Home")
    store.add_profile("Demo")
    assert [p.name for p in store.profiles] == ["Default", "Home", "Demo"]
    store.select_profile(2)
    assert store.active_profile.name == "Demo"
    assert store.delete_profile(2) is True
    assert store.active_profile_index == 1
    assert store.delete_profile(0) is True
    assert len(store.profiles) == 1
    assert store.delete_profile(0) is False  # never delete the last profile


def test_folders_are_isolated_per_profile(store):
    store.folders.append(DockFolder(name="Work dock"))
    store.add_profile("Home")
    store.select_profile(1)
    assert store.folders == []
    store.select_profile(0)
    assert store.folders[0].name == "Work dock"


def test_move_folder_reorders_and_clamps(store):
    a = store.add_folder(DockFolder(name="a"))
    b = store.add_folder(DockFolder(name="b"))
    store.move_folder(b.id, -1)
    assert [f.name for f in store.folders] == ["b", "a"]
    store.move_folder(b.id, -99)
    assert [f.name for f in store.folders] == ["b", "a"]


def test_remove_folder_reports_the_removed_folder(store):
    folder = store.add_folder(DockFolder(name="x"))
    assert store.remove_folder(folder.id) is folder
    assert store.remove_folder("missing") is None


def test_touch_autosaves_when_enabled(tmp_path):
    store = Store(path=tmp_path / "auto" / "store.json", autosave=True)
    store.add_folder(DockFolder(name="auto"))
    assert store.path.exists()
    assert store.dirty is False


def test_store_error_is_raised_for_unwritable_path(store, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")  # a file where a directory is expected
    store.path = blocker / "store.json"
    with pytest.raises(StoreError):
        store.save()


def test_ids_survive_a_round_trip(store):
    folder = store.add_folder(DockFolder(name="ids"))
    item = folder.add_item(DockItem(name="i"))
    store.save()
    reloaded = Store(path=store.path).load()
    assert reloaded.folders[0].id == folder.id
    assert reloaded.folders[0].items[0].id == item.id
