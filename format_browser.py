"""Searchable, categorized output-format browser with capability badges.

The main window keeps its CTkOptionMenu as the source of truth for which
formats are currently offered (it is reconfigured per smart-mode: image,
video, audio, GIF, document). This module only adds a richer way to pick
from that same list, so it takes the option labels as input rather than
owning a format list of its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import customtkinter as ctk

from converter import IMAGE_FORMAT_CAPABILITIES, normalize_output_format


@dataclass(frozen=True)
class FormatEntry:
    label: str
    category: str
    description: str
    badges: tuple[str, ...]

    def search_text(self) -> str:
        return " ".join((self.label, self.category, self.description, *self.badges)).lower()


# Non-image options offered by the main window. Keys are the exact option
# labels used there; the "Extract Audio:" and "Video -> Audio" spellings are
# the same operation surfaced under different smart modes.
MEDIA_FORMAT_CAPABILITIES: dict[str, dict[str, Any]] = {
    "Video: MP4": {"category": "Video", "description": "Universal H.264 video with AAC audio, hardware accelerated where available.", "badges": ("Universal", "Lossy", "Hardware encode", "Metadata")},
    "Video: WebM": {"category": "Video", "description": "VP9 video with Opus audio for modern web streaming.", "badges": ("Web", "Lossy", "Alpha", "Open format")},
    "Video -> Animated WebP": {"category": "Video", "description": "Turn a clip into a compact animated WebP.", "badges": ("Animation", "Alpha", "Web", "Muted")},
    "Video -> GIF": {"category": "Video", "description": "Palette-optimized animated GIF from a clip.", "badges": ("Animation", "Universal", "Indexed", "Muted")},
    "Video -> Audio (MP3)": {"category": "Audio", "description": "Extract the soundtrack as MP3.", "badges": ("Audio only", "Universal", "Lossy")},
    "Extract Audio: MP3": {"category": "Audio", "description": "Extract the soundtrack as MP3.", "badges": ("Audio only", "Universal", "Lossy")},
    "Extract Audio: AAC": {"category": "Audio", "description": "Extract the soundtrack as AAC in an M4A container.", "badges": ("Audio only", "Apple", "Lossy")},
    "Extract Audio: Opus": {"category": "Audio", "description": "Extract the soundtrack as small, high-quality Opus.", "badges": ("Audio only", "Web", "High efficiency")},
    "Extract Audio: WAV": {"category": "Audio", "description": "Extract the soundtrack as uncompressed PCM.", "badges": ("Audio only", "Lossless", "Large files")},
    "Audio: MP3": {"category": "Audio", "description": "Universal lossy audio for players and phones.", "badges": ("Universal", "Lossy", "Metadata")},
    "Audio: AAC": {"category": "Audio", "description": "Efficient lossy audio favoured by Apple devices.", "badges": ("Apple", "Lossy", "Metadata")},
    "Audio: Opus": {"category": "Audio", "description": "Best quality per kilobit for voice and music on the web.", "badges": ("Web", "High efficiency", "Open format")},
    "Audio: WAV": {"category": "Audio", "description": "Uncompressed PCM audio for editing and mastering.", "badges": ("Lossless", "Universal", "Large files")},
    "Document: MD": {"category": "Document", "description": "Clean Markdown extracted from DOCX, PDF, HTML, or TXT.", "badges": ("Text", "Portable", "Editable")},
    "Document: DOCX": {"category": "Document", "description": "Microsoft Word document built from Markdown.", "badges": ("Office", "Editable", "Formatting")},
    "Document: PDF": {"category": "Document", "description": "Fixed-layout PDF rendered from Markdown.", "badges": ("Document", "Portable", "Print")},
    "Document: HTML": {"category": "Document", "description": "Web page rendered from Markdown.", "badges": ("Web", "Editable", "Formatting")},
    "Document: TXT": {"category": "Document", "description": "Plain text with formatting stripped.", "badges": ("Text", "Universal", "Portable")},
}

# Badge -> (fill, text) colours as (light, dark) pairs, grouped by what the
# badge says about the format so alpha/animation/lossless/etc. read
# consistently across the app.
_BADGE_FAMILIES: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "alpha": (("#DBEAFE", "#1E3A5F"), ("#1D4ED8", "#93C5FD")),
    "animation": (("#EDE9FE", "#312E81"), ("#6D28D9", "#C4B5FD")),
    "hdr": (("#FFEDD5", "#7C2D12"), ("#C2410C", "#FDBA74")),
    "lossless": (("#DCFCE7", "#14532D"), ("#15803D", "#86EFAC")),
    "lossy": (("#FEF3C7", "#78350F"), ("#B45309", "#FDE68A")),
    "metadata": (("#E2E8F0", "#1E293B"), ("#334155", "#CBD5E1")),
    "compat": (("#E8F7F4", "#17312E"), ("#0E756B", "#70E1D4")),
    "warning": (("#FEE2E2", "#7F1D1D"), ("#B91C1C", "#FCA5A5")),
}

_BADGE_TO_FAMILY: dict[str, str] = {
    "alpha": "alpha", "transparency": "alpha",
    "animation": "animation", "multi-page": "animation", "multi-size": "animation",
    "hdr": "hdr", "high efficiency": "hdr", "hardware encode": "hdr", "fast": "hdr",
    "lossless": "lossless", "uncompressed": "lossless",
    "lossy": "lossy", "indexed": "lossy", "monochrome": "lossy",
    "metadata": "metadata", "editable": "metadata", "formatting": "metadata", "text": "metadata",
    "large files": "warning", "legacy": "warning", "muted": "warning", "audio only": "warning",
}


def badge_style(badge: str) -> tuple[tuple[str, str], tuple[str, str]]:
    family = _BADGE_TO_FAMILY.get(badge.strip().lower(), "compat")
    return _BADGE_FAMILIES[family]


def describe_format(label: str) -> FormatEntry:
    """Return the catalogue entry for a main-window option label."""
    media = MEDIA_FORMAT_CAPABILITIES.get(label)
    if media:
        return FormatEntry(label, media["category"], media["description"], tuple(media["badges"]))

    image_key = normalize_output_format(label)
    image = IMAGE_FORMAT_CAPABILITIES.get(image_key)
    if image:
        return FormatEntry(label, str(image["category"]), str(image["description"]), tuple(str(b) for b in image["badges"]))

    return FormatEntry(label, "Other", "", ())


def build_catalog(options: Sequence[str]) -> list[FormatEntry]:
    return [describe_format(label) for label in options]


def filter_catalog(entries: Sequence[FormatEntry], query: str) -> list[FormatEntry]:
    """Keep entries matching every whitespace-separated word of the query."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return list(entries)
    return [e for e in entries if all(w in e.search_text() for w in words)]


