"""Folder portals (a dock mirroring a folder) and the quick search."""
from __future__ import annotations

from mesadock.core import portal, search
from mesadock.core.models import DockFolder, DockItem


# --- portal ---------------------------------------------------------------
def _populate(folder):
    (folder / "Zeta.txt").write_text("z", encoding="utf-8")
    (folder / "alpha.pdf").write_text("a", encoding="utf-8")
    (folder / "Site.url").write_text("[InternetShortcut]\nURL=https://example.com\n", encoding="utf-8")
    (folder / "Projects").mkdir()
    (folder / "desktop.ini").write_text("", encoding="utf-8")
    (folder / ".hidden").write_text("", encoding="utf-8")
    (folder / "~$draft.docx").write_text("", encoding="utf-8")


def test_scan_lists_folders_first_and_skips_system_files(tmp_path):
    _populate(tmp_path)
    entries = portal.scan(tmp_path)
    assert [(name, kind) for name, kind, _path in entries] == [
        ("Projects", "folder"),
        ("alpha.pdf", "file"),
        ("Site", "shortcut"),
        ("Zeta.txt", "file"),
    ]


def test_a_missing_folder_is_unavailable_not_empty(tmp_path):
    assert portal.scan(tmp_path / "unplugged") is None
    assert portal.signature(tmp_path / "unplugged") == ("<unavailable>",)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert portal.scan(empty) == []


def test_an_unplugged_folder_keeps_items_ids_and_icons(tmp_path):
    """A drive that goes away must not wipe the dock: when it is back the same
    entries have to keep their id and custom icon."""
    source = tmp_path / "Drive"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    dock = DockFolder(name="Drive", portal=str(source))
    portal.sync_items(dock)
    dock.items[0].icon = "C:/custom.png"
    kept_id = dock.items[0].id

    gone = tmp_path / "Offline"
    source.rename(gone)
    assert portal.sync_items(dock) is False
    assert [item.id for item in dock.items] == [kept_id]

    gone.rename(source)
    assert portal.sync_items(dock) is False
    assert dock.items[0].id == kept_id and dock.items[0].icon == "C:/custom.png"


def test_scan_respects_the_limit(tmp_path):
    for index in range(10):
        (tmp_path / ("f%02d.txt" % index)).write_text("x", encoding="utf-8")
    assert len(portal.scan(tmp_path, limit=4)) == 4


def test_sync_keeps_ids_and_custom_icons_of_entries_that_stay(tmp_path):
    _populate(tmp_path)
    dock = DockFolder(name="Docs", portal=str(tmp_path))
    assert portal.sync_items(dock) is True
    assert len(dock.items) == 4
    kept = next(item for item in dock.items if item.name == "alpha.pdf")
    kept.icon = "C:/custom.png"
    kept_id = kept.id

    assert portal.sync_items(dock) is False  # nothing changed on disk

    (tmp_path / "Zeta.txt").unlink()
    (tmp_path / "New.txt").write_text("n", encoding="utf-8")
    before = portal.signature(tmp_path)
    assert portal.sync_items(dock) is True
    names = [item.name for item in dock.items]
    assert "Zeta.txt" not in names and "New.txt" in names
    same = next(item for item in dock.items if item.name == "alpha.pdf")
    assert same.id == kept_id and same.icon == "C:/custom.png"
    assert portal.signature(tmp_path) == before


def test_signature_changes_when_an_entry_is_added(tmp_path):
    first = portal.signature(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    assert portal.signature(tmp_path) != first


def test_a_normal_dock_is_never_touched_by_sync():
    dock = DockFolder(name="Work")
    dock.add_item(DockItem(name="Notepad", target="C:/Windows/notepad.exe"))
    assert portal.sync_items(dock) is False
    assert len(dock.items) == 1


def test_portal_field_round_trips_through_the_model(tmp_path):
    dock = DockFolder(name="Docs", portal=str(tmp_path))
    assert DockFolder.from_dict(dock.to_dict()).portal == str(tmp_path)
    assert DockFolder(name="Plain").portal == ""


# --- search ---------------------------------------------------------------
def _docks():
    work = DockFolder(name="Trabalho")
    for name in ("Chrome", "Chrome Remote Desktop", "Área de Trabalho Remota", "MEU_HUB_WHATSAPP", "Notepad"):
        work.add_item(DockItem(name=name, target="x"))
    games = DockFolder(name="Jogos")
    games.add_item(DockItem(name="Steam", target="x"))
    return [work, games]


def _names(query, limit=8):
    return [hit.item.name for hit in search.search(query, _docks(), limit)]


def test_empty_query_lists_nothing():
    assert _names("") == [] and _names("   ") == []


def test_prefix_beats_substring_and_shorter_names_win_ties():
    assert _names("chr")[:2] == ["Chrome", "Chrome Remote Desktop"]
    assert _names("rem")[0] == "Chrome Remote Desktop"


def test_search_ignores_case_and_accents():
    assert _names("AREA") == ["Área de Trabalho Remota"]
    assert _names("área") == ["Área de Trabalho Remota"]


def test_every_word_must_match_and_separators_split_words():
    assert _names("chrome desk") == ["Chrome Remote Desktop"]
    assert _names("whats") == ["MEU_HUB_WHATSAPP"]
    assert _names("chrome xyz") == []


def test_the_dock_name_also_matches_and_the_limit_applies():
    assert _names("jogos") == ["Steam"]
    assert len(_names("o", limit=2)) == 2
