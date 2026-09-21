"""Command palette (Ctrl+K): type-to-filter list of every major action."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import customtkinter as ctk

_MUTED = ("#607181", "#91A0AE")
_ROW = ("#FFFFFF", "#11161D")
_ROW_ACTIVE = ("#D8F3EF", "#123A36")


@dataclass(frozen=True)
class PaletteAction:
    label: str
    run: Callable[[], None]
    category: str = "General"
    shortcut: str = ""
    keywords: str = ""
    enabled: Callable[[], bool] = lambda: True

    def search_text(self) -> str:
        return " ".join((self.label, self.category, self.shortcut, self.keywords)).lower()


def filter_actions(actions: Sequence[PaletteAction], query: str) -> list[PaletteAction]:
    """Every whitespace-separated word must appear; label-prefix matches rank first."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return list(actions)
    hits = [a for a in actions if all(w in a.search_text() for w in words)]
    first = words[0]
    return sorted(hits, key=lambda a: (not a.label.lower().startswith(first), a.label.lower()))


class CommandPalette(ctk.CTkToplevel):
    def __init__(self, master: Any, actions: Sequence[PaletteAction]) -> None:
        super().__init__(master)
        self.title("Command Palette")
        self.geometry("560x440")
        self.minsize(420, 300)
        self.transient(master)
        self.overrideredirect(False)

        self._actions = list(actions)
        self._visible: list[PaletteAction] = []
        self._rows: dict[int, ctk.CTkFrame] = {}
        self._cursor = 0

        self.query = ctk.StringVar()
        entry = ctk.CTkEntry(self, textvariable=self.query, placeholder_text="Type a command…", height=38, font=ctk.CTkFont(size=14))
        entry.pack(fill="x", padx=12, pady=(12, 6))
        self.query.trace_add("write", lambda *_: self._render())

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        ctk.CTkLabel(self, text="↑ ↓ move   ·   Enter run   ·   Esc close", font=ctk.CTkFont(size=10), text_color=_MUTED).pack(pady=(0, 8))

        self.bind("<Up>", lambda _e: self._move(-1))
        self.bind("<Down>", lambda _e: self._move(1))
        self.bind("<Return>", lambda _e: self.run_cursor())
        self.bind("<Escape>", lambda _e: self.destroy())

        self._render()
        entry.focus_set()
        self._grab_after_id: str | None = self.after(50, self._grab)

    def _grab(self) -> None:
        self._grab_after_id = None
        # See FormatBrowserDialog._grab: never grab a window that isn't viewable.
        if self.winfo_exists() and self.winfo_viewable():
            self.grab_set()

    def destroy(self) -> None:
        pending = getattr(self, "_grab_after_id", None)
        if pending is not None:
            self._grab_after_id = None
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        super().destroy()

    def _render(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._rows.clear()
        self._visible = filter_actions(self._actions, self.query.get())
        if not self._visible:
            ctk.CTkLabel(self.list_frame, text="No matching commands.", text_color=_MUTED).pack(pady=20)
            self._cursor = -1
            return
        last_category = None
        for index, action in enumerate(self._visible):
            if action.category != last_category and not self.query.get().strip():
                ctk.CTkLabel(self.list_frame, text=action.category.upper(), anchor="w", font=ctk.CTkFont(size=10, weight="bold"), text_color=_MUTED).pack(fill="x", padx=8, pady=(8, 2))
                last_category = action.category
            self._rows[index] = self._build_row(index, action)
        self._cursor = 0
        self._highlight()

    def _build_row(self, index: int, action: PaletteAction) -> ctk.CTkFrame:
        enabled = action.enabled()
        row = ctk.CTkFrame(self.list_frame, corner_radius=6, fg_color=_ROW)
        row.pack(fill="x", padx=4, pady=1)
        label = ctk.CTkLabel(row, text=action.label, anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color=None if enabled else _MUTED)
        label.pack(side="left", padx=10, pady=6)
        if action.shortcut:
            ctk.CTkLabel(row, text=action.shortcut, font=ctk.CTkFont(size=10), text_color=_MUTED).pack(side="right", padx=10)
        for widget in (row, *row.winfo_children()):
            widget.bind("<Button-1>", lambda _e, i=index: self._run_index(i))
            widget.bind("<Motion>", lambda _e, i=index: self._set_cursor(i))
        return row

    def _highlight(self) -> None:
        for index, row in self._rows.items():
            row.configure(fg_color=_ROW_ACTIVE if index == self._cursor else _ROW)

    def _set_cursor(self, index: int) -> None:
        if index != self._cursor:
            self._cursor = index
            self._highlight()

    def _move(self, delta: int) -> None:
        if not self._visible:
            return
        self._cursor = max(0, min(len(self._visible) - 1, self._cursor + delta))
        self._highlight()

    def run_cursor(self) -> None:
        self._run_index(self._cursor)

    def _run_index(self, index: int) -> None:
        if not (0 <= index < len(self._visible)):
            return
        action = self._visible[index]
        if not action.enabled():
            return
        self.destroy()
        action.run()