def group_by_category(entries: Sequence[FormatEntry]) -> list[tuple[str, list[FormatEntry]]]:
    """Group entries by category, preserving first-seen order of both."""
    groups: dict[str, list[FormatEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.category, []).append(entry)
    return list(groups.items())


def render_capability_badges(parent: Any, badges: Sequence[str], size: int = 9) -> None:
    for badge in badges:
        fill, text = badge_style(badge)
        ctk.CTkLabel(
            parent,
            text=badge,
            height=20,
            corner_radius=5,
            padx=7,
            fg_color=fill,
            text_color=text,
            font=ctk.CTkFont(size=size, weight="bold"),
        ).pack(side="left", padx=(0, 4))


class FormatBrowserDialog(ctk.CTkToplevel):
    """Modal picker: type to filter, arrow keys to move, Enter to choose."""

    def __init__(
        self,
        master: Any,
        options: Sequence[str],
        current: str,
        on_select: Callable[[str], None],
    ) -> None:
        super().__init__(master)
        self.title("Choose Output Format")
        self.geometry("640x560")
        self.minsize(520, 420)
        self.transient(master)

        self._entries = build_catalog(options)
        self._on_select = on_select
        self._visible: list[FormatEntry] = []
        self._rows: dict[str, ctk.CTkFrame] = {}
        self._cursor = -1
        self._current = current
        self._row_fill = ("#FFFFFF", "#11161D")
        self._row_hover = ("#E9EEF3", "#1A2029")
        self._row_active = ("#D8F3EF", "#123A36")

        self.query = ctk.StringVar()
        search = ctk.CTkEntry(
            self,
            textvariable=self.query,
            placeholder_text="Search formats, categories, or capabilities (e.g. alpha, lossless, animation)",
            height=36,
        )
        search.pack(fill="x", padx=16, pady=(16, 8))
        self.query.trace_add("write", lambda *_: self._render())

        self.count_label = ctk.CTkLabel(self, text="", anchor="w", font=ctk.CTkFont(size=10), text_color=("#607181", "#91A0AE"))
        self.count_label.pack(fill="x", padx=18, pady=(0, 4))

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        hint = ctk.CTkLabel(
            self,
            text="↑ ↓ to move   ·   Enter to choose   ·   Esc to close",
            font=ctk.CTkFont(size=10),
            text_color=("#607181", "#91A0AE"),
        )
        hint.pack(pady=(0, 10))

        self.bind("<Up>", lambda _e: self._move(-1))
        self.bind("<Down>", lambda _e: self._move(1))
        self.bind("<Return>", lambda _e: self._choose_cursor())
        self.bind("<Escape>", lambda _e: self.destroy())

        self._render()
        search.focus_set()
        # Deferred: grabbing before the window is mapped fails on some
        # platforms. Cancelled in destroy() so a fast close can't fire it
        # against a dead window.
        self._grab_after_id = self.after(50, self._grab)

    def _grab(self) -> None:
        self._grab_after_id = None
        # Only grab a window that is actually on screen. On Tk 8.6/macOS,
        # grabbing one that can never become viewable (e.g. transient to a
        # withdrawn parent) makes update() spin forever.
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

    # -- rendering -------------------------------------------------------

    def _render(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._rows.clear()

        self._visible = filter_catalog(self._entries, self.query.get())
        total = len(self._entries)
        shown = len(self._visible)
        self.count_label.configure(
            text=f"{shown} of {total} formats" if shown != total else f"{total} formats"
        )

        if not self._visible:
            ctk.CTkLabel(
                self.list_frame,
                text="No formats match. Try a capability like “alpha” or a category like “video”.",
                text_color=("#607181", "#91A0AE"),
            ).pack(pady=24)
            self._cursor = -1
            return

        for category, entries in group_by_category(self._visible):
            ctk.CTkLabel(
                self.list_frame,
                text=category.upper(),
                anchor="w",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("#607181", "#91A0AE"),
            ).pack(fill="x", padx=8, pady=(10, 2))
            for entry in entries:
                self._rows[entry.label] = self._build_row(entry)

        labels = [e.label for e in self._visible]
        self._cursor = labels.index(self._current) if self._current in labels else 0
        self._highlight()

    def _build_row(self, entry: FormatEntry) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.list_frame, corner_radius=8, fg_color=self._row_fill)
        row.pack(fill="x", padx=6, pady=2)

        head = ctk.CTkFrame(row, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(7, 0))
        ctk.CTkLabel(head, text=entry.label, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        if entry.badges:
            badges = ctk.CTkFrame(head, fg_color="transparent")
            badges.pack(side="right")
            render_capability_badges(badges, entry.badges)

        if entry.description:
            ctk.CTkLabel(
                row,
                text=entry.description,
                anchor="w",
                justify="left",
                wraplength=560,
                font=ctk.CTkFont(size=11),
                text_color=("#607181", "#91A0AE"),
            ).pack(fill="x", padx=10, pady=(0, 7))
        else:
            ctk.CTkFrame(row, fg_color="transparent", height=6).pack()

        self._bind_recursive(row, "<Button-1>", lambda _e, label=entry.label: self._choose(label))
        # <Motion>, not <Enter>: Enter fires when the window opens beneath a
        # stationary pointer and would steal the highlight from the current
        # selection before the user has touched anything.
        self._bind_recursive(row, "<Motion>", lambda _e, label=entry.label: self._hover(label))
        return row

    def _bind_recursive(self, widget: Any, sequence: str, handler: Callable[[Any], None]) -> None:
        widget.bind(sequence, handler)
        for child in widget.winfo_children():
            self._bind_recursive(child, sequence, handler)

    def _highlight(self) -> None:
        for index, entry in enumerate(self._visible):
            row = self._rows.get(entry.label)
            if row is None:
                continue
            row.configure(fg_color=self._row_active if index == self._cursor else self._row_fill)

    # -- interaction -----------------------------------------------------

    def _hover(self, label: str) -> None:
        labels = [e.label for e in self._visible]
        if label in labels:
            self._cursor = labels.index(label)
            self._highlight()

    def _move(self, delta: int) -> None:
        if not self._visible:
            return
        self._cursor = max(0, min(len(self._visible) - 1, self._cursor + delta))
        self._highlight()

    def _choose_cursor(self) -> None:
        if 0 <= self._cursor < len(self._visible):
            self._choose(self._visible[self._cursor].label)

    def _choose(self, label: str) -> None:
        try:
            self._on_select(label)
        finally:
            self.destroy()
