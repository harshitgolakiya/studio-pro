from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from font_loader import DISPLAY_FONT
from utils import open_file_or_folder
from watch_folder import FolderWatcher


class WatchFolderDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        watcher: FolderWatcher | None = None,
        on_watcher_changed: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.watcher = watcher
        self.on_watcher_changed = on_watcher_changed
        self._closed = False

        self.title("Auto-Watch Folder Pipeline")
        self.geometry("640x520")
        self.minsize(560, 440)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        default_watch = str(Path.home() / "Pictures")
        default_out = str(Path.home() / "Pictures" / "optimized")

        if self.watcher and self.watcher.is_running:
            default_watch = str(self.watcher.watch_dir)
            default_out = str(self.watcher.output_dir)

        self.watch_dir_var = tk.StringVar(value=default_watch)
        self.output_dir_var = tk.StringVar(value=default_out)
        self.target_format_var = tk.StringVar(value="WEBP")
        self.quality_var = tk.IntVar(value=80)
        self.status_indicator = tk.StringVar(
            value="🟢 Active Monitoring" if (self.watcher and self.watcher.is_running) else "⚪ Monitoring Inactive"
        )

        self._build_ui()
        self.grab_set()

        if self.watcher and self.watcher.is_running:
            # Reopening the dialog on an already-running watcher: rebind its
            # event callback to *this* dialog's log box, otherwise the
            # watcher keeps reporting into a destroyed prior dialog instance.
            self.watcher.on_event = self._watcher_event
            self._log(f"Reattached to active monitoring: {self.watcher.watch_dir.name}")

    def _build_ui(self) -> None:
        self.configure(fg_color=("#f8f9fa", "#1a1d20"))

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # Header
        ctk.CTkLabel(
            container,
            text="AUTO-WATCH FOLDER PIPELINE",
            fg_color="#059669",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=6,
            width=210,
            height=24,
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            container,
            text="Automated Background Compression",
            font=ctk.CTkFont(family=DISPLAY_FONT, size=19, weight="bold"),
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            container,
            text="Automatically converts any images or videos dropped into the watch folder.",
            font=ctk.CTkFont(size=11),
            text_color=("#667085", "#98a2b3"),
        ).pack(pady=(0, 14))

        # Config Card
        card = ctk.CTkFrame(
            container,
            fg_color=("#ffffff", "#191c20"),
            corner_radius=10,
            border_width=1,
            border_color=("#eaecf0", "#344054"),
        )
        card.pack(fill="x", pady=(0, 12))

        # Watch Directory
        r1 = ctk.CTkFrame(card, fg_color="transparent")
        r1.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(r1, text="Watch Folder:", font=ctk.CTkFont(size=11, weight="bold"), width=90, anchor="w").pack(side="left")
        ctk.CTkEntry(r1, textvariable=self.watch_dir_var, height=28).pack(side="left", fill="x", expand=True, padx=(4, 6))
        ctk.CTkButton(r1, text="Browse", width=68, height=28, command=self._browse_watch_dir).pack(side="right")

        # Output Directory
        r2 = ctk.CTkFrame(card, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(6, 10))
        ctk.CTkLabel(r2, text="Output Folder:", font=ctk.CTkFont(size=11, weight="bold"), width=90, anchor="w").pack(side="left")
        ctk.CTkEntry(r2, textvariable=self.output_dir_var, height=28).pack(side="left", fill="x", expand=True, padx=(4, 6))
        ctk.CTkButton(r2, text="Browse", width=68, height=28, command=self._browse_output_dir).pack(side="right")

        # Format & Quality
        r3 = ctk.CTkFrame(card, fg_color="transparent")
        r3.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(r3, text="Target Format:", font=ctk.CTkFont(size=11, weight="bold"), width=90, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            r3,
            variable=self.target_format_var,
            values=["WEBP", "JPG", "PNG", "MP4", "WebM"],
            width=100,
            height=26,
        ).pack(side="left", padx=(4, 16))

        ctk.CTkLabel(r3, text="Quality:", font=ctk.CTkFont(size=11, weight="bold"), width=50, anchor="w").pack(side="left")
        ctk.CTkSlider(r3, from_=1, to=100, variable=self.quality_var, width=140).pack(side="left", padx=4)

        # Status & Controls bar
        status_bar = ctk.CTkFrame(container, fg_color="transparent")
        status_bar.pack(fill="x", pady=(0, 8))

        self.status_label = ctk.CTkLabel(
            status_bar,
            textvariable=self.status_indicator,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#16a34a" if (self.watcher and self.watcher.is_running) else "#667085",
        )
        self.status_label.pack(side="left")

        is_run = self.watcher and self.watcher.is_running
        self.toggle_btn = ctk.CTkButton(
            status_bar,
            text="Stop Monitoring" if is_run else "▶ Start Monitoring",
            fg_color="#dc2626" if is_run else "#16a34a",
            hover_color="#b91c1c" if is_run else "#15803d",
            font=ctk.CTkFont(weight="bold"),
            height=30,
            command=self._toggle_monitoring,
        )
        self.toggle_btn.pack(side="right")

        # Log Box
        ctk.CTkLabel(container, text="Pipeline Activity Log:", font=ctk.CTkFont(size=11, weight="bold"), anchor="w").pack(fill="x", pady=(0, 4))
        self.log_box = ctk.CTkTextbox(container, height=140, font=ctk.CTkFont(family="Consolas", size=10))
        self.log_box.pack(fill="both", expand=True, pady=(0, 10))

        # Bottom Bar
        bottom = ctk.CTkFrame(container, fg_color="transparent")
        bottom.pack(fill="x", side="bottom")

        ctk.CTkButton(
            bottom,
            text="Open Output Folder",
            height=32,
            command=lambda: open_file_or_folder(Path(self.output_dir_var.get())),
        ).pack(side="left")

        ctk.CTkButton(
            bottom,
            text="Close",
            width=80,
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=("#d0d5dd", "#475467"),
            text_color=("#344054", "#f2f4f7"),
            command=self._on_close_request,
        ).pack(side="right")

    def _on_close_request(self) -> None:
        # The watcher intentionally keeps running in the background after the
        # dialog closes (main.py retains it as `active_watcher`); just stop
        # routing its events into this soon-to-be-destroyed window.
        if self.watcher:
            self.watcher.on_event = None
        self._closed = True
        self.destroy()

    def _watcher_event(self, level: str, msg: str) -> None:
        self.after(0, lambda: self._log(msg))

    def _browse_watch_dir(self) -> None:
        folder = filedialog.askdirectory(title="Select Folder to Watch")
        if folder:
            self.watch_dir_var.set(folder)
            self.output_dir_var.set(str(Path(folder) / "optimized"))

    def _browse_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_dir_var.set(folder)

    def _log(self, text: str) -> None:
        if self._closed:
            return
        try:
            self.log_box.insert("end", f"{text}\n")
            self.log_box.see("end")
        except tk.TclError:
            pass

    def _toggle_monitoring(self) -> None:
        if self.watcher and self.watcher.is_running:
            self.watcher.stop()
            self.status_indicator.set("⚪ Monitoring Inactive")
            self.status_label.configure(text_color="#667085")
            self.toggle_btn.configure(text="▶ Start Monitoring", fg_color="#16a34a", hover_color="#15803d")
            self._log("Stopped monitoring.")
        else:
            w_dir = Path(self.watch_dir_var.get().strip())
            o_dir = Path(self.output_dir_var.get().strip())
            if not w_dir.is_dir():
                messagebox.showerror("Invalid Folder", "Watch folder does not exist.")
                return

            self.watcher = FolderWatcher(
                watch_dir=w_dir,
                output_dir=o_dir,
                target_format=self.target_format_var.get(),
                quality=self.quality_var.get(),
                on_event=self._watcher_event,
            )
            self.watcher.start()
            self.status_indicator.set("🟢 Active Monitoring")
            self.status_label.configure(text_color="#16a34a")
            self.toggle_btn.configure(text="Stop Monitoring", fg_color="#dc2626", hover_color="#b91c1c")
            self._log(f"Started monitoring: {w_dir.name} ➔ {o_dir.name}")

        if callable(self.on_watcher_changed):
            self.on_watcher_changed(self.watcher)
