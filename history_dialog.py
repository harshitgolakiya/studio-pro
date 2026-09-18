"""History window: searchable log of past conversions with reproducible settings."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

import customtkinter as ctk

from diagnostics import export_diagnostics
from history import HistoryEntry, clear_history, load_history, search_history, summarize
from utils import format_file_size, open_file_or_folder, reveal_in_file_manager

_MUTED = ("#607181", "#91A0AE")


class HistoryDialog(ctk.CTkToplevel):
    def __init__(self, master: Any, apply_settings: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(master)
        self.title("Conversion History")
        self.geometry("900x560")
        self.minsize(720, 420)
        self.transient(master)

        self._apply_settings = apply_settings
        self._entries: list[HistoryEntry] = []
        self._visible: list[HistoryEntry] = []

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        self.query = ctk.StringVar()
        entry = ctk.CTkEntry(top, textvariable=self.query, placeholder_text="Search by file, format, status, error or date (YYYY-MM-DD)…", height=34)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.query.trace_add("write", lambda *_: self._render())
        self.summary = ctk.CTkLabel(top, text="", text_color=_MUTED, font=ctk.CTkFont(size=11))
        self.summary.pack(side="right")

        cols = ("when", "file", "format", "status", "sizes", "saved")
        self.table = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for col, text, width, anchor in (
            ("when", "When", 130, "w"),
            ("file", "File", 260, "w"),
            ("format", "Target", 110, "w"),
            ("status", "Status", 110, "w"),
            ("sizes", "Original → Output", 150, "e"),
            ("saved", "Saved", 70, "e"),
        ):
            self.table.heading(col, text=text)
            self.table.column(col, width=width, anchor=anchor, stretch=col == "file")
        self.table.pack(fill="both", expand=True, padx=12, pady=4)
        self.table.bind("<<TreeviewSelect>>", lambda _e: self._selection_changed())
        self.table.bind("<Double-1>", lambda _e: self._open_output())

        self.detail = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=860, text_color=_MUTED, font=ctk.CTkFont(size=11))
        self.detail.pack(fill="x", padx=18, pady=(2, 6))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 14))
        self.reapply_btn = ctk.CTkButton(actions, text="Re-apply settings", width=140, height=30, state="disabled", command=self._reapply)
        self.reapply_btn.pack(side="left", padx=(0, 6))
        self.open_btn = ctk.CTkButton(actions, text="Open output", width=110, height=30, fg_color="transparent", border_width=1, state="disabled", command=self._open_output)
        self.open_btn.pack(side="left", padx=(0, 6))
        self.reveal_btn = ctk.CTkButton(actions, text="Reveal", width=80, height=30, fg_color="transparent", border_width=1, state="disabled", command=self._reveal_output)
        self.reveal_btn.pack(side="left")
        ctk.CTkButton(actions, text="Clear history", width=110, height=30, fg_color="transparent", border_width=1, command=self._clear).pack(side="right")
        ctk.CTkButton(actions, text="Export diagnostics…", width=150, height=30, fg_color="transparent", border_width=1, command=self._export_diagnostics).pack(side="right", padx=(0, 6))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.reload()
        entry.focus_set()

    def reload(self) -> None:
        self._entries = load_history()
        self._render()

    def _render(self) -> None:
        self.table.delete(*self.table.get_children())
        self._visible = search_history(self._entries, self.query.get())
        for idx, e in enumerate(self._visible):
            when = e.when.astimezone().strftime("%Y-%m-%d %H:%M") if e.timestamp else ""
            sizes = f"{format_file_size(e.original_size)} → {format_file_size(e.output_size)}" if e.output_size else format_file_size(e.original_size)
            status = e.status if e.status != "Failed" else f"Failed: {e.error[:40]}"
            self.table.insert("", "end", iid=str(idx), values=(when, e.source_name, e.target_format, status, sizes, e.saved))
        s = summarize(self._visible)
        self.summary.configure(text=f"{s['items']} items · {s['batches']} batches · {s['completed']} completed · {s['failed']} failed · {format_file_size(s['bytes_saved'])} saved")
        self._selection_changed()

    def _selected(self) -> HistoryEntry | None:
        sel = self.table.selection()
        if not sel:
            return None
        try:
            return self._visible[int(sel[0])]
        except (ValueError, IndexError):
            return None

    def _selection_changed(self) -> None:
        e = self._selected()
        has_output = bool(e and e.output and Path(e.output).exists())
        self.reapply_btn.configure(state="normal" if e else "disabled")
        self.open_btn.configure(state="normal" if has_output else "disabled")
        self.reveal_btn.configure(state="normal" if has_output else "disabled")
        if not e:
            self.detail.configure(text="")
            return
        s = e.settings
        bits = [f"{e.source}", f"→ {e.output or '(no output)'}"]
        if e.error:
            bits.append(f"Error: {e.error}")
        opts = [f"quality {s.get('quality')}"]
        if s.get("lossless"):
            opts.append("lossless")
        if s.get("enable_resize"):
            opts.append(f"max {s.get('max_dimension_text')}px")
        if s.get("enable_target_size"):
            opts.append(f"target {s.get('target_size_val')} {s.get('target_size_unit')}")
        if s.get("enable_watermark"):
            opts.append("watermark")
        if s.get("strip_metadata"):
            opts.append("strip metadata")
        bits.append("Settings: " + ", ".join(opts))
        self.detail.configure(text="\n".join(bits))

    def _reapply(self) -> None:
        e = self._selected()
        if e is None:
            return
        settings = dict(e.settings)
        settings["target_format"] = e.target_format or settings.get("target_format", "WEBP")
        self._apply_settings(settings)
        self.destroy()

    def _open_output(self) -> None:
        e = self._selected()
        if e and e.output and Path(e.output).exists():
            open_file_or_folder(Path(e.output))

    def _reveal_output(self) -> None:
        e = self._selected()
        if e and e.output and Path(e.output).exists():
            reveal_in_file_manager(Path(e.output))

    def _clear(self) -> None:
        if messagebox.askyesno("Clear history?", "Delete the entire conversion history? This can't be undone.", parent=self):
            clear_history()
            self.reload()

    def _export_diagnostics(self) -> None:
        folder = filedialog.askdirectory(title="Save diagnostics bundle to…", parent=self)
        if not folder:
            return
        try:
            out = export_diagnostics(Path(folder))
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        messagebox.showinfo("Diagnostics exported", f"Saved {out.name}\n\nThe bundle contains system info, redacted settings, recent history and logs.", parent=self)
        reveal_in_file_manager(out)
