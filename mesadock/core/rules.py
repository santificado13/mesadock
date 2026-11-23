"""Automatic rules: which dock a new desktop item belongs to.

Each dock may carry a list of name patterns ("*.pdf, relatorio*, .docx"). When a
file or shortcut appears on the desktop while MesaDock runs, the first dock (in
order) with a matching pattern takes it. Pure logic, no Tk and no filesystem.
"""
from __future__ import annotations

import fnmatch
import os
import re
from typing import Iterable

from .search import normalise

_SPLIT = re.compile(r"[,;\n]+")


def parse(text: str) -> list[str]:
    """Patterns of a rules field, trimmed, in order, without duplicates."""
    seen: list[str] = []
    for part in _SPLIT.split(text or ""):
        pattern = part.strip()
        if pattern and pattern not in seen:
            seen.append(pattern)
    return seen


def clean(text: str) -> str:
    """Canonical form stored on the dock: patterns joined by ", "."""
    return ", ".join(parse(text))


def _match(name: str, pattern: str) -> bool:
    """One pattern against a file name, ignoring case and accents.

    - with ``*`` or ``?``: a wildcard match on the whole name, and for shortcuts
      also on the name without ".lnk"/".url" (that is the name people see);
    - starting with a dot (".pdf"): the extension;
    - anything else: text contained in the name.
    """
    name_n, pattern_n = normalise(name), normalise(pattern)
    stem, extension = os.path.splitext(name_n)
    visible = stem if extension in (".lnk", ".url") else name_n
    if "*" in pattern_n or "?" in pattern_n:
        return fnmatch.fnmatchcase(name_n, pattern_n) or fnmatch.fnmatchcase(visible, pattern_n)
    if pattern_n.startswith("."):
        return extension == pattern_n
    return pattern_n in visible


def matches(name: str, patterns: Iterable[str]) -> bool:
    return any(_match(name, pattern) for pattern in patterns)


def pick_dock(name: str, docks: Iterable):
    """First dock whose rules match ``name``; folder docks never take items."""
    for dock in docks:
        if getattr(dock, "portal", ""):
            continue
        patterns = parse(getattr(dock, "rules", ""))
        if patterns and matches(name, patterns):
            return dock
    return None


def any_rules(docks: Iterable) -> bool:
    return any(parse(getattr(dock, "rules", "")) for dock in docks if not getattr(dock, "portal", ""))
