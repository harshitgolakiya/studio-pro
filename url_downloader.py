from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Callable

from media_engine import get_ffmpeg_path

try:
    import yt_dlp
    HAS_YT_DLP = True
except ImportError:
    yt_dlp = None
    HAS_YT_DLP = False


def ensure_yt_dlp_installed() -> bool:
    """Install yt-dlp into the active Python environment when it is missing."""
    global HAS_YT_DLP, yt_dlp

    if HAS_YT_DLP and yt_dlp is not None:
        return True

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "yt-dlp>=2026.8.19"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "yt-dlp is required for URL downloads, and automatic installation failed. "
            f"Please install it manually: {exc.stderr or exc.stdout or str(exc)}"
        ) from exc

    try:
        import yt_dlp as installed_yt_dlp  # type: ignore
    except ImportError as exc:
        raise RuntimeError("yt-dlp could not be imported after installation.") from exc

    yt_dlp = installed_yt_dlp
    HAS_YT_DLP = True
    return True


class DownloadCancelledError(Exception):
    """Raised when the user explicitly cancels an in-progress stream download."""
    pass


class MembersOnlyError(RuntimeError):
    """Raised when the video requires YouTube channel membership or sign-in authentication."""
    pass


class YDLLogger:
    """Internal logger that captures warnings/errors and allows early cancellation during extraction."""

    def __init__(
        self,
        cancel_event: threading.Event | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> None:
        self.cancel_event = cancel_event
        self.progress_callback = progress_callback
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        if self.cancel_event and self.cancel_event.is_set():
            raise DownloadCancelledError("Download cancelled by user.")
        if "[youtube]" in msg and self.progress_callback:
            # Provide responsive feedback during extraction phase
            clean = msg.replace("[youtube]", "").strip()
            if clean:
                self.progress_callback(5.0, f"YouTube: {clean}...")

    def info(self, msg: str) -> None:
        if self.cancel_event and self.cancel_event.is_set():
            raise DownloadCancelledError("Download cancelled by user.")

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)


