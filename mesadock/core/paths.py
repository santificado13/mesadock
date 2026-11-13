"""Filesystem locations for MesaDock.

Everything lives in %APPDATA%/MesaDock unless MESADOCK_HOME overrides it
(used by the test-suite so tests never touch a real profile).
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIRNAME = "MesaDock"


def home_dir() -> Path:
    """Root folder that holds all MesaDock data."""
    override = os.environ.get("MESADOCK_HOME")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIRNAME


def ensure_dirs() -> None:
    for path in (home_dir(), archive_dir(), items_dir(), icons_cache_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True)


def store_file() -> Path:
    return home_dir() / "store.json"



def items_dir() -> Path:
    """MesaDock's own copy of every shortcut/file it manages."""
    return home_dir() / "items"


def _safe_segment(name: str) -> str:
    cleaned = "".join(c for c in str(name) if c.isalnum() or c in " -_.")
    return cleaned.strip() or "Default"


def archive_dir(profile: str | None = None) -> Path:
    """Where moved-away desktop originals are kept (one subfolder per profile)."""
    base = home_dir() / "archived"
    return base / _safe_segment(profile) if profile else base


def icons_cache_dir() -> Path:
    return home_dir() / "icons"


def logs_dir() -> Path:
    return home_dir() / "logs"


def log_file() -> Path:
    return logs_dir() / "mesadock.log"


def show_request_file() -> Path:
    """Handshake file dropped by a second launch to open the Manager."""
    return home_dir() / "show-manager.request"

def resource_dir() -> Path:
    """Folder with shipped assets (works both from source and PyInstaller)."""
    import sys

    if getattr(sys, "frozen", False):  # PyInstaller bundle
        # Assets are placed in mesadock/assets/ by build.ps1 --add-data
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "mesadock" / "assets"
    return Path(__file__).resolve().parent.parent / "assets"

def asset(name: str) -> Path:
    return resource_dir() / name
