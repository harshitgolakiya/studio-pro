from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from font_loader import DISPLAY_FONT
from settings import load_settings, update_setting
from url_downloader import (
    DownloadCancelledError,
    HAS_YT_DLP,
    MembersOnlyError,
    download_media_from_url,
)
from utils import play_completion_sound

VIDEO_QUALITIES = [
    "1080p Full HD",
    "Best Available (4K / 2K)",
    "720p HD",
    "480p SD",
]

AUDIO_QUALITIES = [
    "320 kbps (HQ)",
    "192 kbps (Standard)",
    "128 kbps (Compact)",
]

COOKIE_OPTIONS = [
    "None (Public Streams)",
    "Auto-Detect Browser (Edge / Chrome)",
    "Microsoft Edge",
    "Google Chrome",
    "Mozilla Firefox",
    "Brave Browser",
    "Custom cookies.txt File",
]


class URLDownloaderDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        default_output_dir: Path | None = None,
        on_download_complete: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_download_complete = on_download_complete
        self.cancel_event = threading.Event()
        self.download_thread: threading.Thread | None = None
        self.settings = load_settings()
        self._closed = False
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self.title("Media Stream Downloader (VIP)")
        self.geometry("620x540")
        self.minsize(560, 480)
        self.resizable(False, False)

        # Output dir fallback to Downloads
        if default_output_dir and default_output_dir.is_dir():
            out_dir = str(default_output_dir)
        else:
            out_dir = str(Path.home() / "Downloads")

        self.url_var = tk.StringVar(value="")
        self.format_var = tk.StringVar(value="Video (MP4)")
        self.quality_var = tk.StringVar(value=VIDEO_QUALITIES[0])
        self.output_dir_var = tk.StringVar(value=out_dir)

        # Persistent Cookies / Auth settings
        saved_cookie_source = self.settings.get("stream_cookie_source", COOKIE_OPTIONS[1])
        if saved_cookie_source not in COOKIE_OPTIONS:
            saved_cookie_source = COOKIE_OPTIONS[1]
        self.cookie_source_var = tk.StringVar(value=saved_cookie_source)
        self.cookie_file_var = tk.StringVar(value=self.settings.get("stream_cookie_file", ""))

        self.status_var = tk.StringVar(
            value="Paste any video, member stream, or audio link to download for offline watching."
        )
        self.progress_val = tk.DoubleVar(value=0.0)

        self._build_ui()
        self.grab_set()

    def _build_ui(self) -> None:
        self.configure(fg_color=("#f8f9fa", "#1a1d20"))

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=18)

        # Header Badge
        ctk.CTkLabel(
            container,
            text="VIP POWER FEATURE",
            fg_color="#D4A03C",
            text_color="#171308",
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=6,
            width=140,
            height=24,
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            container,
            text="Media Stream Downloader",
            font=ctk.CTkFont(family=DISPLAY_FONT, size=19, weight="bold"),
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            container,
            text="Save videos, members-only streams & audio locally for private offline watching.",
            font=ctk.CTkFont(size=12),
            text_color=("#667085", "#98a2b3"),
        ).pack(pady=(0, 12))

        # URL Input Row
        url_frame = ctk.CTkFrame(container, fg_color="transparent")
        url_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            url_frame,
            text="Stream URL:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=90,
            anchor="w",
        ).pack(side="left")

        self.url_entry = ctk.CTkEntry(
            url_frame,
            textvariable=self.url_var,
            placeholder_text="https://www.youtube.com/watch?v=...",
            height=32,
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(4, 6))

        ctk.CTkButton(
            url_frame,
            text="Paste",
            width=60,
            height=32,
            command=self._paste_clipboard,
        ).pack(side="right")

        # Options Row: Format & Quality Selector
        opt_frame = ctk.CTkFrame(container, fg_color="transparent")
        opt_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            opt_frame,
            text="Format:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=90,
            anchor="w",
        ).pack(side="left")

        self.format_menu = ctk.CTkOptionMenu(
            opt_frame,
            variable=self.format_var,
            values=["Video (MP4)", "Audio (MP3)"],
            width=135,
            height=30,
            command=self._on_format_changed,
        )
        self.format_menu.pack(side="left", padx=(4, 16))

        ctk.CTkLabel(
            opt_frame,
            text="Quality:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=55,
            anchor="w",
        ).pack(side="left")

        self.quality_menu = ctk.CTkOptionMenu(
            opt_frame,
            variable=self.quality_var,
            values=VIDEO_QUALITIES,
            width=180,
            height=30,
        )
        self.quality_menu.pack(side="left", padx=(4, 0))

        # Authentication / Cookies Row
        auth_frame = ctk.CTkFrame(container, fg_color="transparent")
        auth_frame.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            auth_frame,
            text="Cookies / Auth:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=90,
            anchor="w",
        ).pack(side="left")

        self.cookie_menu = ctk.CTkOptionMenu(
            auth_frame,
            variable=self.cookie_source_var,
            values=COOKIE_OPTIONS,
            width=260,
            height=30,
            command=self._on_cookie_source_changed,
        )
        self.cookie_menu.pack(side="left", padx=(4, 8))

        ctk.CTkLabel(
            auth_frame,
            text="Required for Member-Only content",
            font=ctk.CTkFont(size=10),
            text_color=("#64748b", "#94a3b8"),
        ).pack(side="left")

        # Custom cookies.txt picker frame
        self.cookie_file_frame = ctk.CTkFrame(container, fg_color="transparent")
        ctk.CTkLabel(
            self.cookie_file_frame,
            text="Cookie File:",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=90,
            anchor="w",
        ).pack(side="left")

        self.cookie_file_entry = ctk.CTkEntry(
            self.cookie_file_frame,
            textvariable=self.cookie_file_var,
            placeholder_text="Path to exported Netscape cookies.txt file...",
            height=28,
        )
        self.cookie_file_entry.pack(side="left", fill="x", expand=True, padx=(4, 6))

        ctk.CTkButton(
            self.cookie_file_frame,
            text="Browse...",
            width=70,
            height=28,
            command=self._browse_cookie_file,
        ).pack(side="right")

        if self.cookie_source_var.get() == "Custom cookies.txt File":
            self.cookie_file_frame.pack(fill="x", pady=(0, 8))

        # Output folder row
        folder_frame = ctk.CTkFrame(container, fg_color="transparent")
        folder_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            folder_frame,
            text="Save to:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=90,
            anchor="w",
        ).pack(side="left")

        self.folder_entry = ctk.CTkEntry(
            folder_frame,
            textvariable=self.output_dir_var,
            height=30,
        )
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(4, 6))

        ctk.CTkButton(
            folder_frame,
            text="Browse",
            width=70,
            height=30,
            command=self._browse_folder,
        ).pack(side="right")

        # Progress bar & Status
        self.progress_bar = ctk.CTkProgressBar(container, variable=self.progress_val)
        self.progress_bar.pack(fill="x", pady=(0, 4))

        self.status_label = ctk.CTkLabel(
            container,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=11),
            text_color=("#667085", "#98a2b3"),
            anchor="w",
        )
        self.status_label.pack(fill="x", pady=(0, 8))

        # Alert / Guidance Card (hidden by default, surfaces on member-only or authentication errors)
        self.alert_card = ctk.CTkFrame(
            container,
            fg_color=("#fefce8", "#422006"),
            border_width=1,
            border_color=("#facc15", "#ca8a04"),
            corner_radius=8,
        )
        self.alert_title = ctk.CTkLabel(
            self.alert_card,
            text="🔒 Channel Members-Only Video Detected",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#854d0e", "#fef08a"),
            anchor="w",
        )
        self.alert_title.pack(fill="x", padx=12, pady=(6, 2))

        self.alert_body = ctk.CTkLabel(
            self.alert_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("#713f12", "#fde047"),
            anchor="w",
            justify="left",
            wraplength=540,
        )
        self.alert_body.pack(fill="x", padx=12, pady=(0, 6))

        # Action Buttons
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", side="bottom")

        self.download_btn = ctk.CTkButton(
            btn_frame,
            text="Download & Add to Queue",
            fg_color="#12877A",
            hover_color="#17A594",
            height=36,
            font=ctk.CTkFont(weight="bold"),
            command=self._start_download,
        )
        self.download_btn.pack(side="right", padx=(8, 0))

        self.cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            height=36,
            state="disabled",
            fg_color="transparent",
            border_width=1,
            border_color=("#d0d5dd", "#475467"),
            text_color=("#344054", "#f2f4f7"),
            command=self._cancel_download,
        )
        self.cancel_btn.pack(side="right")

        self.close_btn = ctk.CTkButton(
            btn_frame,
            text="Close",
            height=36,
            width=80,
            fg_color="transparent",
            text_color=("#667085", "#98a2b3"),
            command=self._on_close_request,
        )
        self.close_btn.pack(side="left")

    def _on_close_request(self) -> None:
        """Handle window-close (X button or Close button) while a download may be in flight."""
        if self.download_thread and self.download_thread.is_alive():
            self.cancel_event.set()
        self._closed = True
        self.destroy()

    def _on_format_changed(self, new_format: str) -> None:
        if "Audio" in new_format:
            self.quality_menu.configure(values=AUDIO_QUALITIES)
            self.quality_var.set(AUDIO_QUALITIES[0])
        else:
            self.quality_menu.configure(values=VIDEO_QUALITIES)
            self.quality_var.set(VIDEO_QUALITIES[0])

    def _on_cookie_source_changed(self, new_source: str) -> None:
        update_setting("stream_cookie_source", new_source)
        if new_source == "Custom cookies.txt File":
            self.cookie_file_frame.pack(fill="x", pady=(0, 8), before=self.folder_entry.master)
        else:
            self.cookie_file_frame.pack_forget()

    def _browse_cookie_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Select Exported cookies.txt",
            parent=self,
            filetypes=[("Text & Cookie Files", "*.txt *.cookies"), ("All Files", "*.*")],
        )
        if file_path:
            self.cookie_file_var.set(file_path)
            update_setting("stream_cookie_file", file_path)

    def _paste_clipboard(self) -> None:
        try:
            text = self.clipboard_get()
            if text:
                self.url_var.set(text.strip())
        except Exception:
            pass

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select Destination Folder", parent=self)
        if folder:
            self.output_dir_var.set(folder)

    def _start_download(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL Required", "Please paste or enter a valid video/audio URL.", parent=self)
            return

        if not HAS_YT_DLP:
            messagebox.showerror(
                "Missing yt-dlp",
                "yt-dlp is required for media streaming. Please ensure yt-dlp is installed.",
                parent=self,
            )
            return

        output_dir = Path(self.output_dir_var.get().strip())
        audio_only = "Audio" in self.format_var.get()
        quality_preset = self.quality_var.get()
        cookies_source = self.cookie_source_var.get()
        cookie_file = self.cookie_file_var.get().strip() or None

        self.cancel_event.clear()
        self.alert_card.pack_forget()
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_val.set(0.0)
        self.status_var.set(f"Connecting to stream ({quality_preset})...")

        def worker() -> None:
            try:
                def progress(pct: float, msg: str) -> None:
                    self.after(0, lambda: self._update_progress(pct, msg))

                result_path = download_media_from_url(
                    url=url,
                    output_dir=output_dir,
                    download_audio_only=audio_only,
                    quality_preset=quality_preset,
                    cookies_source=cookies_source,
                    cookie_file_path=cookie_file,
                    progress_callback=progress,
                    cancel_event=self.cancel_event,
                )

                self.after(0, lambda: self._on_success(result_path))
            except DownloadCancelledError:
                self.after(0, lambda: self._on_cancelled())
            except MembersOnlyError as mem_err:
                self.after(0, lambda: self._on_members_error(str(mem_err)))
            except Exception as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        self.download_thread = threading.Thread(target=worker, daemon=True)
        self.download_thread.start()

    def _update_progress(self, pct: float, msg: str) -> None:
        if self._closed:
            return
        self.progress_val.set(pct / 100.0)
        self.status_var.set(msg)

    def _on_success(self, file_path: Path) -> None:
        if self._closed:
            # Download finished after the dialog was closed; still hand the
            # file to the queue, just skip touching destroyed widgets.
            if self.on_download_complete and file_path.exists():
                self.on_download_complete(file_path)
            return
        self.progress_val.set(1.0)
        self.status_var.set(f"Completed! Saved to: {file_path.name}")
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.alert_card.pack_forget()
        play_completion_sound()

        if self.on_download_complete and file_path.exists():
            self.on_download_complete(file_path)

        messagebox.showinfo(
            "Download Finished",
            f"Successfully downloaded:\n{file_path.name}\n\nAdded to Shadow Media Studio queue!",
            parent=self,
        )

    def _on_cancelled(self) -> None:
        if self._closed:
            return
        self.progress_val.set(0.0)
        self.status_var.set("Download was cancelled.")
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def _on_members_error(self, err_msg: str) -> None:
        if self._closed:
            return
        self.progress_val.set(0.0)
        self.status_var.set("🔒 Channel Members-Only Video — Authentication required")
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

        self.alert_card.configure(
            fg_color=("#fefce8", "#422006"),
            border_color=("#facc15", "#ca8a04"),
        )
        self.alert_title.configure(
            text="🔒 Channel Members-Only Video Detected",
            text_color=("#854d0e", "#fef08a"),
        )
        self.alert_body.configure(
            text=(
                "This video is exclusive to channel members. Even though you are a member in your browser, "
                "YouTube requires your active membership cookies to stream.\n\n"
                "👉 Quick Fix:\n"
                "1. Under 'Cookies / Auth' above, select your browser (Edge / Chrome / Firefox) or 'Custom cookies.txt File'.\n"
                "2. If Chrome locks its live store, export your cookies using the free Chrome/Edge extension 'Get cookies.txt locally' and select the file."
            ),
            text_color=("#713f12", "#fde047"),
        )
        self.alert_card.pack(fill="x", pady=(0, 10), before=self.status_label.master.winfo_children()[-1])

        messagebox.showwarning(
            "Members-Only Video",
            "This video requires channel membership authentication.\n\n"
            "Please select your browser or a cookies.txt file under 'Cookies / Auth' to download.",
            parent=self,
        )

    def _on_error(self, err_msg: str) -> None:
        if self._closed:
            return
        self.progress_val.set(0.0)
        self.status_var.set("Download failed.")
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

        is_cookie_locked = "cookie store locked" in err_msg.lower() or "dpapi" in err_msg.lower() or "could not copy" in err_msg.lower()
        if is_cookie_locked:
            self.alert_card.configure(
                fg_color=("#fff7ed", "#431407"),
                border_color=("#fb923c", "#c2410c"),
            )
            self.alert_title.configure(
                text="🔑 Browser Cookie Database Locked",
                text_color=("#9a3412", "#fdba74"),
            )
            self.alert_body.configure(
                text=(
                    "Windows or Chrome has locked the live browser cookie file while the browser is running.\n\n"
                    "👉 Fix: Close your browser and retry, OR export cookies to 'cookies.txt' (using 'Get cookies.txt locally') "
                    "and select 'Custom cookies.txt File' under 'Cookies / Auth'."
                ),
                text_color=("#7c2d12", "#fed7aa"),
            )
            self.alert_card.pack(fill="x", pady=(0, 10), before=self.status_label.master.winfo_children()[-1])
            messagebox.showwarning("Browser Cookies Locked", err_msg, parent=self)
        else:
            self.alert_card.configure(
                fg_color=("#fef2f2", "#450a0a"),
                border_color=("#f87171", "#991b1b"),
            )
            self.alert_title.configure(
                text="⚠️ Stream Download Error",
                text_color=("#b91c1c", "#fca5a5"),
            )
            self.alert_body.configure(
                text=err_msg,
                text_color=("#7f1d1d", "#fecaca"),
            )
            self.alert_card.pack(fill="x", pady=(0, 10), before=self.status_label.master.winfo_children()[-1])
            messagebox.showerror("Download Error", f"Failed to download media stream:\n\n{err_msg}", parent=self)

    def _cancel_download(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Cancelling download...")
