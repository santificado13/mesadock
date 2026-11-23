"""Backup and restore of everything MesaDock keeps: docks, items, archive.

A backup is one zip with the database (profiles, docks, settings), MesaDock's
own copies of the shortcuts (``items``) and the originals it moved off the
desktop (``archived``), plus a small manifest. Logs and the icon cache are left
out: they are rebuilt on demand.

Restoring never destroys the current state. The backup is fully unpacked and
checked first; then each folder is swapped with a single rename, which either
happens or does not, and what was there goes to ``backups/before-restore-*``.
If any step fails, the steps already done are undone.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path

from . import paths

MANIFEST = "mesadock-backup.json"
DATABASE = "store.db"
FOLDERS = ("items", "archived")
ENTRIES = (DATABASE,) + FOLDERS
AUTO_PREFIX = "auto-"
KEPT_PREFIX = "before-restore-"
FORMAT = 1


class BackupError(RuntimeError):
    """The file is not a MesaDock backup, or it could not be read or applied."""


def backups_dir(home: Path | None = None) -> Path:
    return (home or paths.home_dir()) / "backups"


def _snapshot_database(source: Path, target: Path) -> None:
    """Consistent copy of the SQLite file, even while the app is writing to it.

    Copying the file itself could catch it in the middle of a commit; SQLite's
    own backup API waits for a consistent state.
    """
    reader = sqlite3.connect(str(source))
    try:
        writer = sqlite3.connect(str(target))
        try:
            reader.backup(writer)
        finally:
            writer.close()
    finally:
        reader.close()


def _check_database(path: Path) -> dict:
    """The document stored in a database; BackupError when it is not one of ours."""
    try:
        connection = sqlite3.connect(str(path))
        try:
            row = connection.execute("SELECT payload FROM document WHERE id = 1").fetchone()
        finally:
            connection.close()
        document = json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError, TypeError) as exc:
        raise BackupError("the database in the backup cannot be read") from exc
    if not isinstance(document, dict) or not isinstance(document.get("profiles"), list):
        raise BackupError("the database in the backup cannot be read")
    return document


def create(destination: str | Path, home: Path | None = None, version: str = "") -> Path:
    """Write a backup zip of the data folder to ``destination``."""
    home = Path(home) if home else paths.home_dir()
    destination = Path(destination)
    temporary = destination.with_name(destination.name + ".part")
    snapshot = destination.with_name(destination.name + ".db")
    manifest = {"app": "MesaDock", "format": FORMAT, "version": version, "home": str(home),
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "entries": []}
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # strict_timestamps=False: a file dated before 1980 must not abort the backup.
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
            if (home / DATABASE).is_file():
                _snapshot_database(home / DATABASE, snapshot)
                archive.write(snapshot, DATABASE)
                manifest["entries"].append(DATABASE)
            for name in FOLDERS:
                source = home / name
                if not source.is_dir():
                    continue
                manifest["entries"].append(name)
                for folder, _dirs, files in os.walk(source):
                    for file_name in files:
                        path = Path(folder) / file_name
                        try:
                            archive.write(path, path.relative_to(home).as_posix())
                        except OSError:
                            continue  # vanished or locked this instant: skip that one file
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(temporary, destination)
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as exc:
        raise BackupError(str(exc)) from exc
    finally:
        for leftover in (temporary, snapshot):
            try:
                leftover.unlink()
            except OSError:
                pass
    return destination


def read_manifest(source: str | Path) -> dict:
    """Manifest of a backup; raises BackupError when the file is not one."""
    try:
        with zipfile.ZipFile(source) as archive:
            data = json.loads(archive.read(MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise BackupError("not a MesaDock backup") from exc
    if not isinstance(data, dict) or data.get("app") != "MesaDock":
        raise BackupError("not a MesaDock backup")
    try:
        newer = int(data.get("format", 1)) > FORMAT
    except (TypeError, ValueError):
        newer = True
    if newer:
        raise BackupError("this backup was made by a newer MesaDock")
    return data


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Members that stay inside the known entries; anything else is refused."""
    members = []
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        if name == MANIFEST or info.is_dir():
            continue
        parts = name.split("/")
        inside = (parts[0] == DATABASE and len(parts) == 1) or (parts[0] in FOLDERS and len(parts) >= 2)
        if name.startswith("/") or ":" in name or ".." in parts or "" in parts or not inside:
            raise BackupError("unexpected file in backup: " + info.filename)
        members.append(info)
    return members