def download_media_from_url(
    url: str,
    output_dir: Path,
    download_audio_only: bool = False,
    quality_preset: str = "1080p Full HD",
    cookies_source: str = "none",
    cookie_file_path: Path | str | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """
    Download a video or audio stream from URL (YouTube, Vimeo, etc.) using yt-dlp.
    Supports authenticated YouTube channel members-only downloads via browser cookies or cookies.txt.
    Returns the path to the downloaded file.
    """
    if not HAS_YT_DLP:
        ensure_yt_dlp_installed()

    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = get_ffmpeg_path()

    downloaded_files: list[str] = []

    def hook(d: dict) -> None:
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelledError("Download cancelled by user.")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            percent = (downloaded / total * 100) if total > 0 else 0
            speed = d.get("speed") or 0
            speed_str = f"{speed / (1024 * 1024):.1f} MB/s" if speed else ""
            msg = f"Downloading: {percent:.1f}% ({speed_str})" if speed_str else f"Downloading: {percent:.1f}%"
            if progress_callback:
                progress_callback(percent, msg)
        elif status == "finished":
            filename = d.get("filename")
            if filename:
                downloaded_files.append(filename)
            if progress_callback:
                progress_callback(95.0, "Processing and finalizing media...")

    out_template = str(output_dir / "%(title)s.%(ext)s")
    logger = YDLLogger(cancel_event=cancel_event, progress_callback=progress_callback)

    ydl_opts: dict = {
        "outtmpl": out_template,
        "progress_hooks": [hook],
        "logger": logger,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "quiet": True,
        "no_warnings": False,
        "no_color": True,
        "windowsfilenames": True,
    }

    if ffmpeg_bin:
        ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_bin).parent)

    # Configure Authentication & Cookies
    if cookie_file_path and Path(cookie_file_path).is_file():
        ydl_opts["cookiefile"] = str(Path(cookie_file_path).resolve())
    elif cookies_source and cookies_source.lower() not in ("none", "none (public streams)"):
        c_src = cookies_source.lower()
        if "edge" in c_src:
            ydl_opts["cookiesfrombrowser"] = ("edge",)
        elif "chrome" in c_src:
            ydl_opts["cookiesfrombrowser"] = ("chrome",)
        elif "firefox" in c_src:
            ydl_opts["cookiesfrombrowser"] = ("firefox",)
        elif "brave" in c_src:
            ydl_opts["cookiesfrombrowser"] = ("brave",)
        elif "opera" in c_src:
            ydl_opts["cookiesfrombrowser"] = ("opera",)
        elif "auto" in c_src:
            # Default to Microsoft Edge on Windows as standard non-locked browser option
            ydl_opts["cookiesfrombrowser"] = ("edge",)

    if download_audio_only:
        ydl_opts["format"] = "bestaudio/best"
        bitrate = "320"
        if "192" in quality_preset:
            bitrate = "192"
        elif "128" in quality_preset:
            bitrate = "128"

        if ffmpeg_bin:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": bitrate,
                }
            ]
    else:
        # Determine video format by resolution preset
        if "4K" in quality_preset or "Best" in quality_preset:
            ydl_opts["format"] = (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
            )
        elif "720p" in quality_preset:
            ydl_opts["format"] = (
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
            )
        elif "480p" in quality_preset:
            ydl_opts["format"] = (
                "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]/best"
            )
        else:
            # Default to 1080p Full HD
            ydl_opts["format"] = (
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
            )

        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if progress_callback:
                progress_callback(5.0, "Contacting stream server & resolving formats...")

            info = ydl.extract_info(url.strip(), download=True)
            if not info:
                raise RuntimeError("Could not retrieve media info from the provided URL.")

            # Determine resulting file
            if "requested_downloads" in info and info["requested_downloads"]:
                filepath = info["requested_downloads"][0].get("filepath")
                if filepath and Path(filepath).exists():
                    return Path(filepath)

            # Check prepared filename
            candidate = Path(ydl.prepare_filename(info))
            if download_audio_only and candidate.with_suffix(".mp3").exists():
                return candidate.with_suffix(".mp3")
            if candidate.exists():
                return candidate

            # Check downloaded_files hook
            if downloaded_files:
                p = Path(downloaded_files[-1])
                if download_audio_only and p.with_suffix(".mp3").exists():
                    return p.with_suffix(".mp3")
                if p.exists():
                    return p

            # Fallback: inspect newest file in output_dir
            files = sorted(output_dir.glob("*"), key=os.path.getmtime, reverse=True)
            if files:
                return files[0]

            raise FileNotFoundError("Downloaded media file could not be located.")

    except DownloadCancelledError:
        raise
    except Exception as exc:
        combined_err = (str(exc) + " " + " ".join(logger.errors)).strip()
        combined_lower = combined_err.lower()

        # Members-Only / Restricted Video detection
        if any(
            phrase in combined_lower
            for phrase in (
                "join this channel",
                "members-only",
                "members only",
                "sign in to confirm your age",
                "sign in if you've been granted access",
                "this video is private",
                "private video",
                "requires authentication",
            )
        ):
            raise MembersOnlyError(
                "🔒 Members-Only / Restricted Video:\n\n"
                "YouTube requires an active channel membership session to download this video.\n\n"
                "Even though you are a member in your browser, YouTube requires your membership cookie to authenticate the stream.\n\n"
                "To fix:\n"
                "1. Under 'Auth / Cookies', select your browser (Edge / Firefox / Chrome) or 'Custom cookies.txt File'.\n"
                "2. If Chrome has App-Bound encryption locked, export your cookies to cookies.txt (using the free browser extension 'Get cookies.txt locally') and select it."
            )

        # Cookie decryption / lock failure detection
        if "could not copy chrome cookie database" in combined_lower or "failed to decrypt with dpapi" in combined_lower:
            raise RuntimeError(
                "🔑 Browser Cookie Store Locked:\n\n"
                "Windows or your browser is currently locking direct access to the cookie database while the browser is running.\n\n"
                "To download members-only content:\n"
                "1. Close your browser and retry, OR\n"
                "2. Export cookies to a 'cookies.txt' file (using 'Get cookies.txt locally') and select 'Custom cookies.txt File' under 'Auth / Cookies'."
            )

        # Clean up technical prefixes like "ERROR: "
        clean_msg = re.sub(r"^ERROR:\s*", "", combined_err)
        raise RuntimeError(clean_msg or str(exc))
