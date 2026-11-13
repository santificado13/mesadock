"""Plain data model for docks, items, settings and profiles.

Every object is a dataclass with lossless to_dict/from_dict round-trips so
profiles can be stored in JSON and carried between versions.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class DockItem:
    """One entry of a dock: a shortcut, file, folder or web link."""

    name: str
    kind: str = "shortcut"
    path: str = ""            # absolute path of the copy MesaDock owns
    target: str = ""          # resolved target (exe, document, folder, url)
    args: str = ""
    icon: str = ""            # custom icon override (absolute image path)
    archived_from: str = ""   # original desktop path when the original was moved away
    id: str = field(default_factory=lambda: new_id("i_"))
    added_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.kind not in ITEM_KINDS:
            self.kind = "file"
        self.name = (self.name or "").strip() or "Untitled"
        if not self.path and self.target:
            self.path = self.target

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "target": self.target,
            "args": self.args,
            "icon": self.icon,
            "archived_from": self.archived_from,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DockItem":
        return cls(
            id=str(data.get("id") or new_id("i_")),
            kind=str(data.get("kind") or "shortcut"),
            name=str(data.get("name") or "Untitled"),
            path=str(data.get("path") or ""),
            target=str(data.get("target") or ""),
            args=str(data.get("args") or ""),
            icon=str(data.get("icon") or ""),
            archived_from=str(data.get("archived_from") or ""),
            added_at=float(data.get("added_at") or _now()),
        )


@dataclass
class DockFolder:
    """A dock: one collapsed desktop icon that expands into a panel of items."""

    name: str = "New dock"
    style: str = "grid"
    icon: str = ""                           # custom icon image path
    items: list[DockItem] = field(default_factory=list)
    position: tuple[int, int] | None = None  # desktop pixel position of the collapsed icon
    icon_size: int = 64
    show_labels: bool = False
    id: str = field(default_factory=lambda: new_id("f_"))
    created_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.style not in DOCK_STYLES:
            self.style = "grid"
        self.name = (self.name or "").strip() or "New dock"
        self.icon_size = max(32, min(160, int(self.icon_size or 64)))
        if self.position is not None:
            self.position = (int(self.position[0]), int(self.position[1]))

    # -- item helpers ------------------------------------------------------
    def add_item(self, item: DockItem) -> DockItem:
        self.items.append(item)
        return item

    def item_by_id(self, item_id: str) -> DockItem | None:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def remove_item(self, item_id: str) -> DockItem | None:
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

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "style": self.style,
            "icon": self.icon,
            "items": [i.to_dict() for i in self.items],
            "position": list(self.position) if self.position else None,
            "icon_size": self.icon_size,
            "show_labels": self.show_labels,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DockFolder":
        pos = data.get("position")
        return cls(
            id=str(data.get("id") or new_id("f_")),
            name=str(data.get("name") or "New dock"),
            style=str(data.get("style") or "grid"),
            icon=str(data.get("icon") or ""),
            items=[DockItem.from_dict(d) for d in data.get("items") or []],
            position=(int(pos[0]), int(pos[1])) if pos else None,
            icon_size=int(data.get("icon_size") or 64),
            show_labels=bool(data.get("show_labels", False)),
            created_at=float(data.get("created_at") or _now()),
        )


@dataclass
class Settings:
    """Global preferences (Manager -> Settings)."""

    open_trigger: str = "click"            # hover | click
    hover_delay_ms: int = 250
    panel_background: str = "translucent"  # translucent | solid
    panel_theme: str = "dark"              # dark | light | auto
    panel_opacity: float = 0.92
    icon_size: int = 64
    show_labels: bool = False
    archive_mode: str = "move"             # move | copy
    animations: bool = True
    auto_start: bool = False
    start_minimized: bool = True
    snap_to_grid: bool = True
    attach_to_desktop: bool = True         # keep docks/panels on the desktop layer
    update_check: bool = False

    def __post_init__(self) -> None:
        if self.open_trigger not in OPEN_TRIGGERS:
            self.open_trigger = "hover"
        if self.panel_background not in PANEL_BACKGROUNDS:
            self.panel_background = "translucent"
        if self.panel_theme not in PANEL_THEMES:
            self.panel_theme = "dark"
        if self.archive_mode not in ARCHIVE_MODES:
            self.archive_mode = "move"
        self.panel_opacity = max(0.35, min(1.0, float(self.panel_opacity)))
        self.hover_delay_ms = max(0, min(3000, int(self.hover_delay_ms)))
        self.icon_size = max(32, min(160, int(self.icon_size)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_trigger": self.open_trigger,
            "hover_delay_ms": self.hover_delay_ms,
            "panel_background": self.panel_background,
            "panel_theme": self.panel_theme,
            "panel_opacity": self.panel_opacity,
            "icon_size": self.icon_size,
            "show_labels": self.show_labels,
            "archive_mode": self.archive_mode,
            "animations": self.animations,
            "auto_start": self.auto_start,
            "start_minimized": self.start_minimized,
            "snap_to_grid": self.snap_to_grid,
            "attach_to_desktop": self.attach_to_desktop,
            "update_check": self.update_check,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Profile:
    """A named desktop setup: its own list of docks."""

    name: str = "Default"
    folders: list[DockFolder] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "folders": [f.to_dict() for f in self.folders]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        return cls(
            name=str(data.get("name") or "Default"),
            folders=[DockFolder.from_dict(d) for d in data.get("folders") or []],
        )
