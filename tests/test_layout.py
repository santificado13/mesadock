"""Panel geometry: cells, placement, snapping and collision avoidance."""
from __future__ import annotations

import pytest

from mesadock.core import layout

MONITOR = (0, 0, 1920, 1080)


@pytest.mark.parametrize("style", ["grid", "column", "row", "fan", "ring"])
@pytest.mark.parametrize("count", [0, 1, 2, 5, 9, 16])
def test_every_style_produces_one_cell_per_item(style, count):
    built = layout.build_layout(style, count, icon=64)
    assert built.cell_count() == count
    assert built.width > 0 and built.height > 0


def test_grid_prefers_a_square_and_caps_rows():
    built = layout.build_layout("grid", 9, icon=64)
    assert built.cell_count() == 9
    assert built.height < built.width * 1.6


def test_row_is_wider_than_it_is_tall():
    built = layout.build_layout("row", 5, icon=64)
    assert built.width > built.height


def test_column_is_taller_than_it_is_wide():
    built = layout.build_layout("column", 5, icon=64)
    assert built.height > built.width


def test_ring_cells_stay_inside_the_panel():
    built = layout.build_layout("ring", 8, icon=48)
    for x, y in built.cells:
        assert 0 <= x <= built.width
        assert 0 <= y <= built.height


def test_labels_grow_the_cells():
    plain = layout.build_layout("grid", 4, icon=64, labels=False)
    labelled = layout.build_layout("grid", 4, icon=64, labels=True)
    assert labelled.height > plain.height


def test_max_width_reduces_grid_columns():
    narrow = layout.build_layout("grid", 16, icon=64, max_width=420)
    wide = layout.build_layout("grid", 16, icon=64, max_width=0)
    assert narrow.width <= 420 + 2 * layout.DEFAULT_PADDING
    assert narrow.width <= wide.width


def test_panel_opens_above_the_icon_and_flips_below_near_the_top():
    built = layout.build_layout("grid", 9, icon=64)
    low_icon = (900, 900, 64, 64)
    x, y = layout.place_panel(low_icon, built, MONITOR)
    assert y + built.height <= low_icon[1] + 4

    high_icon = (900, 4, 64, 64)
    x2, y2 = layout.place_panel(high_icon, built, MONITOR)
    assert y2 >= high_icon[1] + high_icon[3]


def test_panel_never_leaves_the_monitor():
    built = layout.build_layout("ring", 10, icon=64)
    for icon in [(0, 0, 64, 64), (1900, 1050, 64, 64), (1880, 10, 64, 64)]:
        x, y = layout.place_panel(icon, built, MONITOR)
        assert x >= 0 and y >= 0
        assert x + built.width <= MONITOR[2]
        assert y + built.height <= MONITOR[3]


def test_clamp_centres_oversized_rectangles():
    x, y = layout.clamp_to_monitor((500, 500, 4000, 3000), MONITOR)
    assert x == 0 and y == 0


def test_contains_and_monitor_for_point():
    assert layout.contains((10, 10, 100, 100), 10, 10)
    assert not layout.contains((10, 10, 100, 100), 110, 10)
    second = (1920, 0, 1280, 1024)
    assert layout.monitor_for_point([MONITOR, second], 2000, 10) == second
    assert layout.monitor_for_point([MONITOR, second], -50, -50) == MONITOR


def test_snap_to_grid_lands_on_cell_centres():
    cell = (115, 117)
    x, y = layout.snap_to_grid(130, 120, MONITOR, cell)
    assert x % cell[0] == 0 and y % cell[1] == 0
    x2, y2 = layout.snap_to_grid(240, 250, MONITOR, cell)
    assert (x2, y2) == (2 * cell[0], 2 * cell[1])


def test_snap_respects_the_monitor_origin():
    monitor = (1920, 0, 1280, 1024)
    x, y = layout.snap_to_grid(1920 + 130, 120, monitor, (100, 100))
    assert x >= 1920


def test_first_free_cell_skips_occupied_spots():
    occupied = layout.Occupancy([(0, 0, 115, 117)])
    x, y = layout.first_free_cell(MONITOR, (115, 117), occupied, preferred=(0, 0))
    assert (x, y) != (0, 0)


def test_occupancy_detects_overlap():
    occupied = layout.Occupancy([(0, 0, 100, 100)])
    assert occupied.collides((50, 50, 100, 100))
    assert not occupied.collides((100, 0, 100, 100))


