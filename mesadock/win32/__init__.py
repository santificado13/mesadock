"""Thin ctypes layer over the Win32 APIs MesaDock needs.

Every module here degrades gracefully when it is imported on a non-Windows host
or with MESADOCK_NO_DESKTOP=1 (used by CI and by the test-suite): callers get
the documented fallback value instead of an exception, so the persistence and
layout layers stay testable everywhere.
"""
from __future__ import annotations

import os
import sys


def is_windows() -> bool:
    return sys.platform.startswith("win")


def desktop_enabled() -> bool:
    """True when the live-desktop integration may be used."""
    if os.environ.get("MESADOCK_NO_DESKTOP") in ("1", "true", "yes"):
        return False
    return is_windows()
