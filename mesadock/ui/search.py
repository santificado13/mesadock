"""Quick search: type a few letters, press Enter, the item opens.

A small borderless window in the middle of the screen with one entry and a
result list covering every dock of the active profile. Opened by a global
hotkey (see ui.tray) or from the tray menu; closes on Escape, on launch and
when it loses focus.
"""
from __future__ import annotations

import tkinter as tk

from ..core import search as search_mod
from ..core.i18n import tr
from . import theme
from .images import item_source

WIDTH = 520
ROW_HEIGHT = 44
ICON = 28
MAX_ROWS = 8


class SearchWindow:
    def __init__(self, app) -> None:
        self.app = app
        self.hits: list[search_mod.Hit] = []
        self.selected = 0
        self._photos: list = []
        self._closed = False

        self.window = tk.Toplevel(app.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=theme.BORDER)

        body = tk.Frame(self.window, bg=theme.BG_ELEVATED)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        self.query = tk.StringVar()
        self.entry = tk.Entry(
            body, textvariable=self.query, font=theme.font(14), relief="flat", bd=0,
            bg=theme.BG_ELEVATED, fg=theme.TEXT, insertbackground=theme.TEXT,
        )
        self.entry.pack(fill="x", padx=16, pady=(14, 6))
        self.hint = tk.Label(
            body, text=tr("Type to find a shortcut in any dock"), anchor="w",
            bg=theme.BG_ELEVATED, fg=theme.TEXT_DIM, font=theme.font(9),
        )
        self.hint.pack(fill="x", padx=16, pady=(0, 10))
        self.canvas = tk.Canvas(body, width=WIDTH, height=1, bg=theme.BG_ELEVATED,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")

        self.query.trace_add("write", lambda *_: self._update())
        self.entry.bind("<Escape>", lambda _e: self.close())
        self.entry.bind("<Return>", lambda _e: self._launch())
        self.entry.bind("<Down>", lambda _e: self._move(1))
        self.entry.bind("<Up>", lambda _e: self._move(-1))
        self.entry.bind("<Tab>", lambda _e: self._move(1))
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Motion>", self._hover)
        self.window.bind("<FocusOut>", self._focus_out)

        self._place()
        self._update()
        self.window.after(10, self._grab_focus)

    # -- window ------------------------------------------------------------
    def _place(self) -> None:
        try:
            pointer = self.app.root.winfo_pointerxy()
            left, top, right, bottom = self.app.monitor_for(pointer).rect
        except Exception:
            left, top = 0, 0
            right, bottom = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
        x = left + (right - left - WIDTH) // 2
        y = top + int((bottom - top) * 0.24)
        self.window.geometry("+" + str(int(x)) + "+" + str(int(y)))

    def _grab_focus(self) -> None:
        if self._closed:
            return
        try:
            self.window.lift()
            self.window.focus_force()
            self.entry.focus_set()
        except tk.TclError:
            return
        self._focus_tries = getattr(self, "_focus_tries", 0) + 1
        self.window.after(300, self._check_focus)

    def _has_focus(self) -> bool:
        try:
            focused = self.window.focus_displayof()
            return focused is not None and focused.winfo_toplevel() is self.window
        except (tk.TclError, KeyError):
            return False

    def _check_focus(self) -> None:
        """Windows may refuse focus_force; without focus the box cannot be typed
        in and never gets a FocusOut to close it, so retry and then give up."""
        if self._closed or self._has_focus():
            return
        if self._focus_tries < 3:
            self._grab_focus()
        else:
            self.close()

    def _focus_out(self, _event=None) -> None:
        # Focus moves between the window and its entry while it opens; only close
        # when it really went to another application.
        self.window.after(120, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        if self._closed:
            return
        # Focus on another MesaDock window (the Manager, a dock) counts as gone too.
        if not self._has_focus():
            self.close()

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        if self.app.search is self:
            self.app.search = None

    # -- results -----------------------------------------------------------
    def _update(self) -> None:
        text = self.query.get()
        self.hits = search_mod.search(text, self.app.store.folders, MAX_ROWS)
        self.selected = 0
        if not text.strip():
            self.hint.configure(text=tr("Type to find a shortcut in any dock"))
        elif not self.hits:
            self.hint.configure(text=tr("Nothing found"))
        else:
            self.hint.configure(text=tr("Enter opens  ·  ↑ ↓ choose  ·  Esc closes"))
        self._draw()

    def _draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self._photos = []
        canvas.configure(height=max(1, len(self.hits) * ROW_HEIGHT + (8 if self.hits else 0)))
        for row, hit in enumerate(self.hits):
            top = row * ROW_HEIGHT
            if row == self.selected:
                theme.rounded_rect(canvas, 8, top + 2, WIDTH - 8, top + ROW_HEIGHT - 2, radius=8,
                                   fill=theme.ACCENT_SOFT, outline="")
            try:
                photo = self.app.images.photo(item_source(hit.item), ICON)
                self._photos.append(photo)
                canvas.create_image(32, top + ROW_HEIGHT // 2, image=photo)
            except Exception:
                pass
            canvas.create_text(58, top + ROW_HEIGHT // 2, text=_clip(hit.item.name, 40), anchor="w",
                               fill=theme.TEXT, font=theme.font(11))
            canvas.create_text(WIDTH - 20, top + ROW_HEIGHT // 2, text=_clip(hit.dock.name, 22), anchor="e",
                               fill=theme.TEXT_DIM, font=theme.font(9))

    def _row_at(self, y: int) -> int | None:
        row = int(y // ROW_HEIGHT)
        return row if 0 <= row < len(self.hits) else None

    def _hover(self, event) -> None:
        row = self._row_at(event.y)
        if row is not None and row != self.selected:
            self.selected = row
            self._draw()

    def _click(self, event) -> None:
        row = self._row_at(event.y)
        if row is not None:
            self.selected = row
            self._launch()

    def _move(self, delta: int) -> str:
        if self.hits:
            self.selected = (self.selected + delta) % len(self.hits)
            self._draw()
        return "break"

    def _launch(self) -> str:
        if self.hits:
            hit = self.hits[self.selected]
            self.close()
            self.app.launch_item(hit.dock, hit.item)
        return "break"


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"