def test_offset_point():
    assert layout.offset_point(10, 20, -3, 4) == (7, 24)


def test_ring_cells_do_not_overlap_once_labels_are_on():
    """Regression: the ring was sized from the icon only, so with labels on the
    name of one item was drawn underneath the icon of the next."""
    import math

    for count in (3, 5, 8, 11, 16):
        built = layout.build_layout(
            "ring", count, icon=84, gap=15, padding=14, labels=True
        )
        cell_h = 84 + layout.LABEL_HEIGHT
        centres = [(x + 84 / 2, y + cell_h / 2) for x, y in built.cells]
        need = math.hypot(84, cell_h)
        for index in range(count):
            a = centres[index]
            b = centres[(index + 1) % count]
            spacing = math.hypot(a[0] - b[0], a[1] - b[1])
            assert spacing >= need, (count, index, spacing, need)


def test_ring_panel_is_wide_and_tall_enough_for_its_labels():
    built = layout.build_layout("ring", 6, icon=64, labels=True)
    cell_h = 64 + layout.LABEL_HEIGHT
    lowest = max(y + cell_h for _x, y in built.cells)
    rightmost = max(x + 64 for x, _y in built.cells)
    assert built.height >= lowest
    assert built.width >= rightmost


def test_ring_is_nearly_square_so_it_reads_as_a_circle():
    """A ring panel has to look circular, not like a wide card.

    The cell is now wider than it is tall (the label needs horizontal room), so
    the old assertion that height exceeded width no longer describes the shape.
    """
    built = layout.build_layout("ring", 7, icon=64, labels=True)
    ratio = built.width / built.height
    assert 0.75 < ratio < 1.35, ratio


def _fan_overlaps(count: int, icon: int, labels: bool, gap: int = 12) -> int:
    built = layout.build_layout("fan", count, icon=icon, gap=gap, labels=labels)
    cell_w, cell_h = layout.icon_cell(icon, layout.LABEL_HEIGHT, labels)
    conflicts = 0
    for i in range(count):
        for j in range(i + 1, count):
            ax, ay = built.cells[i]
            bx, by = built.cells[j]
            if abs(ax - bx) < cell_w + gap and abs(ay - by) < cell_h + gap:
                conflicts += 1
    return conflicts


def test_fan_cells_do_not_overlap_once_labels_are_on():
    """The fan used to size its radius from the icon alone, so from five items
    up every neighbour sat on top of the next one's label."""
    for count in (2, 3, 5, 8, 11, 16):
        assert _fan_overlaps(count, 64, labels=True) == 0, count


def test_fan_panel_is_big_enough_for_its_labels():
    """A fan that fits its cells but is smaller than the cells themselves would
    still clip the labels, so the panel must contain the whole layout."""
    built = layout.build_layout("fan", 11, icon=64, gap=12, labels=True)
    cell_w, cell_h = layout.icon_cell(64, layout.LABEL_HEIGHT, True)
    for cell_x, cell_y in built.cells:
        assert cell_x >= 0 and cell_y >= 0
        assert cell_x + cell_w <= built.width
        assert cell_y + cell_h <= built.height


def test_fan_and_ring_have_comparable_footprints():
    """A fan must not explode off screen: it is a compact radial style."""
    fan = layout.build_layout("fan", 11, icon=84, gap=15, labels=True)
    ring = layout.build_layout("ring", 11, icon=84, gap=15, labels=True)
    assert fan.width < 1400 and fan.height < 1400
    assert 0.7 < (fan.width / fan.height) < 1.6
    assert abs(fan.width - ring.width) < 400


def test_column_wraps_instead_of_running_off_the_screen():
    """A ten-item column is taller than the screen at this icon size.

    Regression: max_height was ignored, so the panel was 1093px tall on a
    1019px screen and the top icons were unreachable."""
    built = layout.build_layout(
        "column", 10, icon=75, gap=15, labels=True,
        max_width=1647, max_height=959,
    )
    assert built.height <= 959
    widths = {cell_x for cell_x, _ in built.cells}
    assert len(widths) > 1, "the column should have wrapped"


def test_every_style_fits_a_laptop_screen_with_ten_labelled_items():
    max_width, max_height = 1647, 959
    for style in ("grid", "column", "row", "fan", "ring"):
        built = layout.build_layout(
            style, 10, icon=75, gap=15, labels=True,
            max_width=max_width, max_height=max_height,
        )
        assert built.width <= 1707, style
        assert built.height <= 1019, style


