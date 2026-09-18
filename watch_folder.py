from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from typing import Callable

from converter import SUPPORTED_EXTENSIONS, ConversionResult, convert_image
from media_engine import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    convert_media_file,
)

ALL_SUPPORTED_EXTS = SUPPORTED_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS


class FolderWatcher:
    """
    Monitors a folder in the background. When new media files are dropped,
    waits for writing to stabilize and automatically converts them.
    """

    def __init__(
        self,
        watch_dir: Path,
        output_dir: Path,
        target_format: str = "WEBP",
        quality: int = 80,
        on_event: Callable[[str, str], None] | None = None,
        poll_interval: float = 1.5,
    ) -> None:
        self.watch_dir = watch_dir
        self.output_dir = output_dir
        self.target_format = target_format
        self.quality = quality
        self.on_event = on_event
        self.poll_interval = poll_interval

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._processed_files: set[Path] = set()
        self._file_sizes: dict[Path, int] = {}
        self._stable_polls: dict[Path, int] = {}

        # Require this many consecutive unchanged-size polls before treating
        # a file as fully written. A single matching poll is not enough --
        # a network/cloud-synced transfer can stall mid-copy for longer than
        # one poll interval and look "stable" while still incomplete.
        self._STABLE_POLLS_REQUIRED = 2

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Pre-populate already existing files so we only process new ones
        for p in self.watch_dir.glob("*"):
            if p.is_file():
                self._processed_files.add(p.resolve())

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if self.on_event:
            self.on_event("info", f"Started monitoring: {self.watch_dir.name}")

    def stop(self) -> None:
        if not self.is_running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        if self.on_event:
            self.on_event("info", "Monitoring stopped.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._scan_and_process()
            except Exception as exc:
                if self.on_event:
                    self.on_event("error", f"Watch error: {exc}")
            time.sleep(self.poll_interval)

    def _scan_and_process(self) -> None:
        if not self.watch_dir.is_dir():
            return

        for p in self.watch_dir.iterdir():
            if self._stop_event.is_set():
                break
            if not p.is_file():
                continue
            resolved = p.resolve()
            if resolved in self._processed_files:
                continue
            if p.suffix.lower() not in ALL_SUPPORTED_EXTS:
                continue

            # Check if file is still being written by another app (size stabilization)
            try:
                current_size = p.stat().st_size
            except (FileNotFoundError, PermissionError):
                continue

            last_size = self._file_sizes.get(resolved)
            if last_size is None or last_size != current_size or current_size == 0:
                self._file_sizes[resolved] = current_size
                self._stable_polls[resolved] = 0
                continue  # wait for next check to confirm size has settled

            stable_count = self._stable_polls.get(resolved, 0) + 1
            self._stable_polls[resolved] = stable_count
            if stable_count < self._STABLE_POLLS_REQUIRED:
                continue  # size matched once; wait for another confirming poll

            # File is stable, process it
            self._process_file(resolved)

    def _process_file(self, file_path: Path) -> None:
        self._processed_files.add(file_path)
        self._file_sizes.pop(file_path, None)
        self._stable_polls.pop(file_path, None)

        if self.on_event:
            self.on_event("info", f"Processing: {file_path.name}")

        ext = file_path.suffix.lower()
        is_video = ext in SUPPORTED_VIDEO_EXTENSIONS
        is_audio = ext in SUPPORTED_AUDIO_EXTENSIONS

        try:
            if is_video or is_audio:
                fmt_key = "mp4"
                if "WEBM" in self.target_format.upper():
                    fmt_key = "webm"
                elif "MP3" in self.target_format.upper():
                    fmt_key = "mp3"
                res = convert_media_file(
                    file_path,
                    self.output_dir,
                    target_format=fmt_key,
                )
            else:
                fmt_key = self.target_format.upper().replace(".", "")
                res = convert_image(
                    file_path,
                    self.output_dir,
                    target_format=fmt_key,
                    quality=self.quality,
                )

            if res.status == "Completed":
                saved_msg = f"({res.saved} saved)" if res.saved != "-" else ""
                if self.on_event:
                    self.on_event(
                        "success",
                        f"Done: {file_path.name} ➔ {res.output_path.name if res.output_path else ''} {saved_msg}",
                    )
            else:
                if self.on_event:
                    self.on_event("error", f"Failed {file_path.name}: {res.error}")
        except Exception as exc:
            if self.on_event:
                self.on_event("error", f"Error converting {file_path.name}: {exc}")
