"""Plain data model for docks, items, settings and profiles.

Refactored to use Pydantic for automatic validation and serialization.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, List, Optional, Tuple
from pydantic import BaseModel, Field, model_validator

# --- allowed values -------------------------------------------------------
ITEM_KINDS = ("shortcut", "file", "folder", "url", "app")
DOCK_STYLES = ("grid", "column", "row", "fan", "ring")
DOCK_STYLE_LABELS = {
    "grid": "Grid",
    "column": "Column",
    "row": "Row",
    "fan": "Fan",
    "ring": "Ring",
}
OPEN_TRIGGERS = ("hover", "click")
ARCHIVE_MODES = ("move", "copy")
PANEL_BACKGROUNDS = ("translucent", "solid")
PANEL_THEMES = ("dark", "light", "auto")


def new_id(prefix: str = "") -> str:
    """Short, collision-safe identifier."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


class DockItem(BaseModel):
    """One entry of a dock: a shortcut, file, folder or web link."""
    name: str
    kind: str = "shortcut"
    path: str = ""
    target: str = ""
    args: str = ""
    icon: str = ""
    archived_from: str = ""
    id: str = Field(default_factory=lambda: new_id("i_"))
    added_at: float = Field(default_factory=_now)

    @model_validator(mode='after')
    def validate_item(self) -> 'DockItem':
        if self.kind not in ITEM_KINDS:
            self.kind = "file"
        self.name = (self.name or "").strip() or "Untitled"
        if not self.path and self.target:
            self.path = self.target
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DockItem":
        # Evitar sobreposição de id/added_at se não existirem no json original
        return cls(**{k: v for k, v in data.items() if v is not None})


class DockFolder(BaseModel):
    """A dock: one collapsed desktop icon that expands into a panel of items."""
    name: str = "New dock"
    style: str = "ring"
    icon: str = ""
    items: List[DockItem] = Field(default_factory=list)
    position: Optional[Tuple[int, int]] = None
    icon_size: int = 64
    show_labels: bool = True
    id: str = Field(default_factory=lambda: new_id("f_"))
    created_at: float = Field(default_factory=_now)

    @model_validator(mode='after')
    def validate_folder(self) -> 'DockFolder':
        if self.style not in DOCK_STYLES:
            self.style = "grid"
        self.name = (self.name or "").strip() or "New dock"
        self.icon_size = max(32, min(160, int(self.icon_size or 64)))
        if self.position is not None:
            self.position = (int(self.position[0]), int(self.position[1]))
        return self

    def add_item(self, item: DockItem) -> DockItem:
        self.items.append(item)
        return item

    def item_by_id(self, item_id: str) -> Optional[DockItem]:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def remove_item(self, item_id: str) -> Optional[DockItem]:
        for index, item in enumerate(self.items):
            if item.id == item_id:
                return self.items.pop(index)
        return None

    def move_item(self, item_id: str, delta: int) -> None:
        ids = [i.id for i in self.items]
        if item_id not in ids:
            return
        from_index = ids.index(item_id)
        to_index = max(0, min(len(self.items) - 1, from_index + delta))
        if to_index != from_index:
            self.items.insert(to_index, self.items.pop(from_index))

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DockFolder":
        return cls(**{k: v for k, v in data.items() if v is not None})


class Settings(BaseModel):
    """Global preferences (Manager -> Settings)."""
    open_trigger: str = "click"
    hover_delay_ms: int = 250
    panel_background: str = "translucent"
    panel_theme: str = "dark"
    panel_opacity: float = 0.92
    icon_size: int = 64
    show_labels: bool = False
    archive_mode: str = "copy"
    animations: bool = True
    auto_start: bool = False
    start_minimized: bool = True
    snap_to_grid: bool = True
    attach_to_desktop: bool = True
    update_check: bool = False

    @model_validator(mode='after')
    def validate_settings(self) -> 'Settings':
        if self.open_trigger not in OPEN_TRIGGERS:
            self.open_trigger = "hover"
        if self.panel_background not in PANEL_BACKGROUNDS:
            self.panel_background = "translucent"
        if self.panel_theme not in PANEL_THEMES:
            self.panel_theme = "dark"
        if self.archive_mode not in ARCHIVE_MODES:
            self.archive_mode = "copy"
        self.panel_opacity = max(0.35, min(1.0, float(self.panel_opacity)))
        self.hover_delay_ms = max(0, min(3000, int(self.hover_delay_ms)))
        self.icon_size = max(32, min(160, int(self.icon_size)))
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {k: v for k, v in (data or {}).items() if k in cls.model_fields}
        return cls(**known)


class Profile(BaseModel):
    """A named desktop setup: its own list of docks."""
    name: str = "Default"
    folders: List[DockFolder] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        return cls(**{k: v for k, v in data.items() if v is not None})