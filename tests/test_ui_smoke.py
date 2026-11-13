"""UI smoke tests: Tk really builds the docks, panels and Manager.

These run headless-ish: the desktop integration is disabled by conftest and the
data folder is temporary, but real Tk windows are created when a display exists.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")
tkfont = pytest.importorskip("tkinter.font")


@pytest.fixture(scope="module")
def tk_available():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk")
    root.destroy()
    return True


def _make_app(home, tk_available):
    from mesadock.core.models import DockFolder, DockItem
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folder = DockFolder(name="Work", style="grid", position=(40, 80))
    folder.add_item(DockItem(name="Notepad", kind="shortcut", target="C:/Windows/notepad.exe"))
    folder.add_item(DockItem(name="Site", kind="url", target="https://example.com"))
    store.profiles[0].folders = [folder]
    store.save()
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    app.root.update()
    return app, folder


def test_app_builds_docks_panels_and_manager(home, tk_available):
    app, folder = _make_app(home, tk_available)
    try:
        assert folder.id in app.docks
        dock = app.docks[folder.id]
        assert dock.rect()[2] > 0 and dock.rect()[3] > 0

        app.pin_panels(True)
        app.open_panel(folder)
        app.root.update()
        panel = app.panels.get(folder.id)
        assert panel is not None and panel.is_alive()
        assert panel.layout.count == 2
        assert panel.layout.width > 0 and panel.layout.height > 0

        app.open_manager()
        app.root.update()
        assert app.manager is not None and app.manager.is_alive()
        app.manager.close()
        assert app.manager is None

        app.close_panel(folder.id)
        app.root.update()
        assert folder.id not in app.panels
    finally:
        app.quit()
        assert app._running is False


def test_every_style_opens_a_panel(home, tk_available):
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folders = []
    for index, style in enumerate(("grid", "column", "row", "fan", "ring")):
        folder = DockFolder(name=style, style=style, position=(40, 80 + index * 120))
        folders.append(folder)
    store.profiles[0].folders = folders
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    app.pin_panels(True)
    try:
        app.root.update()
        for folder in folders:
            app.open_panel(folder)
            app.root.update()
            panel = app.panels.get(folder.id)
            assert panel is not None and panel.is_alive()
            assert panel.layout.count == 0  # an empty dock still renders
            assert panel.layout.width > 20 and panel.layout.height > 20
            app.close_panel(folder.id)
            app.root.update()
    finally:
        app.quit()


def test_adding_and_removing_a_dock_updates_the_windows(home, tk_available):
    app, _folder = _make_app(home, tk_available)
    try:
        before = len(app.docks)
        created = app.add_dock("New dock", "column")
        app.root.update()
        assert len(app.docks) == before + 1
        assert created.id in app.docks

        app.remove_dock(created.id)
        app.root.update()
        assert created.id not in app.docks
    finally:
        app.quit()


def test_saving_after_changes_is_clean(home, tk_available):
    from mesadock.core.store import Store

    app, folder = _make_app(home, tk_available)
    try:
        app.rename_dock(folder.id, "Renamed")
        app.set_dock_style(folder.id, "ring")
        app.save()
        assert app.store.dirty is False
        reloaded = Store(path=app.store.path).load()
        assert reloaded.folders[0].name == "Renamed"
        assert reloaded.folders[0].style == "ring"
    finally:
        app.quit()

def test_new_dock_does_not_land_on_an_existing_dock(home, tk_available):
    # Regression: add_dock only reserved cells taken by native desktop icons, so a
    # second dock was placed exactly on top of the first one and looked as if the
    # + New dock button had done nothing at all.
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    store.profiles[0].folders = [DockFolder(name="first", style="grid", position=(40, 40))]
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        first = app.store.folders[0]
        second = app.add_dock("second", "grid")
        app.root.update()
        assert second.position != first.position
        a = app.docks[first.id].rect()
        b = app.docks[second.id].rect()
        overlap_x = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
        overlap_y = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        assert not (overlap_x > 0 and overlap_y > 0)
    finally:
        app.quit()


def test_adding_a_path_puts_the_item_in_the_dock(home, tk_available, tmp_path):
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folder = DockFolder(name="Work", style="grid", position=(40, 80))
    store.profiles[0].folders = [folder]
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        sample = tmp_path / "Tool.lnk"
        sample.write_bytes(b"shortcut")
        assert app.add_paths_to_dock(folder.id, [str(sample)]) == 1
        app.root.update()
        reloaded = app.store.folder_by_id(folder.id)
        assert len(reloaded.items) == 1
        assert reloaded.items[0].name == "Tool"
    finally:
        app.quit()


def test_removing_an_item_drops_it_from_the_dock(home, tk_available, tmp_path):
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folder = DockFolder(name="Work", style="grid", position=(40, 80))
    store.profiles[0].folders = [folder]
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        first = tmp_path / "Alpha.lnk"
        second = tmp_path / "Beta.lnk"
        first.write_bytes(b"a")
        second.write_bytes(b"b")
        assert app.add_paths_to_dock(folder.id, [str(first), str(second)]) == 2
        app.root.update()

        item = app.store.folder_by_id(folder.id).items[0]
        app.remove_item(folder.id, item.id, restore=False)
        app.root.update()

        remaining = app.store.folder_by_id(folder.id).items
        assert [i.name for i in remaining] == ["Beta"]
    finally:
        app.quit()


def test_removing_from_the_menu_asks_first(home, tk_available, tmp_path, monkeypatch):
    """A single stray click on the context menu used to drop a shortcut with no
    confirmation, which silently emptied docks."""
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui import app as app_mod

    store = Store()
    folder = DockFolder(name="ESTUDOS", style="grid", position=(40, 80))
    store.profiles[0].folders = [folder]
    app = app_mod.MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        link = tmp_path / "Alpha.lnk"
        link.write_bytes(b"a")
        assert app.add_paths_to_dock(folder.id, [str(link)]) == 1
        app.root.update()
        item = app.store.folder_by_id(folder.id).items[0]

        asked = {"count": 0}

        class FakeMessageBox:
            @staticmethod
            def askyesno(*_args, **_kwargs):
                asked["count"] += 1
                return False

        import tkinter.messagebox as real_box

        monkeypatch.setattr(real_box, "askyesno", FakeMessageBox.askyesno)
        app.confirm_remove(app.store.folder_by_id(folder.id), item, restore=False)
        app.root.update()

        assert asked["count"] == 1
        # Answering "no" must leave the dock untouched.
        assert len(app.store.folder_by_id(folder.id).items) == 1
    finally:
        app.quit()


def test_every_dock_draws_its_name(home, tk_available):
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    store.profiles[0].folders = [
        DockFolder(name="ESTUDOS", style="grid", position=(40, 80)),
        DockFolder(name="", style="row", position=(40, 260)),
    ]
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        named = app.store.folders[0]
        dock = app.docks[named.id]
        assert dock._label_text() == "ESTUDOS"
        # A named dock needs a strip under the icon, so it is taller than wide.
        assert dock.rect()[3] > dock.rect()[2]
        # An empty name falls back to a default, but it is still drawn.
        unnamed = app.docks[app.store.folders[1].id]
        assert unnamed._label_text() == "New dock"
        assert unnamed._label_text() == "New dock"
    finally:
        app.quit()


def test_a_long_dock_name_is_shown_in_full_instead_of_cut(home, tk_available):
    """Dock captions were measured with font(8) and painted in font(9, bold).

    The measurement therefore under-estimated the painted width by ~17%, so
    "IA ASSISTENTES" measured 77px, was drawn 90px wide in a 78px strip, and Tk
    wrapped it to "IA ASSIST...". On top of that tk.font was never imported, so
    every measurement silently fell back to a character count.
    """
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    store.profiles[0].folders = [
        DockFolder(name="IA ASSISTENTES", style="grid", position=(40, 80)),
    ]
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        dock = app.docks[app.store.folders[0].id]
        # Measuring with the drawing font is the whole point: a name is only
        # "too long" relative to the font it is actually rendered in.
        font = dock._label_font()
        painted = tkfont.Font(font=font, root=app.root).measure("IA ASSISTENTES")
        # The window must have grown to fit the caption, and the caption must be
        # the whole name rather than a wrapped fragment.
        assert dock._dock_width() - 4 >= painted
        assert dock._label_text() == "IA ASSISTENTES"
    finally:
        app.quit()

def test_right_click_on_an_item_offers_the_item_menu(home, tk_available, tmp_path):
    """Right-click used to jump to the Manager, which hid the Remove commands."""
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folder = DockFolder(name="ESTUDOS", style="grid", position=(40, 80))
    store.profiles[0].folders = [folder]
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        samples = []
        for name in ("Alpha", "Beta", "Gamma"):
            path = tmp_path / (name + ".lnk")
            path.write_bytes(b"x")
            samples.append(str(path))
        assert app.add_paths_to_dock(folder.id, samples) == 3
        app.root.update()

        app.open_panel(app.store.folder_by_id(folder.id), force=True)
        app.root.update()
        panel = app.panels[folder.id]
        assert panel.on_menu is not None, "the panel must offer an item menu"

        seen = []
        panel.on_menu = lambda f, item, x, y: seen.append(item.name)
        current = app.store.folder_by_id(folder.id)
        panel.on_menu(current, current.items[1], 10, 10)
        assert seen == ["Beta"]
    finally:
        app.quit()


def test_removing_one_of_five_items_leaves_four(home, tk_available, tmp_path):
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folder = DockFolder(name="ESTUDOS", style="grid", position=(40, 80))
    store.profiles[0].folders = [folder]
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        paths = []
        for name in ("A", "B", "C", "D", "E"):
            path = tmp_path / (name + ".lnk")
            path.write_bytes(b"x")
            paths.append(str(path))
        assert app.add_paths_to_dock(folder.id, paths) == 5
        app.root.update()

        target = app.store.folder_by_id(folder.id).items[2]
        app.remove_item(folder.id, target.id, restore=False)
        app.root.update()

        assert [i.name for i in app.store.folder_by_id(folder.id).items] == [
            "A", "B", "D", "E"]
    finally:
        app.quit()


def test_panels_close_when_the_pointer_leaves_in_click_mode(home, tk_available):
    """Click mode used to leave an open panel on screen with no way to dismiss it."""
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folder = DockFolder(name="ESTUDOS", style="grid", position=(40, 80))
    store.profiles[0].folders = [folder]
    store.settings.open_trigger = "click"
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        app.open_panel(app.store.folder_by_id(folder.id), force=True)
        app.root.update()
        assert app.panels
        # Pointer parked far away from both the panel and its dock.
        app._last_pointer = (-500, -500)
        app._close_now()
        app.root.update()
        assert not app.panels
    finally:
        app.quit()


def test_hover_opens_panels_when_that_trigger_is_selected(home, tk_available):
    from mesadock.core.models import DockFolder
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    folder = DockFolder(name="ESTUDOS", style="grid", position=(40, 80))
    store.profiles[0].folders = [folder]
    store.settings.open_trigger = "hover"
    store.settings.hover_delay_ms = 0
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        assert app._opens_on_hover() is True
        app.pointer_entered_dock(app.docks[folder.id])
        app.root.update()
        app._open_now(app.store.folder_by_id(folder.id))
        app.root.update()
        assert folder.id in app.panels
    finally:
        app.quit()


def test_hover_does_not_open_panels_in_click_mode(home, tk_available):
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    store.settings.open_trigger = "click"
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        assert app._opens_on_hover() is False
    finally:
        app.quit()
