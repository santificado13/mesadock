"""Data model behaviour and serialisation."""
from __future__ import annotations

from mesadock.core.models import (
    DOCK_STYLES,
    DockFolder,
    DockItem,
    Profile,
    Settings,
    new_id,
)


def test_new_id_is_unique_and_prefixed():
    first = new_id("f_")
    second = new_id("f_")
    assert first.startswith("f_") and first != second and len(first) > 8


def test_item_defaults_and_validation():
    item = DockItem(name="  ")
    assert item.name == "Untitled"
    assert item.kind == "shortcut"
    bad = DockItem(name="x", kind="nonsense")
    assert bad.kind == "file"


def test_item_path_falls_back_to_target():
    item = DockItem(name="link", target="https://example.com")
    assert item.path == "https://example.com"


def test_item_round_trip():
    item = DockItem(name="Notepad", kind="shortcut", path="C:/Windows/notepad.exe",
                    target="C:/Windows/notepad.exe", args="--x", icon="i.png")
    restored = DockItem.from_dict(item.to_dict())
    assert restored.to_dict() == item.to_dict()


def test_folder_rejects_unknown_style_and_clamps_icon():
    folder = DockFolder(name="Dock", style="spiral", icon_size=9999)
    assert folder.style == "grid"
    assert folder.icon_size == 160


def test_folder_item_operations():
    folder = DockFolder(name="Work")
    a = folder.add_item(DockItem(name="a"))
    b = folder.add_item(DockItem(name="b"))
    c = folder.add_item(DockItem(name="c"))
    assert folder.item_by_id(b.id) is b
    folder.move_item(c.id, -1)
    assert [i.name for i in folder.items] == ["a", "c", "b"]
    folder.move_item(a.id, -5)
    assert [i.name for i in folder.items] == ["a", "c", "b"]
    assert folder.remove_item(b.id) is b
    assert folder.remove_item("missing") is None
    assert [i.name for i in folder.items] == ["a", "c"]


def test_folder_round_trip_preserves_position():
    folder = DockFolder(name="Media", style="ring", position=(120, 340), icon="custom.png")
    folder.add_item(DockItem(name="clip.mp4", kind="file"))
    restored = DockFolder.from_dict(folder.to_dict())
    assert restored.style == "ring"
    assert restored.position == (120, 340)
    assert restored.items[0].name == "clip.mp4"


def test_all_styles_are_accepted():
    for style in DOCK_STYLES:
        assert DockFolder(name="d", style=style).style == style


def test_settings_clamp_and_validate():
    settings = Settings(panel_opacity=9, hover_delay_ms=-4, icon_size=4, open_trigger="magic")
    assert settings.panel_opacity == 1.0
    assert settings.hover_delay_ms == 0
    assert settings.icon_size == 32
    assert settings.open_trigger == "hover"


def test_settings_round_trip_ignores_unknown_keys():
    settings = Settings(archive_mode="copy", panel_theme="light")
    data = settings.to_dict()
    data["future_option"] = True
    restored = Settings.from_dict(data)
    assert restored.archive_mode == "copy"
    assert restored.panel_theme == "light"


def test_profile_round_trip():
    profile = Profile(name="Work", folders=[DockFolder(name="Office")])
    restored = Profile.from_dict(profile.to_dict())
    assert restored.name == "Work"
    assert restored.folders[0].name == "Office"