def _rebase(document: dict, old_home: str, new_home: Path) -> bool:
    """Point stored paths at this data folder when the backup came from another
    one (a different user or PC). Returns True when something was changed."""
    old = os.path.normcase(os.path.normpath(old_home)) if old_home else ""
    new = os.path.normpath(str(new_home))
    if not old or old == os.path.normcase(new):
        return False
    changed = False
    for profile in document.get("profiles", []):
        for folder in profile.get("folders", []) or []:
            for holder in [folder] + list(folder.get("items", []) or []):
                for key in ("path", "icon"):
                    value = holder.get(key)
                    if not isinstance(value, str) or not value:
                        continue
                    plain = os.path.normpath(value)
                    if os.path.normcase(plain).startswith(old + os.sep):
                        holder[key] = new + plain[len(old):]
                        changed = True
    return changed


def _write_document(path: Path, document: dict) -> None:
    connection = sqlite3.connect(str(path))
    try:
        with connection:
            connection.execute("UPDATE document SET payload = ? WHERE id = 1",
                               (json.dumps(document, ensure_ascii=False),))
    finally:
        connection.close()


def restore(source: str | Path, home: Path | None = None) -> Path:
    """Replace the data folder contents with a backup. Returns the folder that
    holds what was there before, so the restore itself can be undone."""
    home = Path(home) if home else paths.home_dir()
    manifest = read_manifest(source)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    staging = home / ("restore-" + stamp)
    previous = backups_dir(home) / (KEPT_PREFIX + stamp)
    try:
        # 1. Unpack and check everything before touching the live data.
        with zipfile.ZipFile(source) as archive:
            members = _safe_members(archive)
            if not any(info.filename.replace("\\", "/") == DATABASE for info in members):
                raise BackupError("the backup has no database")
            for info in members:
                target = staging / info.filename.replace("\\", "/")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as reader, open(target, "wb") as writer:
                    shutil.copyfileobj(reader, writer)
        document = _check_database(staging / DATABASE)
        if _rebase(document, str(manifest.get("home") or ""), home):
            _write_document(staging / DATABASE, document)
        for name in FOLDERS:
            (staging / name).mkdir(parents=True, exist_ok=True)

        # 2. Swap. A rename either happens or leaves everything as it was; a
        #    file held open inside a folder (a document launched from a dock)
        #    makes it fail cleanly instead of moving half the folder.
        previous.mkdir(parents=True, exist_ok=True)
        swapped: list[str] = []
        try:
            for name in FOLDERS:
                current = home / name
                if current.exists():
                    os.rename(current, previous / name)
                swapped.append(name)
                os.rename(staging / name, current)
            if (home / DATABASE).exists():
                shutil.copy2(home / DATABASE, previous / DATABASE)
            # Copied over rather than renamed: SQLite may still hold the file.
            shutil.copyfile(staging / DATABASE, home / DATABASE)
        except OSError as exc:
            for name in reversed(swapped):
                current, kept = home / name, previous / name
                try:
                    if current.exists() and kept.exists():
                        os.rename(current, staging / (name + "-undone"))
                    if kept.exists():
                        os.rename(kept, current)
                except OSError:
                    pass
            raise BackupError(
                "a file inside the data folder is in use; close what was opened from a dock and try again ("
                + str(exc) + ")") from exc

        # 3. Originals archived after the backup was made are not in it. Keep
        #    them reachable ("Restore all archived shortcuts") instead of only
        #    in the before-restore folder.
        _carry_over(previous / "archived", home / "archived")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError(str(exc)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _prune(backups_dir(home), KEPT_PREFIX + "*", 3, folders=True)
    return previous


def _carry_over(old: Path, new: Path) -> None:
    if not old.is_dir():
        return
    for folder, _dirs, files in os.walk(old):
        for file_name in files:
            source = Path(folder) / file_name
            target = new / source.relative_to(old)
            if target.exists():
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            except OSError:
                continue


def _prune(folder: Path, pattern: str, keep: int, folders: bool = False) -> None:
    found = sorted(folder.glob(pattern)) if folder.is_dir() else []
    for old in found[:-max(1, keep)]:
        try:
            if folders:
                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink()
        except OSError:
            pass


def auto_backup(home: Path | None = None, version: str = "", keep: int = 7, min_hours: float = 20.0) -> Path | None:
    """Make an automatic backup unless a recent one exists; keep the newest few."""
    home = Path(home) if home else paths.home_dir()
    if not (home / DATABASE).is_file():
        return None
    folder = backups_dir(home)
    existing = sorted(folder.glob(AUTO_PREFIX + "*.zip")) if folder.is_dir() else []
    if existing and time.time() - existing[-1].stat().st_mtime < min_hours * 3600:
        return None
    created = create(folder / (AUTO_PREFIX + time.strftime("%Y%m%d-%H%M%S") + ".zip"), home, version)
    _prune(folder, AUTO_PREFIX + "*.zip", keep)
    return created
