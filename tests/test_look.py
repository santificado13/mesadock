"""Per-pixel-alpha rendering: paint helpers, docks, panels and the dock look."""
from __future__ import annotations

import time

import pytest
from PIL import Image

from mesadock.core import icons
from mesadock.core.models import DockFolder, DockItem
from mesadock.ui import paint
from mesadock.win32 import layered

tk = pytest.importorskip("tkinter")


# --- paint ----------------------------------------------------------------
def test_premultiplied_bgra_swaps_channels_and_scales_by_alpha():
    image = Image.new("RGBA", (2, 1))
    image.putpixel((0, 0), (200, 100, 50, 255))
    image.putpixel((1, 0), (200, 100, 50, 128))
    data = layered.premultiplied_bgra(image)
    assert tuple(data[0:4]) == (50, 100, 200, 255)
    blue, green, red, alpha = data[4:8]
    assert alpha == 128 and abs(red - 100) <= 1 and abs(green - 50) <= 1 and abs(blue - 25) <= 1


def test_rounded_shapes_are_anti_aliased_and_keep_clear_corners():
    layer = paint.rounded((40, 40), (0, 0, 40, 40), 12, fill=(10, 20, 30, 255))
    assert layer.getpixel((0, 0))[3] == 0            # outside the corner
    assert layer.getpixel((20, 20)) == (10, 20, 30, 255)
    edge_alphas = {layer.getpixel((x, 1))[3] for x in range(0, 14)}
    assert any(0 < alpha < 255 for alpha in edge_alphas), "the edge must have partial alpha"


def test_shadow_is_soft_and_only_black():
    layer = paint.shadow((60, 60), (15, 15, 45, 45), 8, blur=6, offset=(0, 4), opacity=120)
    assert layer.getpixel((30, 34))[3] > 60
    assert 0 < layer.getpixel((30, 54))[3] < 60      # fades out below the shape
    assert layer.getpixel((30, 34))[:3] == (0, 0, 0)


def test_fit_text_adds_an_ellipsis_only_when_needed():
    face = paint.font(12)
    assert paint.fit_text("Chrome", face, 400) == "Chrome"
    short = paint.fit_text("Um nome de atalho realmente muito comprido", face, 90)
    assert short.endswith("\u2026") and paint.text_width(short, face) <= 90
    assert paint.fit_text("", face, 50) == ""


def test_tint_recolours_but_keeps_transparency():
    icon = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for x in range(2, 6):
        for y in range(2, 6):
            icon.putpixel((x, y), (200, 40, 40, 255))
    tinted = paint.tint(icon, icons.ACCENTS["teal"], strength=1.0)
    assert tinted.getpixel((0, 0))[3] == 0 and tinted.getpixel((3, 3))[3] == 255
    red, green, blue, _alpha = tinted.getpixel((3, 3))
    assert green > red and blue > red, "a red icon tinted teal must turn greenish-blue"


# --- model and icon source ------------------------------------------------
def test_accent_follows_the_style_until_the_user_picks_one():
    assert icons.accent_name(DockFolder(name="A", style="ring")) == "rose"
    assert icons.accent_name(DockFolder(name="A", style="ring", accent="teal")) == "teal"
    assert icons.accent_name(DockFolder(name="A", style="ring", accent="not-a-colour")) == "rose"
    assert icons.accent_name(DockFolder(name="A", portal="C:/x")) == "lime"


def test_look_fields_round_trip_and_reach_the_glyph_source():
    from mesadock.ui.images import folder_source

    dock = DockFolder(name="A", style="grid", accent="amber", tint=True)
    again = DockFolder.from_dict(dock.to_dict())
    assert again.accent == "amber" and again.tint is True
    assert folder_source(dock) == "glyph:grid:amber"
    assert folder_source(DockFolder(name="B", style="fan")) == "glyph:fan"
    amber = icons.dock_icon("grid", 64, accent="amber")
    blue = icons.dock_icon("grid", 64)
    assert amber.tobytes() != blue.tobytes()


# --- windows ---------------------------------------------------------------
@pytest.fixture(scope="module")
def tk_available():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk")
    root.destroy()
    return True


