"""Adding, archiving and restoring items without ever losing a file."""
from __future__ import annotations

import os
from pathlib import Path

from mesadock.core import paths
from mesadock.core.archive import Archiver, desktop_shortcuts, safe_filename, unique_path, user_desktop_dirs
from mesadock.core.models import DockItem
from conftest import make_file


def test_safe_filename_strips_illegal_characters():
    assert safe_filename('a<>:"/\\|?*b') == "ab"
    assert safe_filename("   ") == "item"
    assert safe_filename("ok name.txt") == "ok name.txt"


def test_unique_path_never_overwrites(tmp_path):
    first = unique_path(tmp_path, "item.txt")
    first.write_text("a", encoding="utf-8")
    second = unique_path(tmp_path, "item.txt")
    assert second.name == "item (2).txt"
    second.write_text("b", encoding="utf-8")
    third = unique_path(tmp_path, "item.txt")
    assert third.name == "item (3).txt"


def test_add_url_creates_an_internet_shortcut(home):
    archiver = Archiver("Default", "copy")
    result = archiver.add_url("example.com", "dock1")
    assert result.ok and result.item is not None
    assert result.item.kind == "url"
    assert result.item.target == "https://example.com"
    assert os.path.exists(result.item.path)


def test_add_file_in_copy_mode_keeps_the_original(home, desktop_dir):
    original = make_file(desktop_dir, "Tool.lnk")
    archiver = Archiver("Default", "copy")
    result = archiver.add_from_path(original, "dock1")
    assert result.ok
    assert original.exists()
    assert result.item.archived_from == ""
    assert os.path.exists(result.item.path)


def test_add_file_in_move_mode_archives_the_desktop_original(home, desktop_dir):
    original = make_file(desktop_dir, "Game.lnk")
    archiver = Archiver("Default", "move")
    result = archiver.add_from_path(original, "dock1")
    assert result.ok
    assert not original.exists(), "the desktop original should be tucked away"
    assert result.item.archived_from, "the original desktop path is remembered"
    assert Path(result.item.archived_from) == original
    assert any(p.name.endswith("Game.lnk") for p in paths.archive_dir("Default").iterdir())
    assert os.path.exists(result.item.path), "MesaDock keeps its own copy"


def test_move_mode_leaves_files_outside_the_desktop_alone(home, tmp_path):
    outside = tmp_path / "Downloads"
    outside.mkdir()
    source = make_file(outside, "setup.exe")
    archiver = Archiver("Default", "move")
    result = archiver.add_from_path(source, "dock1")
    assert result.ok
    assert source.exists()


def test_restore_puts_the_original_back(home, desktop_dir):
    original = make_file(desktop_dir, "Restore.lnk")
    archiver = Archiver("Default", "move")
    result = archiver.add_from_path(original, "dock1")
    assert not original.exists()
    assert archiver.restore_original(result.item) is True
    assert original.exists()


def test_release_item_restores_and_deletes_the_copy(home, desktop_dir):
    original = make_file(desktop_dir, "Release.lnk")
    archiver = Archiver("Default", "move")
    result = archiver.add_from_path(original, "dock1")
    copy_path = result.item.path
    archiver.release_item(result.item)
    assert original.exists()
    assert not os.path.exists(copy_path)


def test_release_item_ignores_files_outside_the_items_folder(home, tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("important", encoding="utf-8")
    archiver = Archiver("Default", "copy")
    item = DockItem(name="keep", kind="file", path=str(outside))
    archiver.release_item(item)
    assert outside.exists()


def test_missing_source_is_reported(home):
    archiver = Archiver("Default", "move")
    result = archiver.add_from_path(home / "does-not-exist.lnk", "dock1")
    assert result.ok is False
    assert "Not found" in result.message


def test_folders_are_linked_in_place(home, tmp_path):
    folder = tmp_path / "Projects"
    folder.mkdir()
    archiver = Archiver("Default", "move")
    result = archiver.add_from_path(folder, "dock1")
    assert result.ok and result.item.kind == "folder"
    assert folder.exists()


def test_restore_all_reports_the_count(home, desktop_dir):
    archiver = Archiver("Default", "move")
    items = []
    for name in ("a.lnk", "b.lnk"):
        source = make_file(desktop_dir, name)
        result = archiver.add_from_path(source, "dock1")
        items.append(result.item)
    assert archiver.restore_all(items) == 2
    assert (desktop_dir / "a.lnk").exists() and (desktop_dir / "b.lnk").exists()


def test_archive_lives_under_the_profile_folder(home):
    archiver = Archiver("Work profile", "move")
    assert archiver.archive_dir() == paths.archive_dir("Work profile")


def test_desktop_shortcuts_reads_the_fake_desktop(desktop_dir):
    make_file(desktop_dir, "one.lnk")
    make_file(desktop_dir, "two.url")
    make_file(desktop_dir, "notes.txt")
    found = [p.name for p in desktop_shortcuts()]
    assert "one.lnk" in found and "two.url" in found
    assert "notes.txt" not in found


def test_user_desktop_dirs_is_never_empty():
    assert user_desktop_dirs() != []


def test_restore_uses_the_desktop_windows_reports(home, tmp_path, monkeypatch):
    # Regression: restoring moved the file back to the recorded path even when
    # that path was no longer the desktop (OneDrive redirection, localized folder
    # name, or an older build guessing home/Desktop). The shortcut then existed
    # but the user never saw it, because it was in a folder the shell hides.
    from mesadock.core import archive as archive_mod

    wrong = tmp_path / "Desktop"
    wrong.mkdir()
    real = tmp_path / "Área de Trabalho"
    real.mkdir()
    # At add time the old folder was the desktop; by restore time the desktop has
    # been redirected to a different folder.
    monkeypatch.setattr(archive_mod, "user_desktop_dirs", lambda: [wrong])
    monkeypatch.setattr(archive_mod.shell, "known_desktop_dir", lambda: real)

    original = make_file(wrong, "Tool.lnk")
    archiver = Archiver("Default", "move")
    result = archiver.add_from_path(original, "dock1")
    assert result.ok and not original.exists()

    monkeypatch.setattr(archive_mod, "user_desktop_dirs", lambda: [real])
    assert archiver.restore_original(result.item) is True
    assert (real / "Tool.lnk").exists()
    assert not (wrong / "Tool.lnk").exists()
