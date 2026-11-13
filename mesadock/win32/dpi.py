"""Per-monitor DPI awareness.

A process must declare DPI awareness before any window exists, otherwise Windows
stretches the app on scaled monitors and every measured rectangle is wrong.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import is_windows

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_APPLIED: str | None = None


def enable_per_monitor_v2() -> str:
    """Make the process Per-Monitor V2 DPI aware, falling back gracefully.

    Returns the mode that was actually applied:
    "per-monitor-v2", "per-monitor", "system" or "unavailable".
    """
    global _APPLIED
    if _APPLIED is not None:
        return _APPLIED
    if not is_windows():
        _APPLIED = "unavailable"
        return _APPLIED
    try:
        user32 = ctypes.windll.user32
        try:
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                _APPLIED = "per-monitor-v2"
                return _APPLIED
        except (AttributeError, OSError):
            pass
        try:
            if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
                _APPLIED = "per-monitor"
                return _APPLIED
        except (AttributeError, OSError):
            pass
        try:
            if user32.SetProcessDPIAware():
                _APPLIED = "system"
                return _APPLIED
        except (AttributeError, OSError):
            pass
    except (AttributeError, OSError):
        pass
    _APPLIED = "unavailable"
    return _APPLIED


def dpi_for_monitor(hmonitor: int) -> tuple[int, int]:
    """(dpi_x, dpi_y) for a monitor handle, defaulting to 96."""
    if not is_windows():
        return 96, 96
    try:
        dpix = wintypes.UINT(96)
        dpiy = wintypes.UINT(96)
        fn = ctypes.windll.shcore.GetDpiForMonitor
        if fn(int(hmonitor), 0, ctypes.byref(dpix), ctypes.byref(dpiy)) == 0:
            return int(dpix.value), int(dpiy.value)
    except (AttributeError, OSError):
        pass
    return 96, 96


def scale_for_monitor(hmonitor: int) -> float:
    """Scale factor (1.0 = 100 percent) for a monitor handle."""
    dpi = dpi_for_monitor(hmonitor)[0]
    return max(0.5, min(4.0, dpi / 96.0))
