"""SQLite persistence for profiles, docks and settings.

Replaces the JSON tempfile rotation to avoid antivirus locks and I/O conflicts,
while keeping the atomic ACID guarantees of SQLite.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import paths
from .models import DockFolder, Profile, Settings

SCHEMA_VERSION = 1


class StoreError(RuntimeError):
    """Raised when the store cannot be read or written."""


class Store:
    """In-memory document (profiles + settings) with SQLite persistence."""

    def __init__(self, path: Path | None = None, autosave: bool = False) -> None:
        # Alterado para .db para refletir o uso do SQLite
        self.path = Path(path) if path else paths.store_file()
        self.autosave = autosave
        self.schema = SCHEMA_VERSION
        self.settings = Settings()
        self.profiles: list[Profile] = [Profile(name="Default")]
        self.active_profile_index = 0
        self.dirty = False
        self.last_saved_at: float | None = None
        self.last_error: str | None = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS document (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        payload TEXT NOT NULL
                    )
                ''')
        except sqlite3.Error as exc:
            self.last_error = f"DB Init Error: {exc}"

    # -- profile access ----------------------------------------------------
    @property
    def active_profile(self) -> Profile:
        if not self.profiles:
            self.profiles = [Profile(name="Default")]
            self.active_profile_index = 0
        self.active_profile_index = max(0, min(self.active_profile_index, len(self.profiles) - 1))
        return self.profiles[self.active_profile_index]

    @property
    def folders(self) -> list[DockFolder]:
        return self.active_profile.folders

    def folder_by_id(self, folder_id: str) -> DockFolder | None:
        return next((f for f in self.folders if f.id == folder_id), None)

    def add_folder(self, folder: DockFolder) -> DockFolder:
        self.folders.append(folder)
        self.touch()
        return folder

    def remove_folder(self, folder_id: str) -> DockFolder | None:
        for index, folder in enumerate(self.folders):
            if folder.id == folder_id:
                self.touch()
                return self.folders.pop(index)
        return None

    def move_folder(self, folder_id: str, delta: int) -> None:
        ids = [f.id for f in self.folders]
        if folder_id not in ids:
            return
        index = ids.index(folder_id)
        target = max(0, min(len(self.folders) - 1, index + delta))
        if target != index:
            self.folders.insert(target, self.folders.pop(index))
            self.touch()

    def add_profile(self, name: str) -> Profile:
        profile = Profile(name=(name or "Profile").strip() or "Profile")
        self.profiles.append(profile)
        self.touch()
        return profile

    def rename_profile(self, index: int, name: str) -> None:
        if 0 <= index < len(self.profiles):
            self.profiles[index].name = (name or "").strip() or self.profiles[index].name
            self.touch()

    def delete_profile(self, index: int) -> bool:
        if len(self.profiles) <= 1 or not (0 <= index < len(self.profiles)):
            return False
        self.profiles.pop(index)
        self.active_profile_index = max(0, min(self.active_profile_index, len(self.profiles) - 1))
        self.touch()
        return True

    def select_profile(self, index: int) -> None:
        if 0 <= index < len(self.profiles):
            self.active_profile_index = index
            self.touch()

    def touch(self) -> None:
        self.dirty = True
        if self.autosave:
            self.save()

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "active_profile": self.active_profile_index,
            "settings": self.settings.to_dict(),
            "profiles": [p.to_dict() for p in self.profiles],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> "Store":
        store = cls(path=path)
        store.schema = int(data.get("schema") or SCHEMA_VERSION)
        store.settings = Settings.from_dict(data.get("settings") or {})
        profiles = [Profile.from_dict(d) for d in data.get("profiles") or []]
        store.profiles = profiles or [Profile(name="Default")]
        store.active_profile_index = max(0, min(int(data.get("active_profile") or 0), len(store.profiles) - 1))
        store.dirty = False
        return store

    # -- disk (SQLite transacional) ----------------------------------------
    def load(self) -> "Store":
        """Load from SQLite database (id=1)."""
        if not self.path.exists():
            return self
        try:
            with sqlite3.connect(self.path) as conn:
                cursor = conn.execute("SELECT payload FROM document WHERE id = 1")
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    loaded = Store.from_dict(data, path=self.path)
                    self.__dict__.update(loaded.__dict__)
            self.last_error = None
        except (sqlite3.Error, ValueError, TypeError) as exc:
            self.last_error = f"{self.path.name}: {exc}"
        return self

    def save(self) -> Path:
        """Atomically write the store payload into the SQLite database."""
        try:
            payload = json.dumps(self.to_dict(), ensure_ascii=False)
            with sqlite3.connect(self.path, isolation_level=None) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO document (id, payload) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                    (payload,)
                )
                conn.execute("COMMIT")
            
            self.dirty = False
            self.last_saved_at = time.time()
            self.last_error = None
        except sqlite3.Error as exc:
            raise StoreError(f"could not write {self.path}: {exc}") from exc
        return self.path

    def reset(self) -> None:
        self.schema = SCHEMA_VERSION
        self.settings = Settings()
        self.profiles = [Profile(name="Default")]
        self.active_profile_index = 0
        self.dirty = True


def default_store() -> Store:
    paths.ensure_dirs()
    return Store().load()