def test_labelled_cell_is_wider_than_the_icon_so_names_are_not_clipped():
    """A name is a line of text; it needs horizontal room, not just a strip.

    The cell used to be exactly as wide as the icon, so long names were cut to
    "Web Bankin..." while the cell next to them was empty.
    """
    icon_w, icon_h = layout.icon_cell(72, layout.LABEL_HEIGHT, labels=False)
    cell_w, cell_h = layout.icon_cell(72, layout.LABEL_HEIGHT, labels=True)
    assert cell_w > icon_w
    assert cell_h > icon_h
    # Wide enough for the longest realistic shortcut name at this size.
    assert cell_w >= 110


def test_layout_exposes_the_cell_box_the_panel_draws_into():
    built = layout.build_layout("ring", 10, icon=72, gap=15, labels=True)
    cell_w, cell_h = built.cell_size()
    assert cell_w > 0 and cell_h > 0
    for cell_x, cell_y in built.cells:
        assert cell_x + cell_w <= built.width + 2
        assert cell_y + cell_h <= built.height + 2


def test_ring_panel_is_square_so_the_disc_is_a_circle():
    """A ring drawn in a wide rectangle reads as an oval, not an orbit.

    The panel used to take the cell width horizontally and the cell height
    vertically, which made it wider than it was tall even though the items are
    laid out on a circle.
    """
    for count in (2, 3, 5, 8, 10, 14, 20):
        built = layout.build_layout("ring", count, icon=72, gap=15, labels=True)
        assert built.width == built.height, (count, built.width, built.height)


def test_ring_disc_encloses_every_cell():
    """The painted disc must cover the cells, or icons sit on the rim.

    The disc is inscribed in the shorter side of the panel. When the panel was
    wider than tall, the outer cells and their labels poked out of the circle and
    were drawn over the transparent edge.
    """
    import math

    for count in (2, 3, 5, 8, 10, 14, 20):
        for icon in (56, 72, 84):
            built = layout.build_layout("ring", count, icon=icon, gap=15, labels=True)
            cell_w, cell_h = built.cell_size()
            disc_radius = min(built.width, built.height) / 2 - 2
            centre_x, centre_y = built.width / 2, built.height / 2
            for cell_x, cell_y in built.cells:
                for corner_x, corner_y in (
                    (cell_x, cell_y),
                    (cell_x + cell_w, cell_y),
                    (cell_x, cell_y + cell_h),
                    (cell_x + cell_w, cell_y + cell_h),
                ):
                    distance = math.hypot(corner_x - centre_x, corner_y - centre_y)
                    assert distance <= disc_radius, (count, icon, distance, disc_radius)


def test_fan_disc_encloses_every_cell_and_is_concentric_with_the_arc():
    """Fan items used to hang outside their own disc, and off its centre.

    The arc spans 240 degrees, so its bounding box leans to one side. Sizing the
    panel (and the disc drawn in it) from that box put the disc centre ~11px off
    the dock icon and left ten cell corners up to 31px beyond the rim.
    """
    import math

    for count in (2, 3, 5, 8, 10, 14, 20):
        for icon in (56, 72, 84):
            built = layout.build_layout("fan", count, icon=icon, gap=15, labels=True)
            cell_w, cell_h = built.cell_size()
            assert built.width == built.height, (count, icon)
            disc_radius = min(built.width, built.height) / 2 - 2
            centre_x, centre_y = built.width / 2, built.height / 2
            for cell_x, cell_y in built.cells:
                for corner_x, corner_y in (
                    (cell_x, cell_y),
                    (cell_x + cell_w, cell_y),
                    (cell_x, cell_y + cell_h),
                    (cell_x + cell_w, cell_y + cell_h),
                ):
                    distance = math.hypot(corner_x - centre_x, corner_y - centre_y)
                    assert distance <= disc_radius, (count, icon, distance, disc_radius)


def test_fan_anchor_sits_on_the_disc_centre():
    """Fan panels open anchored on the dock icon, so the arc must pivot there.

    Anchoring the panel on the bounding-box centre instead made the arc pivot
    around a point that was not the icon the panel hangs from.
    """
    for count in (3, 5, 10, 14):
        built = layout.build_layout("fan", count, icon=72, gap=15, labels=True)
        assert abs(built.anchor_x - built.width / 2) <= 1, count
        assert abs(built.anchor_y - built.height / 2) <= 1, count
