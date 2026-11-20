"""Adding, archiving and restoring desktop items.

MesaDock never deletes anything. When an item is added in Move mode its
original is tucked into archived/<profile>/ and MesaDock keeps its own copy in
items/<dock>/, so entries keep working after the original is moved or renamed.
Removing an item (or uninstalling) puts the original back where it came from.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..win32 import shell
from . import paths
from .i18n import tr
from .models import DockItem, new_id


@dataclass
class ArchiveResult:
    """Outcome of adding or restoring an item."""

    ok: bool
    message: str = ""
    item: DockItem | None = None

    def __bool__(self) -> bool:
        return self.ok


def unique_path(directory: Path, filename: str) -> Path:
    """A free path inside directory for filename (adds \" (2)\" etc.)."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        candidate = directory / (stem + " (" + str(index) + ")" + suffix)
        if not candidate.exists():
            return candidate
        index += 1


def safe_filename(name: str, fallback: str = "item") -> str:
    cleaned = "".join(c for c in str(name) if c not in '\\/:*?"<>|').strip().strip(".")
    return cleaned or fallback


class Archiver:
    """Owns the lifetime of the files behind dock items."""

    def __init__(self, profile_name: str = "Default", mode: str = "move") -> None:
        self.profile_name = profile_name
        self.mode = mode if mode in ("move", "copy") else "move"

    # -- locations ---------------------------------------------------------
    def items_dir(self, dock_id: str) -> Path:
        return paths.items_dir() / safe_filename(dock_id, "dock")

    def archive_dir(self) -> Path:
        return paths.archive_dir(self.profile_name)

    # -- adding ------------------------------------------------------------
    def add_from_path(self, source: str | Path, dock_id: str, name: str | None = None) -> ArchiveResult:
        """Add a shortcut, file, folder or url to a dock.

        In Move mode the original is archived and the desktop gets cleaner; in
        Copy mode the original stays where it is.
        """
        text = str(source).strip()
        if not text:
            return ArchiveResult(False, tr("Empty path"))
        if shell.is_url(text):
            return self.add_url(text, dock_id, name=name)
        path = Path(text).expanduser()
        if not path.exists():
            return ArchiveResult(False, tr("Not found: ") + text)
        try:
            if path.is_dir():
                item = DockItem(
                    name=name or path.name,
                    kind="folder",
                    path=str(path),
                    target=str(path),
                    archived_from="",
                )
                return ArchiveResult(True, tr("Folder linked in place"), item)
            return self._add_file(path, dock_id, name=name)
        except OSError as exc:
            return ArchiveResult(False, tr("Could not add: ") + str(exc))

    def add_url(self, url: str, dock_id: str, name: str | None = None) -> ArchiveResult:
        url = (url or "").strip()
        if not url:
            return ArchiveResult(False, tr("Empty url"))
        if not shell.is_url(url):
            url = "https://" + url
        label = name or _url_label(url)
        target_dir = self.items_dir(dock_id) / "links"
        link_path = unique_path(target_dir, safe_filename(label) + ".url")
        try:
            shell.write_url_file(link_path, url)
        except OSError as exc:
            return ArchiveResult(False, tr("Could not store link: ") + str(exc))
        item = DockItem(name=label, kind="url", path=str(link_path), target=url)
        return ArchiveResult(True, tr("Link added"), item)

    def _add_file(self, path: Path, dock_id: str, name: str | None = None) -> ArchiveResult:
        target_dir = self.items_dir(dock_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        stored = unique_path(target_dir, safe_filename(path.name, "item"))
        shutil.copy2(path, stored)
        item = DockItem(name=name or path.stem, kind="shortcut" if shell.is_shortcut(path) else "file", path=str(stored))
        if shell.is_shortcut(path):
            info = shell.read_shortcut(path)
            item.target = info.get("target") or str(path)
            item.args = info.get("args") or ""
        else:
            item.target = str(path)
        if self.mode == "move" and self._is_on_desktop(path):
            original = path
            archived = self.archive_original(original)
            if archived is not None:
                item.archived_from = str(original)
        return ArchiveResult(True, tr("Added"), item)

    # -- archiving ---------------------------------------------------------
    def _is_on_desktop(self, path: Path) -> bool:
        try:
            desktop = user_desktop_dirs()
        except OSError:
            return False
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return any(_is_inside(resolved, folder) for folder in desktop)

    def archive_original(self, path: Path) -> Path | None:
        """Move a desktop original into the archive; returns its new path."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        destination = unique_path(self.archive_dir(), stamp + "_" + safe_filename(path.name, "item"))
        try:
            shutil.move(str(path), str(destination))
            return destination
        except OSError:
            return None

    def _restore_destination(self, item: DockItem) -> Path:
        """Where a restored original belongs, corrected for desktop redirection.

        archived_from records the path the file had when it was archived. If the
        desktop has since moved (OneDrive redirection, a localized folder name,
        or an older build guessing home/Desktop) that path is no longer on the
        desktop, so put the file back on the desktop Windows actually shows.
        """
        recorded = Path(item.archived_from)
        parent = recorded.parent
        try:
            known = [d for d in user_desktop_dirs()]
        except OSError:
            known = []
        for folder in known:
            try:
                if parent.resolve() == folder.resolve():
                    return recorded
            except OSError:
                pass
        known_desktop = shell.known_desktop_dir()
        if known_desktop is not None:
            return known_desktop / recorded.name
        return recorded

    def restore_original(self, item: DockItem) -> bool:
        """Put an archived original back on the desktop."""
        if not item.archived_from:
            return False
        current = self._restore_destination(item)
        if current.exists():
            return True  # already back
        archived = self._find_archived(item)
        if archived is None:
            return False
        try:
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived), str(current))
        except (OSError, shutil.Error):
            return False
        item.archived_from = ""
        return True

    def _find_archived(self, item: DockItem) -> Path | None:
        """Locate the archived copy that belongs to an item's original path."""
        name = safe_filename(Path(item.archived_from).name, "item")
        directory = self.archive_dir()
        if not directory.exists():
            return None
        matches = sorted(directory.glob("*_" + name))
        return matches[-1] if matches else None

    def restore_all(self, items: list[DockItem]) -> int:
        """Restore every archived original (used by remove-all and uninstall)."""
        return sum(1 for item in items if self.restore_original(item))

    # -- removing ----------------------------------------------------------
    def release_item(self, item: DockItem, delete_copy: bool = True) -> None:
        """Undo an item: restore its original and drop MesaDock's own copy."""
        self.restore_original(item)
        if delete_copy and item.path and item.kind != "folder":
            try:
                copy = Path(item.path)
                if copy.exists() and _is_inside(copy, paths.items_dir()):
                    copy.unlink()
            except OSError:
                pass


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _url_label(url: str) -> str:
    cleaned = url.split("://", 1)[-1]
    cleaned = cleaned.split("/", 1)[0]
    cleaned = cleaned[4:] if cleaned.startswith("www.") else cleaned
    return cleaned or "Link"


def user_desktop_dirs() -> list[Path]:
    """Every Desktop folder for the current user (OneDrive redirection included).

    The folder Windows reports through SHGetKnownFolderPath always comes first:
    on a machine with a OneDrive-redirected, localized desktop the guesswork
    below finds extra folders that the shell does not actually show.
    """
    candidates: list[Path] = []
    known = shell.known_desktop_dir()
    if known is not None:
        candidates.append(known)
    home = Path.home()
    candidates.append(home / "Desktop")
    onedrive = home / "OneDrive"
    if onedrive.exists():
        candidates.append(onedrive / "Desktop")
        candidates.append(onedrive / "Area de Trabalho")
        candidates.append(onedrive / "Área de Trabalho")
    candidates.extend([home / "Area de Trabalho", home / "Área de Trabalho"])
    public = Path("C:/Users/Public/Desktop")
    if public.exists():
        candidates.append(public)
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if candidate.exists() and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def desktop_shortcuts() -> list[Path]:
    """Every .lnk and .url on the user's desktop(s)."""
    found: list[Path] = []
    for folder in user_desktop_dirs():
        try:
            found.extend(sorted(folder.glob("*.lnk")))
            found.extend(sorted(folder.glob("*.url")))
        except OSError:
            continue
    return found


def new_dock_folder_id() -> str:
    return new_id("f_")
