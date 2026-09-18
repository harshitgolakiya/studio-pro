from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from font_loader import DISPLAY_FONT
from media_engine import (
    extract_video_thumbnail,
    get_media_duration,
    trim_video_lossless,
)
from utils import play_completion_sound


def format_seconds(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins:02d}:{secs:04.1f}"


class VideoTrimmerDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        video_path: Path,
        on_trim_complete: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.video_path = video_path
        self.on_trim_complete = on_trim_complete
        self._closed = False

        self.title(f"Fast Video Trimmer - {video_path.name}")
        self.geometry("560x380")
        self.minsize(500, 340)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self.duration = get_media_duration(video_path) or 60.0
        self.start_val = tk.DoubleVar(value=0.0)
        self.end_val = tk.DoubleVar(value=self.duration)
        self.clip_duration_text = tk.StringVar(
            value=f"Clip Length: {format_seconds(self.duration)} ({self.duration:.1f}s)"
        )

        self._build_ui()
        self.grab_set()

    def _build_ui(self) -> None:
        self.configure(fg_color=("#f8f9fa", "#1a1d20"))

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # Header
        ctk.CTkLabel(
            container,
            text="FAST LOSSLESS VIDEO TRIMMER",
            fg_color="#12877A",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=6,
            width=190,
            height=24,
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            container,
            text=self.video_path.name,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            container,
            text=f"Total Duration: {format_seconds(self.duration)} ({self.duration:.1f}s) • Lossless cut with zero quality loss",
            font=ctk.CTkFont(size=11),
            text_color=("#667085", "#98a2b3"),
        ).pack(pady=(0, 16))

        # Timeline Card
        card = ctk.CTkFrame(
            container,
            fg_color=("#ffffff", "#191c20"),
            corner_radius=10,
            border_width=1,
            border_color=("#eaecf0", "#344054"),
        )
        card.pack(fill="x", pady=(0, 16), padx=4)

        # Start slider row
        r1 = ctk.CTkFrame(card, fg_color="transparent")
        r1.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(r1, text="Start Point:", font=ctk.CTkFont(size=12, weight="bold"), width=80, anchor="w").pack(side="left")
        self.start_slider = ctk.CTkSlider(
            r1,
            from_=0.0,
            to=self.duration,
            variable=self.start_val,
            command=self._on_start_changed,
        )
        self.start_slider.pack(side="left", fill="x", expand=True, padx=8)
        self.start_label = ctk.CTkLabel(r1, text="00:00.0", width=65, font=ctk.CTkFont(family="Consolas", size=11))
        self.start_label.pack(side="right")

        # End slider row
        r2 = ctk.CTkFrame(card, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(6, 12))
        ctk.CTkLabel(r2, text="End Point:", font=ctk.CTkFont(size=12, weight="bold"), width=80, anchor="w").pack(side="left")
        self.end_slider = ctk.CTkSlider(
            r2,
            from_=0.0,
            to=self.duration,
            variable=self.end_val,
            command=self._on_end_changed,
        )
        self.end_slider.pack(side="left", fill="x", expand=True, padx=8)
        self.end_label = ctk.CTkLabel(
            r2,
            text=format_seconds(self.duration),
            width=65,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.end_label.pack(side="right")

        # Clip summary
        ctk.CTkLabel(
            container,
            textvariable=self.clip_duration_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#16a34a",
        ).pack(pady=(0, 16))

        # Action Buttons
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", side="bottom")

        self.frame_btn = ctk.CTkButton(
            btn_frame,
            text="📸 Capture Frame",
            fg_color="#059669",
            hover_color="#047857",
            height=36,
            command=self._do_capture_frame,
        )
        self.frame_btn.pack(side="left")

        self.trim_btn = ctk.CTkButton(
            btn_frame,
            text="⚡ Trim & Add to Queue",
            fg_color="#12877A",
            hover_color="#17A594",
            height=36,
            font=ctk.CTkFont(weight="bold"),
            command=self._do_trim,
        )
        self.trim_btn.pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            height=36,
            width=80,
            fg_color="transparent",
            border_width=1,
            border_color=("#d0d5dd", "#475467"),
            text_color=("#344054", "#f2f4f7"),
            command=self._on_close_request,
        ).pack(side="right")

    def _on_close_request(self) -> None:
        self._closed = True
        self.destroy()

    def _do_capture_frame(self) -> None:
        pos_s = self.start_val.get()
        out_name = f"{self.video_path.stem}_frame_{int(pos_s)}s.webp"
        out_path = self.video_path.parent / out_name

        self.frame_btn.configure(state="disabled", text="Capturing...")

        def worker() -> None:
            try:
                extract_video_thumbnail(self.video_path, out_path, timestamp=pos_s)
                self.after(0, lambda: self._on_capture_success(pos_s, out_path))
            except Exception as exc:
                self.after(0, lambda: self._on_capture_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_capture_success(self, pos_s: float, out_path: Path) -> None:
        if self._closed:
            if self.on_trim_complete and out_path.exists():
                self.on_trim_complete(out_path)
            return
        self.frame_btn.configure(state="normal", text="📸 Capture Frame")
        play_completion_sound()
        if self.on_trim_complete and out_path.exists():
            self.on_trim_complete(out_path)
        messagebox.showinfo(
            "Poster Frame Saved",
            f"Captured frame at {format_seconds(pos_s)}!\n\nSaved to:\n{out_path.name}",
            parent=self,
        )

    def _on_capture_error(self, err_msg: str) -> None:
        if self._closed:
            return
        self.frame_btn.configure(state="normal", text="📸 Capture Frame")
        messagebox.showerror("Capture Error", f"Failed to capture frame:\n{err_msg}", parent=self)

    def _on_start_changed(self, val: float) -> None:
        if val >= self.end_val.get():
            self.start_val.set(max(0.0, self.end_val.get() - 0.5))
        self.start_label.configure(text=format_seconds(self.start_val.get()))
        self._update_clip_length()

    def _on_end_changed(self, val: float) -> None:
        if val <= self.start_val.get():
            self.end_val.set(min(self.duration, self.start_val.get() + 0.5))
        self.end_label.configure(text=format_seconds(self.end_val.get()))
        self._update_clip_length()

    def _update_clip_length(self) -> None:
        diff = max(0.1, self.end_val.get() - self.start_val.get())
        self.clip_duration_text.set(
            f"Clip Length: {format_seconds(diff)} ({diff:.1f}s)"
        )

    def _do_trim(self) -> None:
        start_s = self.start_val.get()
        end_s = self.end_val.get()
        if end_s <= start_s:
            messagebox.showwarning("Invalid Range", "End point must be greater than start point.", parent=self)
            return

        out_name = f"{self.video_path.stem}_trimmed{self.video_path.suffix}"
        out_path = self.video_path.parent / out_name

        self.trim_btn.configure(state="disabled", text="Trimming clip...")

        def worker() -> None:
            try:
                trim_video_lossless(self.video_path, out_path, start_s, end_s)
                self.after(0, lambda: self._on_trim_success(out_path))
            except Exception as exc:
                self.after(0, lambda: self._on_trim_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_trim_success(self, out_path: Path) -> None:
        if self._closed:
            if self.on_trim_complete and out_path.exists():
                self.on_trim_complete(out_path)
            return
        play_completion_sound()
        if self.on_trim_complete and out_path.exists():
            self.on_trim_complete(out_path)
        messagebox.showinfo(
            "Trim Complete", f"Successfully cut clip in <1s!\n\nSaved to:\n{out_path.name}", parent=self
        )
        self._closed = True
        self.destroy()

    def _on_trim_error(self, err_msg: str) -> None:
        if self._closed:
            return
        self.trim_btn.configure(state="normal", text="⚡ Trim & Add to Queue")
        messagebox.showerror("Trim Error", f"Failed to trim video:\n{err_msg}", parent=self)
