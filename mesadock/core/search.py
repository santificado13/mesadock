"""Quick search over every item of every dock. Pure logic, no Tk."""
from __future__ import annotations

import unicodedata
from typing import Iterable, NamedTuple


class Hit(NamedTuple):
    score: int
    dock: object   # DockFolder
    item: object   # DockItem


def normalise(text: str) -> str:
    """Lower-case, accent-free form: "Área" and "area" compare equal."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _score(name: str, dock_name: str, tokens: list[str]) -> int:
    """0 when a token is missing; higher is better."""
    words = name.replace("_", " ").replace("-", " ").replace(".", " ").split()
    total = 0
    for token in tokens:
        if name.startswith(token):
            total += 100
        elif any(word.startswith(token) for word in words):
            total += 60
        elif token in name:
            total += 30
        elif token in dock_name:
            total += 10
        else:
            return 0
    return total


def search(query: str, docks: Iterable, limit: int = 8) -> list[Hit]:
    """Best matches for ``query`` among the items of ``docks``.

    Every word of the query must appear in the item name (or the dock name).
    An empty query lists nothing: the box starts clean.
    """
    tokens = normalise(query).split()
    if not tokens:
        return []
    hits: list[Hit] = []
    for dock in docks:
        dock_name = normalise(getattr(dock, "name", ""))
        for item in getattr(dock, "items", []):
            name = normalise(getattr(item, "name", ""))
            score = _score(name, dock_name, tokens)
            if score:
                # Shorter names win ties: "Chrome" before "Chrome Remote Desktop".
                hits.append(Hit(score * 1000 - len(name), dock, item))
    hits.sort(key=lambda hit: (-hit.score, normalise(getattr(hit.item, "name", ""))))
    return hits[:max(0, limit)]
