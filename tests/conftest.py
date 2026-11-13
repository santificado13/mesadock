"""Shared pytest fixtures.

Every test runs against a throwaway MESADOCK_HOME and with the live-desktop
integration disabled, so a test run can never move the developer's icons.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("MESADOCK_NO_DESKTOP", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
