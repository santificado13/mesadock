"""Pure geometry for MesaDock.

No Tk, no Win32: every function takes numbers and returns numbers, which keeps
panel placement testable without a display.

Coordinate space is screen pixels, origin at the top-left of the primary monitor
(y grows downwards), matching Tk and Win32.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

Rect = tuple[int, int, int, int]  # (left, top, width, height)

DEFAULT_PADDING = 14
DEFAULT_GAP = 12
LABEL_HEIGHT = 18
# How much wider than the icon a labelled cell gets, as a fraction of the icon.
# The name is drawn on a single line, so a cell only as wide as the icon clipped it.
LABEL_SPREAD = 0.62
MAX_GRID_COLUMNS = 5
MAX_GRID_ROWS = 5
# The fan has to sweep wide enough that neighbouring cells clear each other once
# labels are on: at 140 degrees the arc cannot hold 11 labelled items, and the
# radius needed grew to 619px instead of 394px at this span.
FAN_SPAN = math.radians(240)
FAN_START = math.radians(200)
STYLES = ("grid", "column", "row", "fan", "ring")


@dataclass(frozen=True)
class Layout:
    """Panel geometry for one dock."""

    style: str
    count: int
    width: int
    height: int
    cells: list[tuple[int, int]]      # top-left of each icon cell, panel coordinates
    anchor_x: int                     # where the collapsed dock icon sits, panel coordinates
    anchor_y: int
    cell_w: int = 0                   # full cell width, label included
    cell_h: int = 0                   # full cell height, label strip included

    def cell_size(self) -> tuple[int, int]:
        """Width and height of one cell, falling back to the icon box."""
        return self.cell_w or 0, self.cell_h or 0
    def cell_count(self) -> int:
        return len(self.cells)


def icon_cell(icon: int, label_height: int = LABEL_HEIGHT, labels: bool = False,
              min_width: int = 0) -> tuple[int, int]:
    """Width/height of a single icon cell (icon plus its label strip).

    A label is a horizontal line of text, so it needs *width* as well as the
    height of the strip. The cell used to be exactly as wide as the icon, which
    left the name only the icon's own width to fit into: short names survived,
    long ones were clipped to "Web Bankin...". The cell now widens by a share of
    the icon so the name has room without pushing the icons far apart.
    """
    icon = max(16, int(icon))
    if not labels:
        return icon, icon
    extra = int(label_height)
    # 62% of the icon on each side keeps the cells compact while letting the
    # average label breathe; anything wider made the grid feel sparse.
    extra_width = max(0, int(round(icon * LABEL_SPREAD)))
    width = icon + extra_width
    # The caller can measure the real names and ask for a wider cell. This is what
    # stops long shortcut names from being cut with an ellipsis: guessing from the
    # icon size alone could never satisfy names of very different lengths.
    if min_width > 0:
        width = max(width, int(min_width))
    return width, icon + extra


def grid_columns(count: int, icon: int, gap: int, padding: int, max_width: int) -> int:
    """How many columns a Grid dock uses, honouring the row and column caps."""
    count = max(1, int(count))
    cols = min(MAX_GRID_COLUMNS, int(math.ceil(math.sqrt(count))))
    rows = int(math.ceil(count / cols))
    while rows > MAX_GRID_ROWS and cols < MAX_GRID_COLUMNS:
        cols += 1
        rows = int(math.ceil(count / cols))
    if max_width > 0:
        fit = (max_width - 2 * padding + gap) // max(1, icon + gap)
        cols = max(1, min(cols, int(fit)))
    return cols

def _fan_points_clear(points, cell_w: int, cell_h: int, gap: int) -> bool:
    """True when no two fan cells touch once labels are part of the cell."""
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dx = abs(points[i][0] - points[j][0])
            dy = abs(points[i][1] - points[j][1])
            if dx < cell_w + gap and dy < cell_h + gap:
                return False
    return True
def _fan_radius(count: int, icon: int, cell_w: int | None = None,
                cell_h: int | None = None, gap: int = 0) -> float:
    """Radius that keeps neighbouring fan cells from touching.

    The old formula only looked at the icon, so once labels were switched on
    every neighbour overlapped: at 11 items the centres were 62px apart while a
    labelled cell needs 158px. Sizing by the cell diagonal fixes both, the same
    way the ring is sized.
    """
    count = max(1, int(count))
    if count == 1:
        return float(max(icon, 1)) * 1.35
    w = max(1, int(cell_w or icon))
    h = max(1, int(cell_h or icon))
    gap = max(0, int(gap))
    diagonal = math.hypot(w, h)
    chord = diagonal * 1.08 + gap + 6
    step = FAN_SPAN / (count - 1)
    # A chord estimate alone is not enough: the cells are axis-aligned boxes.
    # We use a binary search to find the exact minimum radius efficiently,
    # replacing the old O(N) brute-force multiplication loop.
    min_rad = max(icon * 1.2, chord / (2 * math.sin(step / 2)))
    max_rad = min_rad * 4.0
    
    def check_rad(r: float) -> bool:
        pts = []
        for i in range(count):
            ang = FAN_START + FAN_SPAN * (i / (count - 1))
            pts.append((r * math.cos(ang), r * math.sin(ang)))
        return _fan_points_clear(pts, w, h, gap)

    while not check_rad(max_rad):
        max_rad *= 2.0

    for _ in range(12):  # 12 iterações bastam para precisão sub-pixel
        mid = (min_rad + max_rad) / 2.0
        if check_rad(mid):
            max_rad = mid
        else:
            min_rad = mid
    return max_rad


def _ring_radius(
    count: int,
    icon: int,
    gap: int,
    cell_w: int | None = None,
    cell_h: int | None = None,
) -> float:
    """Radius that keeps neighbouring ring cells from touching.

    The circumference has to fit the *widest* side of a cell, which is the
    height once labels are switched on. Sizing only by the icon packed the
    labels of one item under the icons of the next.
    """
    count = max(1, int(count))
    if count == 1:
        return max(icon * 1.25, float(icon))
    w = max(1, int(cell_w or icon))
    h = max(1, int(cell_h or icon))
    # Neighbours on a circle are separated by the chord between their centres, not
    # by the arc. A cell is a rectangle, so the radius has to be large enough that
    # the chord clears the cell diagonal; sizing by the widest edge left the labels
    # of one item tucked under the icons of the next.
    diagonal = math.hypot(w, h)
    # The 1.08 and the extra breathing room open the ring up a little: a flush fit
    # read as cramped even when the rectangles technically did not touch.
    chord = diagonal * 1.08 + max(0, int(gap)) + 6
    return max(icon * 1.35, chord / (2 * math.sin(math.pi / count)))


def build_layout(
    style: str,
    count: int,
    icon: int = 64,
    gap: int = DEFAULT_GAP,
    padding: int = DEFAULT_PADDING,
    label_height: int = LABEL_HEIGHT,
    labels: bool = False,
    max_width: int = 0,
    max_height: int = 0,
    min_cell_width: int = 0,
) -> Layout:
    """Compute the panel rectangle and each icon cell for a dock.

    max_width (pixels, 0 = unlimited) caps Grid columns so a wide dock still
    fits on screen.
    """
    style = style if style in STYLES else "grid"
    count = max(0, int(count))
    cell_w, cell_h = icon_cell(icon, label_height, labels, min_cell_width)
    gap = max(0, int(gap))
    padding = max(0, int(padding))
    cells: list[tuple[int, int]] = []

    if style in ("grid", "column", "row"):
        if style == "grid":
            cols = grid_columns(count or 1, icon, gap, padding, max_width)
        elif style == "column":
            # A single column grows past the screen once a dock holds a dozen
            # labelled items, so it wraps into as many columns as needed instead of
            # running off the screen edge where the icons could not be reached.
            # Height is the axis that overflows for a column, so max_height is the
            # limit to respect (max_width is only a fallback when it is not given).
            cols = 1
            limit = max_height or max_width
            if limit > 0 and count:
                per_col = max(1, (limit - padding * 2 + gap) // max(1, cell_h + gap))
                if count > per_col:
                    cols = int(math.ceil(count / per_col))
        else:
            cols = max(1, count)
        rows = int(math.ceil(count / cols)) if count else 0
        if count:
            width = padding * 2 + cols * cell_w + max(0, cols - 1) * gap
            height = padding * 2 + rows * cell_h + max(0, rows - 1) * gap
        else:
            width = height = icon + padding * 2
        for index in range(count):
            row, col = divmod(index, cols)
            cells.append((padding + col * (cell_w + gap), padding + row * (cell_h + gap)))
        return Layout(style, count, int(width), int(height), cells, int(width // 2), int(height), cell_w, cell_h)

    if style == "fan":
        radius = _fan_radius(count, icon, cell_w, cell_h, gap)
        span = FAN_SPAN
        start = FAN_START
        points = []
        for index in range(count):
            angle = start + span * (index / (count - 1)) if count > 1 else start + span / 2
            points.append((radius * math.cos(angle), radius * math.sin(angle)))
        # The arc is centred on the dock icon, not on the bounding box: the arc
        # spans 240 degrees, so the box is wider on the side the items lean to.
        # Offsetting by the box put the disc's centre 11px off the icon and, worse,
        # sized the disc from the box instead of from the cells themselves. Each
        # cell corner is measured from the icon, and the disc radius becomes the
        # true reach, so nothing is ever drawn outside the circle.
        reach = 0.0
        for point_x, point_y in points:
            for corner_x, corner_y in (
                (point_x - cell_w / 2, point_y - cell_h / 2),
                (point_x + cell_w / 2, point_y - cell_h / 2),
                (point_x - cell_w / 2, point_y + cell_h / 2),
                (point_x + cell_w / 2, point_y + cell_h / 2),
            ):
                reach = max(reach, math.hypot(corner_x, corner_y))
        radius = math.ceil(reach) + padding
        side = int(radius * 2)
        for point_x, point_y in points:
            cells.append((int(round(point_x + radius - cell_w / 2)),
                          int(round(point_y + radius - cell_h / 2))))
        centre = side // 2
        return Layout(style, count, side, side, cells, centre, centre, cell_w, cell_h)

    # ring
    radius = _ring_radius(count, icon, gap, cell_w, cell_h)
    # Lay the cells out around the origin first, then size the panel from where
    # they actually landed. A cell sitting on a diagonal reaches further from the
    # centre than half its own edge, so sizing the disc by the edge alone left the
    # corners of the outer cells poking through the rim and over the transparent
    # edge of the window.
    raw: list[tuple[float, float]] = []
    for index in range(count):
        angle = -math.pi / 2 + (2 * math.pi * index / count if count else 0)
        raw.append((radius * math.cos(angle) - cell_w / 2,
                    radius * math.sin(angle) - cell_h / 2))
    reach = 0.0
    for cell_x, cell_y in raw:
        for corner_x, corner_y in (
            (cell_x, cell_y),
            (cell_x + cell_w, cell_y),
            (cell_x, cell_y + cell_h),
            (cell_x + cell_w, cell_y + cell_h),
        ):
            reach = max(reach, math.hypot(corner_x, corner_y))
    if not raw:
        # Empty dock: keep a panel big enough for the hint text.
        half = int(round(radius)) + padding
    else:
        half = int(math.ceil(reach)) + padding
    side = half * 2
    shift = float(half)
    for cell_x, cell_y in raw:
        cells.append((int(round(cell_x + shift)), int(round(cell_y + shift))))
    return Layout("ring", count, side, side, cells, side // 2, side // 2, cell_w, cell_h)


def place_panel(icon_rect: Rect, layout: Layout, monitor: Rect, margin: int = 10) -> tuple[int, int]:
    """Where to put an expanded panel so it stays attached to its dock icon.

    Grid, Column and Row open upwards and flip below when there is no room
    above; Fan and Ring stay anchored on the icon. The result is clamped to the
    monitor so a panel never spills off screen.
    """
    left, top, iw, ih = icon_rect
    cx = left + iw // 2

    if layout.style in ("fan", "ring"):
        x = cx - layout.anchor_x
        y = (top + ih // 2) - layout.anchor_y
    else:
        x = cx - layout.anchor_x
        y = top - margin - layout.height
        if y < monitor[1]:
            y = top + ih + margin

    return clamp_to_monitor((int(x), int(y), layout.width, layout.height), monitor)


def clamp_to_monitor(rect: Rect, monitor: Rect, margin: int = 4) -> tuple[int, int]:
    """Shift a rect just enough to keep it inside the monitor."""
    x, y, w, h = rect
    mon_left, mon_top, mon_w, mon_h = monitor
    if w > mon_w:
        x = mon_left
    else:
        x = max(mon_left + margin, min(x, mon_left + mon_w - w - margin))
    if h > mon_h:
        y = mon_top
    else:
        y = max(mon_top + margin, min(y, mon_top + mon_h - h - margin))
    return int(x), int(y)


def contains(rect: Rect, x: int, y: int) -> bool:
    left, top, width, height = rect
    return left <= x < left + width and top <= y < top + height


def monitor_for_point(monitors: list[Rect], x: int, y: int) -> Rect:
    """Monitor that owns a point, falling back to the first monitor."""
    for monitor in monitors:
        if contains(monitor, x, y):
            return monitor
    return monitors[0] if monitors else (0, 0, 1920, 1080)


def snap_to_grid(
    x: int,
    y: int,
    monitor: Rect,
    cell: tuple[int, int],
    origin: tuple[int, int] = (0, 0),
) -> tuple[int, int]:
    """Snap a desktop point onto the icon grid of a monitor."""
    cell_w, cell_h = cell
    mon_left, mon_top, mon_w, mon_h = monitor
    origin_x = mon_left + origin[0]
    origin_y = mon_top + origin[1]
    col = round((x - origin_x) / max(1, cell_w))
    row = round((y - origin_y) / max(1, cell_h))
    max_col = max(0, (mon_w - origin[0]) // max(1, cell_w) - 1)
    max_row = max(0, (mon_h - origin[1]) // max(1, cell_h) - 1)
    col = max(0, min(int(col), int(max_col)))
    row = max(0, min(int(row), int(max_row)))
    return origin_x + col * cell_w, origin_y + row * cell_h


def offset_point(x: int, y: int, dx: int, dy: int) -> tuple[int, int]:
    return int(x) + int(dx), int(y) + int(dy)


@dataclass
class Occupancy:
    """Rects already taken on a monitor (used when nudging a native icon aside)."""

    rects: list[Rect] = field(default_factory=list)

    def collides(self, rect: Rect) -> bool:
        left, top, width, height = rect
        for other in self.rects:
            o_left, o_top, o_w, o_h = other
            if left < o_left + o_w and o_left < left + width and top < o_top + o_h and o_top < top + height:
                return True
        return False

    def add(self, rect: Rect) -> None:
        self.rects.append(rect)


def first_free_cell(
    monitor: Rect,
    cell: tuple[int, int],
    occupied: Occupancy,
    preferred: tuple[int, int] | None = None,
    origin: tuple[int, int] = (0, 0),
    icon: int = 64,
) -> tuple[int, int]:
    """Nearest free grid cell to the preferred spot inside a monitor.

    Used when a dock lands on a cell that already holds a native desktop icon:
    the native icon is nudged to this spot instead of being covered up.
    """
    cell_w, cell_h = cell
    mon_left, mon_top, mon_w, mon_h = monitor
    origin_x = mon_left + origin[0]
    origin_y = mon_top + origin[1]
    cols = max(1, (mon_w - origin[0]) // max(1, cell_w))
    rows = max(1, (mon_h - origin[1]) // max(1, cell_h))
    if preferred is None:
        preferred = (0, 0)
    p_col = int(round((preferred[0] - origin_x) / max(1, cell_w)))
    p_row = int(round((preferred[1] - origin_y) / max(1, cell_h)))
    best: tuple[float, int, int] | None = None
    for row in range(rows):
        for col in range(cols):
            candidate = (origin_x + col * cell_w, origin_y + row * cell_h, icon, icon)
            if occupied.collides(candidate):
                continue
            distance = (col - p_col) ** 2 + (row - p_row) ** 2
            if best is None or distance < best[0]:
                best = (distance, candidate[0], candidate[1])
                if distance == 0:
                    return candidate[0], candidate[1]
    if best is None:
        return preferred[0], preferred[1]
    return best[1], best[2]
