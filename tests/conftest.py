"""Shared pytest fixtures.

Every test runs against a throwaway MESADOCK_HOME and with the live-desktop
integration disabled, so a test run can never move the developer's icons.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("MESADOCK_NO_DESKTOP", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Messages of the same flaky Tcl/Tk start-up failure seen on GitHub's runners.
_FLAKY_TK_INIT = ("tcl_findLibrary", "usable tk.tcl", "usable init.tcl")


def _retry_flaky_tk_init() -> None:
    """Retry Tk() when Tcl fails to load its own start-up scripts.

    On GitHub's Windows runners (seen with Python 3.12), creating many Tk roots
    in one test run now and then fails inside Tk's initialisation with
    'invalid command name "tcl_findLibrary"' or "Can't find a usable tk.tcl".
    It is an environment race, not a MesaDock bug (the app creates a single
    root), so the tests retry those errors and nothing else.
    """
    try:
        import tkinter
    except ImportError:
        return
    if getattr(tkinter.Tk, "_mesadock_retry", False):
        return

    class _RetryingTk(tkinter.Tk):
        _mesadock_retry = True

        def __init__(self, *args, **kwargs):
            for attempt in range(5):
                try:
                    super().__init__(*args, **kwargs)
                    return
                except tkinter.TclError as exc:
                    if not any(text in str(exc) for text in _FLAKY_TK_INIT) or attempt == 4:
                        raise
                    time.sleep(0.5)

    tkinter.Tk = _RetryingTk


_retry_flaky_tk_init()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A temporary data folder used as %APPDATA%/MesaDock."""
    monkeypatch.setenv("MESADOCK_HOME", str(tmp_path))
    from mesadock.core import paths

    paths.ensure_dirs()
    return tmp_path


@pytest.fixture()
def store(home):
    from mesadock.core.store import Store

    return Store(path=home / "store.json")


@pytest.fixture()
def desktop_dir(tmp_path, monkeypatch):
    """A fake Desktop folder that archive tests may move files out of."""
    folder = tmp_path / "Desktop"
    folder.mkdir()
    from mesadock.core import archive

    monkeypatch.setattr(archive, "user_desktop_dirs", lambda: [folder])
    return folder


def make_file(folder: Path, name: str = "Example.lnk", content: bytes = b"shortcut") -> Path:
    path = folder / name
    path.write_bytes(content)
    return path
