"""Windows-specific behaviour the GUI depends on: z-order and shell focus.

The dock and panel windows are normal Toplevels repositioned every tick, which
would fight the mouse if Tk processed the move between the pointer's own motion
events. keep_pointer therefore positions a window whose top-left corner is the
hot spot, so the pointer never lands on a different part of the overlay.
"""
from __future__ import annotations

import ctypes

from . import desktop_enabled


def keep_pointer(window, hot_x: int = 0, hot_y: int = 0) -> bool:
    """Move a window so its hot spot sits exactly under the cursor.

    Used for feedback overlays (the drag ghost and the drop highlight) where any
    lag between the pointer and the window shows up as jitter.
    """
    if not desktop_enabled():
        return False
    try:
        from ctypes import wintypes

        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return False
        window.geometry("+" + str(int(point.x) - int(hot_x)) + "+" + str(int(point.y) - hot_y))
        return True
    except (AttributeError, OSError):
        return False


def move_to_front_once(hwnd: int) -> bool:
    """Raise a window without activating it (used by the drag ghost)."""
    if not desktop_enabled() or not hwnd:
        return False
    try:
        HWND_TOP = 0
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        return bool(
            ctypes.windll.user32.SetWindowPos(
                int(hwnd), HWND_TOP, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            )
        )
    except (AttributeError, OSError):
        return False


def foreground_class() -> str:
    """Window class of the foreground window (empty when unknown)."""
    if not desktop_enabled():
        return ""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetClassNameW(hwnd, None, 0)
        buffer = ctypes.create_unicode_buffer(length + 2)
        user32.GetClassNameW(hwnd, buffer, length + 2)
        return buffer.value
    except (AttributeError, OSError):
        return ""


def is_desktop_active() -> bool:
    """True when the foreground window belongs to the desktop or the shell."""
    name = foreground_class()
    return name in ("Progman", "WorkerW", "Shell_TrayWnd") or name.startswith("Windows.UI.")