def _app(home, style="grid", items=3, animations=False):
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    store.settings.animations = animations
    store.settings.show_labels = True
    folder = DockFolder(name="Work", style=style, position=(60, 90))
    for index in range(items):
        folder.add_item(DockItem(name="Item %d" % index, kind="shortcut", target="C:/Windows/notepad.exe"))
    store.profiles[0].folders = [folder]
    store.save()
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    app.root.update()
    return app, folder


def _pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        time.sleep(0.01)


def test_dock_is_composed_with_real_alpha(home, tk_available):
    app, folder = _app(home)
    try:
        dock = app.docks[folder.id]
        image = dock._image
        assert image is not None and image.mode == "RGBA"
        assert image.size == (dock._dock_width(), dock._pixel_size() + dock._label_height())
        assert image.getpixel((image.width // 2, 1))[3] >= 1, "the tile column stays clickable"
        centre = image.getpixel((image.width // 2, dock._pixel_size() // 2))
        assert centre[3] > 200, "the tile is nearly opaque glass"
        assert layered.available() is False or dock._layered is True
    finally:
        app.quit()


def test_dock_look_changes_colour_size_and_tint(home, tk_available):
    app, folder = _app(home)
    try:
        dock = app.docks[folder.id]
        before = dock._image.tobytes()
        small = dock._pixel_size()

        app.set_dock_look(folder.id, accent="rose")
        assert folder.accent == "rose" and dock._image.tobytes() != before

        app.set_dock_look(folder.id, size=app.DOCK_SIZES["large"])
        assert folder.icon_size == 88 and dock._pixel_size() > small

        app.set_dock_look(folder.id, tint=True, accent="nonsense")
        assert folder.tint is True and folder.accent == ""
    finally:
        app.quit()


@pytest.mark.parametrize("style", ["grid", "column", "ring", "fan"])
def test_panel_has_a_shadow_margin_and_reacts_to_hover(home, tk_available, style):
    from mesadock.ui import panel as panel_mod

    app, folder = _app(home, style=style, items=4)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        app.root.update()
        panel = app.panels[folder.id]
        pad = panel_mod.SHADOW_PAD
        image = panel._image
        assert image.size == (panel.layout.width + pad * 2, panel.layout.height + pad * 2)
        assert image.getpixel((0, 0))[3] == 0, "the far corner of the shadow margin is clear"
        middle = image.getpixel((image.width // 2, image.height // 2))
        assert middle[3] >= 200  # default opacity 0.92, the same for every style

        # The shadow margin is not part of the panel for pointer tracking.
        left, top = panel.layout_origin
        assert panel.contains_point(left + 5, top + panel.layout.height // 2)
        assert not panel.contains_point(left - pad + 2, top - pad + 2)

        # Hovering an item repaints it; leaving restores the first picture.
        x, y, w, h = panel._hovered_items[1]
        assert panel._index_at(int(x + w / 2), int(y + h / 2)) == 1
        idle = image.tobytes()
        panel._set_hover(1)
        assert panel._image.tobytes() != idle
        panel._set_hover(-1)
        assert panel._image.tobytes() == idle
    finally:
        app.quit()


def test_tinted_dock_recolours_the_panel_icons(home, tk_available):
    app, folder = _app(home, items=2)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        app.root.update()
        plain = app.panels[folder.id]._image.tobytes()
        app.set_dock_look(folder.id, tint=True)
        assert app.panels[folder.id]._image.tobytes() != plain
    finally:
        app.quit()


def test_panel_fades_in_to_full_opacity_and_out_to_nothing(home, tk_available):
    app, folder = _app(home, animations=True)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        panel = app.panels[folder.id]
        assert panel._opacity < 1.0, "it starts transparent"
        _pump(app, 0.4)
        assert panel._opacity == 1.0 and panel._slide == 0
        panel.hide()
        _pump(app, 0.3)
        assert not panel.is_alive()
    finally:
        app.quit()


def test_a_closing_panel_ignores_rebuild_and_still_closes(home, tk_available):
    """rebuild() during the fade-out cancelled it and left a panel that was fully
    visible and could never be closed again."""
    app, folder = _app(home, animations=True)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        _pump(app, 0.3)
        panel = app.panels[folder.id]
        panel.hide()
        panel.rebuild()
        _pump(app, 0.3)
        assert not panel.is_alive()
    finally:
        app.quit()


def test_a_fading_panel_does_not_unregister_its_successor(home, tk_available):
    app, folder = _app(home, animations=True)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        _pump(app, 0.3)
        old = app.panels[folder.id]
        app.close_panel(folder.id)          # starts the fade-out
        app.open_panel(folder, force=True)  # reopened before it ends
        new = app.panels[folder.id]
        assert new is not old
        _pump(app, 0.3)
        assert not old.is_alive()
        assert app.panels.get(folder.id) is new and new.is_alive()
    finally:
        app.quit()


def test_the_panel_shadow_never_covers_its_dock(home, tk_available):
    app, folder = _app(home, style="grid", items=4)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        app.root.update()
        panel = app.panels[folder.id]
        left, top, width, height = app.docks[folder.id].rect()
        origin_x, origin_y = panel._window_origin()
        image = panel._image
        for x in range(left, left + width, 4):
            for y in range(top, top + height, 2):
                px, py = x - origin_x, y - origin_y
                if 0 <= px < image.width and 0 <= py < image.height:
                    assert image.getpixel((px, py))[3] == 0, (px, py)
    finally:
        app.quit()


def test_a_wide_dock_only_takes_clicks_where_something_is_drawn(home, tk_available):
    from mesadock.core.store import Store
    from mesadock.ui.app import MesaDockApp

    store = Store()
    store.profiles[0].folders = [DockFolder(name="UM NOME BEM COMPRIDO DE DOCK", position=(60, 90))]
    store.save()
    app = MesaDockApp(store=store)
    app.start(minimized=True)
    try:
        app.root.update()
        dock = app.docks[store.folders[0].id]
        image, size = dock._image, dock._pixel_size()
        assert image.width > size * 1.5, "the long name makes the window wider than the tile"
        assert image.getpixel((2, size // 2))[3] == 0, "empty side: clicks go to the desktop"
        assert image.getpixel((image.width // 2, 2))[3] >= 1, "tile column stays clickable"
        assert image.getpixel((image.width // 2, size + dock._label_height() // 2))[3] > 200, "name pill"
    finally:
        app.quit()


def test_fonts_follow_the_monitor_scale(home, tk_available):
    app, folder = _app(home)
    try:
        dock = app.docks[folder.id]
        scale = getattr(app.monitor_for(dock.position()), "scale", 1.0) or 1.0
        assert dock._dpi() == 96.0 * scale
        assert paint.points_to_pixels(9, 96) == 12 and paint.points_to_pixels(9, 192) == 24
    finally:
        app.quit()


def test_paste_centre_ignores_pictures_outside_the_target():
    target = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    picture = Image.new("RGBA", (6, 6), (255, 0, 0, 255))
    paint.paste_centre(target, picture, (-40, -40))
    paint.paste_centre(target, picture, (400, 10))
    assert target.getbbox() is None
    paint.paste_centre(target, picture, (0, 0))      # partly inside: clipped, not an error
    assert target.getpixel((1, 1))[3] == 255


def _background_alpha_at_rim(panel):
    """Alpha of the card where nothing else is drawn: just inside the edge."""
    from mesadock.ui import panel as panel_mod

    pad = panel_mod.SHADOW_PAD
    image = panel._image
    if panel.layout.style in ("ring", "fan"):
        radius = min(panel.layout.width, panel.layout.height) / 2 - 2
        cx, cy = pad + panel.layout.width / 2, pad + panel.layout.height / 2
        # on the diagonal, clear of the items and of the rim lines
        point = (int(cx - radius * 0.64), int(cy - radius * 0.64))
    else:
        point = (pad + 7, pad + panel.layout.height // 2)  # inside the left padding
    return image.getpixel(point)[3]


def test_every_style_uses_the_same_panel_opacity(home, tk_available):
    """Ring and fan used to ignore the setting and stay nearly opaque."""
    alphas = {}
    for style in ("grid", "ring", "fan", "column"):
        app, folder = _app(home, style=style, items=4)
        try:
            app.store.settings.panel_opacity = 0.5
            app.pin_panels(True)
            app.open_panel(folder, force=True)
            app.root.update()
            alphas[style] = _background_alpha_at_rim(app.panels[folder.id])
        finally:
            app.quit()
    assert all(abs(alpha - 127) <= 4 for alpha in alphas.values()), alphas


def test_the_dock_steps_aside_only_under_a_ring_or_fan_panel(home, tk_available):
    for style, expected in (("ring", True), ("fan", True), ("grid", False)):
        app, folder = _app(home, style=style, items=4)
        try:
            dock = app.docks[folder.id]
            assert dock._under_own_panel() is False
            app.pin_panels(True)
            app.open_panel(folder, force=True)
            app.root.update()
            panel = app.panels[folder.id]
            if expected:
                # Centre the disc on the dock, as it is when there is room on screen.
                left, top, width, height = dock.rect()
                panel._anchor = (left, top, width, height)
                panel.layout_origin = (int(left + width / 2 - panel.layout.width / 2),
                                       int(top + height / 2 - panel.layout.height / 2))
            assert dock._under_own_panel() is expected, style
            if expected:
                # Pushed aside by a screen edge, the dock is next to the disc: it stays.
                panel.layout_origin = (panel.layout_origin[0] + panel.layout.width, panel.layout_origin[1])
                assert dock._under_own_panel() is False
                panel.layout_origin = (panel.layout_origin[0] - panel.layout.width, panel.layout_origin[1])
            app.close_panel(folder.id)
            app.root.update()
            assert dock._under_own_panel() is False, "the dock is back once the panel closes"
        finally:
            app.quit()


def test_text_halo_outlines_the_letters_without_touching_the_rest():
    face = paint.font(14)
    plain = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    haloed = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    paint.draw_text(plain, (60, 20), "Nome", face, (255, 255, 255, 255))
    paint.draw_text(haloed, (60, 20), "Nome", face, (255, 255, 255, 255), halo=(10, 20, 30, 205))
    covered = lambda image: sum(1 for value in image.getchannel("A").tobytes() if value)  # noqa: E731
    assert covered(haloed) > covered(plain) * 1.5, "the outline adds pixels around the letters"
    assert haloed.getpixel((2, 2))[3] == 0, "far from the text nothing is painted"
    paint.draw_text(haloed, (-500, -500), "fora", face, (255, 255, 255, 255), halo=(0, 0, 0, 255))  # no error


def test_translucent_panels_outline_their_names_and_opaque_ones_do_not(home, tk_available):
    app, folder = _app(home, items=2)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        app.root.update()
        panel = app.panels[folder.id]
        app.store.settings.panel_opacity = 1.0
        panel.rebuild()
        opaque = panel._image.tobytes()
        app.store.settings.panel_opacity = 0.4
        panel.rebuild()
        assert panel._background_alpha() < 215 and panel._image.tobytes() != opaque
    finally:
        app.quit()


def test_hover_repaints_only_from_the_cached_resting_picture(home, tk_available):
    app, folder = _app(home, style="ring", items=6)
    try:
        app.pin_panels(True)
        app.open_panel(folder, force=True)
        app.root.update()
        panel = app.panels[folder.id]
        resting = panel._image.tobytes()
        for index in (0, 3, 5, 2):
            panel._set_hover(index)
        first = panel._image.tobytes()
        panel._set_hover(-1)
        assert panel._image.tobytes() == resting, "no leftovers from earlier hovers"
        panel._set_hover(2)
        assert panel._image.tobytes() == first, "the same hover always paints the same picture"
    finally:
        app.quit()


def test_dock_tiles_follow_the_opacity_setting(home, tk_available):
    """Settings > Opacity makes the tile glass more or less solid; the glyph,
    the border and the count badge stay fully visible."""
    app, folder = _app(home)
    try:
        dock = app.docks[folder.id]
        size = dock._pixel_size()
        # a spot of bare glass: inside the tile, away from the glyph in the middle
        glass = (dock._dock_width() // 2 - (size - 16) // 2 + 6, size // 2)
        seen = {}
        for opacity in (1.0, 0.35):
            app.store.settings.panel_opacity = opacity
            app.apply_settings()
            assert dock._tile_source().endswith(":" + str(int(opacity * 100)))
            seen[opacity] = dock._image.getpixel(glass)[3]
        assert seen[1.0] >= 235
        assert 70 <= seen[0.35] <= 110, seen
        middle = dock._image.crop((dock._dock_width() // 2 - size // 5, size // 2 - size // 5,
                                   dock._dock_width() // 2 + size // 5, size // 2 + size // 5))
        assert middle.getchannel("A").getextrema()[1] > 200, "the glyph stays visible on a see-through tile"

        app.store.settings.panel_background = "solid"
        app.apply_settings()
        assert dock._image.getpixel(glass)[3] >= 235, "solid background ignores the slider"
    finally:
        app.quit()


def test_a_custom_dock_picture_is_not_faded(home, tk_available, tmp_path):
    app, folder = _app(home)
    try:
        picture = tmp_path / "mine.png"
        Image.new("RGBA", (64, 64), (200, 30, 30, 255)).save(picture)
        app.set_dock_icon(folder.id, str(picture))
        app.store.settings.panel_opacity = 0.35
        app.apply_settings()
        dock = app.docks[folder.id]
        assert dock._tile_source() == str(picture)
        assert dock._image.getpixel((dock._dock_width() // 2, dock._pixel_size() // 2))[3] == 255
    finally:
        app.quit()


def test_glyph_source_accepts_an_empty_accent_and_an_opacity():
    solid = icons.dock_icon("grid", 64, opacity=1.0)
    faint = icons.dock_icon("grid", 64, opacity=0.35)
    spot = (10, 32)  # bare glass, left of the glyph
    assert solid.getpixel(spot)[3] > 230 and 70 <= faint.getpixel(spot)[3] <= 110
    assert faint.getpixel((32, 1))[3] > 150, "the border does not fade with the glass"


def test_docks_move_almost_freely_and_tiles_line_up(home, tk_available, monkeypatch):
    """Snapping to the 76x96 desktop icon cell overlapped large docks or pushed
    them a whole cell apart. Docks must be placeable side by side, with tiles
    aligned even when their names have different widths."""
    from mesadock.core.store import Store
    from mesadock.ui import dockwindow
    from mesadock.ui.app import MesaDockApp
    from mesadock.win32.monitors import Monitor

    store = Store()
    store.profiles[0].folders = [
        DockFolder(name="IA", icon_size=88, position=(100, 100)),
        DockFolder(name="SISTEMA_ENERGIA_SOLAR", icon_size=88, position=(400, 100)),
    ]
    store.save()
    app = MesaDockApp(store=store)
    app.background_watch = False
    app.start(minimized=True)
    try:
        # a monitor above and to the left of the primary, as on a two-screen desk
        screen = Monitor(1, (-1920, -1440, 2560, 1440), (-1920, -1440, 2560, 1400), 1.0, False)
        monkeypatch.setattr(app, "monitor_for", lambda _point: screen)
        short, long = (app.docks[f.id] for f in store.folders)

        def tile_centre(dock):
            x, y = dock.folder.position
            return x + dock._dock_width() // 2, y + dock._pixel_size() // 2

        for dock in (short, long):                     # never moved further than half a step
            for wanted in ((-900, -1200), (-853, -1111), (-701, -907)):
                dock.move_to(*wanted)
                got = dock.folder.position
                assert all(abs(g - w) <= dockwindow.SNAP_STEP // 2 + 1 for g, w in zip(got, wanted)), (wanted, got)

        # dropped a few pixels off the same column: the tiles end up in line
        short.move_to(-600 - short._dock_width() // 2 + 4, -1200)
        long.move_to(-600 - long._dock_width() // 2 - 3, -1000)
        assert tile_centre(short)[0] == tile_centre(long)[0]

        # two large docks fit side by side: no overlap, no empty cell between
        short.move_to(-900, -1200)
        other = short.folder.position[0] + short._dock_width() + 8
        long.move_to(other, -1200)
        gap = long.folder.position[0] - (short.folder.position[0] + short._dock_width())
        assert 0 <= gap <= 20

        app.store.settings.snap_to_grid = False        # unticked: exactly where it was dropped
        short.move_to(-853, -1111)
        assert short.folder.position == (-853, -1111)
    finally:
        app.quit()
