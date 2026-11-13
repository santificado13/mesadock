"""Monitor enumeration, work areas and the desktop icon grid.

Rectangles are (left, top, width, height) in virtual-screen pixels, matching the
core.layout helpers.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import is_windows
from .dpi import scale_for_monitor

MONITOR_DEFAULTTONEAREST = 2

if is_windows():
    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]


class Monitor:
    """One display: its bounds, work area (without taskbar) and DPI scale."""

    __slots__ = ("handle", "rect", "work", "scale", "primary")

    def __init__(self, handle: int, rect: tuple[int, int, int, int], work: tuple[int, int, int, int], scale: float, primary: bool) -> None:
        self.handle = handle
        self.rect = rect
        self.work = work
        self.scale = scale
        self.primary = primary

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Monitor(rect={self.rect}, work={self.work}, scale={self.scale:.2f}, primary={self.primary})"


def virtual_screen() -> tuple[int, int, int, int]:
    """Bounding rectangle covering every monitor."""
    if not is_windows():
        return 0, 0, 1920, 1080
    try:
        metrics = ctypes.windll.user32.GetSystemMetrics
        left = metrics(76)     # SM_XVIRTUALSCREEN
        top = metrics(77)      # SM_YVIRTUALSCREEN
        width = metrics(78)    # SM_CXVIRTUALSCREEN
        height = metrics(79)   # SM_CYVIRTUALSCREEN
        return left, top, width or 1920, height or 1080
    except (AttributeError, OSError):
        return 0, 0, 1920, 1080


def list_monitors() -> list[Monitor]:
    """Every monitor, primary first."""
    if not is_windows():
        return [Monitor(0, (0, 0, 1920, 1080), (0, 0, 1920, 1040), 1.0, True)]
    monitors: list[Monitor] = []
    try:
        user32 = ctypes.windll.user32
        proto = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        def callback(hmonitor, hdc, rect_ptr, data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                mon = info.rcMonitor
                work = info.rcWork
                monitors.append(
                    Monitor(
                        int(hmonitor),
                        (mon.left, mon.top, mon.right - mon.left, mon.bottom - mon.top),
                        (work.left, work.top, work.right - work.left, work.bottom - work.top),
                        scale_for_monitor(int(hmonitor)),
                        bool(info.dwFlags & 1),
                    )
                )
            return True

        user32.EnumDisplayMonitors(None, None, proto(callback), 0)
    except (AttributeError, OSError):
        pass
    if not monitors:
        monitors = [Monitor(0, (0, 0, 1920, 1080), (0, 0, 1920, 1040), 1.0, True)]
    monitors.sort(key=lambda m: (not m.primary, m.rect[0], m.rect[1]))
    return monitors


def primary_monitor() -> Monitor:
    for monitor in list_monitors():
        if monitor.primary:
            return monitor
    return list_monitors()[0]


def monitor_at(x: int, y: int) -> Monitor:
    """Monitor containing a virtual-screen point (nearest when none does)."""
    for monitor in list_monitors():
        left, top, width, height = monitor.rect
        if left <= x < left + width and top <= y < top + height:
            return monitor
    return primary_monitor()


def work_rects() -> list[tuple[int, int, int, int]]:
    return [monitor.work for monitor in list_monitors()]
