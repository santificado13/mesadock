"""Folder portals: a dock whose items mirror the contents of a folder.

Pure filesystem logic, no Tk. The app polls :func:`signature` and calls
:func:`sync_items` when the folder changed. Nothing here ever writes to the
mirrored folder: a portal only reads it.
"""
from __future__ import annotations

import os
from pathlib import Path

from .models import DockFolder, DockItem

MAX_ITEMS = 60
_SKIP_NAMES = {"desktop.ini", "thumbs.db", "$recycle.bin", "system volume information"}
_SHORTCUT_SUFFIXES = (".lnk", ".url")


def _is_hidden(entry: os.DirEntry) -> bool:
    name = entry.name
    if name.startswith(".") or name.startswith("~$") or name.lower() in _SKIP_NAMES:
        return True
    try:
        attributes = entry.stat(follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attributes & 0x2) or bool(attributes & 0x4)  # HIDDEN or SYSTEM


def scan(folder: str | Path, limit: int = MAX_ITEMS) -> list[tuple[str, str, str]] | None:
    """Visible entries of ``folder`` as (name, kind, path): folders first, by name.

    Returns ``None`` when the folder is missing or unreadable (an unplugged drive,
    a network share that is offline, a mapped drive not mounted yet at logon).
    That is different from an empty folder, which is an empty list.
    """
    found: list[tuple[int, str, str, str, str]] = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if _is_hidden(entry):
                    continue
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    continue
                suffix = os.path.splitext(entry.name)[1].lower()
                if is_dir:
                    kind, name = "folder", entry.name
                elif suffix in _SHORTCUT_SUFFIXES:
                    kind, name = "shortcut", os.path.splitext(entry.name)[0]
                else:
                    kind, name = "file", entry.name
                found.append((0 if is_dir else 1, name.casefold(), name, kind, entry.path))
    except OSError:
        return None
    found.sort()
    return [(name, kind, path) for _order, _key, name, kind, path in found[:max(0, limit)]]


def signature(folder: str | Path) -> tuple:
    """Cheap fingerprint of the folder listing; changes when entries come or go."""
    try:
        with os.scandir(folder) as entries:
            return tuple(sorted(entry.name for entry in entries))
    except OSError:
        return ("<unavailable>",)


def sync_items(dock: DockFolder, entries: list[tuple[str, str, str]] | None = None,
               limit: int = MAX_ITEMS) -> bool:
    """Make ``dock.items`` match its portal folder. Returns True when it changed.

    Items are matched by path, so an entry that is still there keeps its id and
    any custom icon the user gave it. ``entries`` is a :func:`scan` result made
    elsewhere (the watcher scans on a worker thread so a slow network folder
    never blocks the interface); without it the folder is scanned here.

    When the folder cannot be read the items are left alone: wiping them would
    lose their ids and custom icons the moment a drive is unplugged.
    """
    if not dock.portal:
        return False
    if entries is None:
        entries = scan(dock.portal, limit)
    if entries is None:
        return False
    existing = {os.path.normcase(item.path): item for item in dock.items}
    fresh: list[DockItem] = []
    for name, kind, path in entries:
        item = existing.get(os.path.normcase(path))
        if item is None:
            item = DockItem(name=name, kind=kind, path=path, target=path)
        else:
            item.name, item.kind = name, kind
        fresh.append(item)
    changed = [item.id for item in fresh] != [item.id for item in dock.items]
    dock.items = fresh
    return changed


def default_name(folder: str | Path) -> str:
    path = Path(folder)
    return path.name or str(path)
