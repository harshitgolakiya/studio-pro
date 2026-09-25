from __future__ import annotations

import json
import os
from pathlib import Path
import platform
from collections import deque
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

from converter import ConversionResult
import temp_tracker
from utils import (
    build_destination_filename,
    format_file_size,
    format_saved_percentage,
    reserve_output_path,
)

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".wmv", ".m4v"}
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


_EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""
_VENDOR_DIR_NAME = "ffmpeg" if sys.platform == "win32" else "ffmpeg-mac"

# Common Homebrew install locations, checked as a last resort after PATH.
# Apple Silicon uses /opt/homebrew, Intel Macs use /usr/local.
_MAC_FALLBACK_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))


def _bundled_tool_path(tool_name: str) -> str | None:
    """Locate a copy of ffmpeg/ffprobe shipped alongside the app.

    In a packaged (frozen) build this is ``bin/<tool_name>`` under
    ``sys._MEIPASS`` -- the directory PyInstaller collected data/binaries
    into (see Shadow.spec / Shadow-mac.spec, which collect vendor/ffmpeg
    there). This is used instead of assuming a fixed path next to the exe
    because PyInstaller's onedir layout puts collected files under an
    internal subfolder whose exact name has changed between versions.
    When running from source, fall back to the local vendor/<platform>
    folder (populated by fetch_ffmpeg.ps1 on Windows, or Homebrew/CI on
    macOS) so development matches the packaged behavior without requiring
    a system-wide FFmpeg install.
    """
    exe_name = f"{tool_name}{_EXE_SUFFIX}"
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "bin" / exe_name
        if candidate.is_file():
            return str(candidate)
    dev_candidate = (
        Path(__file__).resolve().parent / "vendor" / _VENDOR_DIR_NAME / exe_name
    )
    if dev_candidate.is_file():
        return str(dev_candidate)
    return None


def _locate_tool(tool_name: str) -> str | None:
    """Locate ffmpeg/ffprobe: bundled copy, then system PATH, then platform package managers."""
    bundled = _bundled_tool_path(tool_name)
    if bundled:
        return bundled

    exe_name = f"{tool_name}{_EXE_SUFFIX}"
    direct = shutil.which(tool_name)
    if direct:
        return direct

    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            winget_path = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
            for p in winget_path.glob(f"**/{exe_name}"):
                if p.is_file():
                    return str(p)
    else:
        for fallback_dir in _MAC_FALLBACK_DIRS:
            candidate = fallback_dir / tool_name
            if candidate.is_file():
                return str(candidate)

    return None


def get_ffmpeg_path() -> str | None:
    """Locate ffmpeg: bundled copy first, then system PATH, then platform package managers."""
    return _locate_tool("ffmpeg")


def get_ffprobe_path() -> str | None:
    """Locate ffprobe: bundled copy first, then system PATH, then platform package managers."""
    return _locate_tool("ffprobe")


def get_media_duration(source_path: Path) -> float | None:
    """Extract media duration in seconds using ffprobe."""
    ffprobe = get_ffprobe_path()
    if not ffprobe or not source_path.is_file():
        return None
    try:
        cmd = [
            ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(source_path.resolve()),
        ]
        flags = (
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=True, creationflags=flags
        )
        data = json.loads(proc.stdout)
        duration_str = data.get("format", {}).get("duration")
        if duration_str:
            return float(duration_str)
    except Exception:
        pass
    return None


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    """Stop an FFmpeg child promptly, escalating when graceful exit stalls."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception:
            pass


def trim_video_lossless(
    source_path: Path,
    output_path: Path,
    start_time: float | str,
    end_time: float | str,
) -> Path:
    """
    Losslessly trim video clip using ffmpeg stream copy (-c copy) in < 1 second.
    Does not decode or re-encode video frames.
    """
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for video trimming.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )

    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(start_time),
        "-to",
        str(end_time),
        "-i",
        str(source_path.resolve()),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path.resolve()),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=flags)
    return output_path


def extract_video_thumbnail(
    source_path: Path,
    output_path: Path,
    timestamp: float = 1.0,
) -> Path:
    """Extract a single video frame at specified timestamp to an image file."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for thumbnail extraction.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    ts_str = f"{max(0.0, float(timestamp)):.3f}" if isinstance(timestamp, (int, float)) else str(timestamp).strip()
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        ts_str,
        "-i",
        str(source_path.resolve()),
        "-vframes",
        "1",
        str(output_path.resolve()),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=flags)
    return output_path


_GPU_ENCODER_CACHE: tuple[str, str] | None = None


def get_best_hardware_encoder() -> tuple[str, str]:
    """
    Detect best available hardware-accelerated video encoder (NVIDIA NVENC, Intel QSV, AMD AMF).
    Falls back to software libx264 if no compatible GPU encoder is active.
    Returns (encoder_name, label).
    """
    global _GPU_ENCODER_CACHE
    if _GPU_ENCODER_CACHE is not None:
        return _GPU_ENCODER_CACHE

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        _GPU_ENCODER_CACHE = ("libx264", "Software CPU (libx264)")
        return _GPU_ENCODER_CACHE

    flags = (
        subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    if sys.platform == "darwin":
        # VideoToolbox is the only hardware H.264 path on macOS; it covers
        # every Apple-chip Mac (M-series and the A18 Pro MacBook Neo) as well
        # as Intel Macs with Quick Sync.
        candidates = [("h264_videotoolbox", "GPU: Apple VideoToolbox")]
    else:
        candidates = [
            ("h264_nvenc", "GPU: NVIDIA NVENC"),
            ("h264_qsv", "GPU: Intel QuickSync"),
            ("h264_amf", "GPU: AMD AMF"),
        ]
    for enc, label in candidates:
        try:
            cmd = [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:d=0.04",
                "-c:v",
                enc,
                "-f",
                "null",
                "-",
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=2, creationflags=flags
            )
            if r.returncode == 0:
                _GPU_ENCODER_CACHE = (enc, label)
                return _GPU_ENCODER_CACHE
        except Exception:
            continue

    _GPU_ENCODER_CACHE = ("libx264", "Software CPU (libx264)")
    return _GPU_ENCODER_CACHE


def convert_media_file(
    source_path: Path,
    output_directory: Path,
    target_format: str = "mp4",
    video_quality: str = "medium",  # high | medium | low | discord25 | target_mb
    target_mb: float | None = None,
    audio_bitrate: str = "192k",
    overwrite: bool = False,
    reserved_paths: set[Path] | None = None,
    mute_audio: bool = False,
    slugify_names: bool = False,
    filename_prefix: str = "",
    filename_suffix: str = "",
    normalize_audio: bool = False,
    video_resolution: str = "Original",
    video_fps: str = "Original",
    scale_percent: float | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    replace_source: bool = False,
) -> ConversionResult:
    """Convert and compress video or audio files using FFmpeg with real-time progress updates."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return ConversionResult(
            source_path,
            None,
            source_path.stat().st_size if source_path.exists() else None,
            None,
            "-",
            "Failed",
            "FFmpeg executable not found on system. Please install FFmpeg to process video/audio files.",
        )

    original_size = None
    try:
        if not source_path.is_file():
            raise FileNotFoundError("The selected media file no longer exists")

        original_size = source_path.stat().st_size
        output_directory.mkdir(parents=True, exist_ok=True)

        target_fmt = target_format.lower().replace(".", "")
        ext_map = {
            "webm": ".webm",
            "mp4": ".mp4",
            "animated_webp": ".webp",
            "gif": ".gif",
            "extract_audio": ".mp3",
            "mp3": ".mp3",
            "aac": ".m4a",
            "opus": ".opus",
            "wav": ".wav",
        }
        dest_ext = ext_map.get(target_fmt, f".{target_fmt}")
        dest_filename = build_destination_filename(
            stem=source_path.stem,
            ext=dest_ext,
            slugify=slugify_names,
            prefix=filename_prefix,
            suffix=filename_suffix,
        )
        effective_overwrite = True if replace_source else overwrite
        output_path = reserve_output_path(
            output_directory / dest_filename,
            effective_overwrite,
            reserved_paths,
        )

        # Temporary intermediate destination
        temp_fd, temp_name = tempfile.mkstemp(
            suffix=f".tmp{dest_ext}", dir=str(output_directory)
        )
        os.close(temp_fd)
        temporary_file = Path(temp_name)
        temp_tracker.register(temporary_file)

        media_duration = get_media_duration(source_path)

        args = [
            ffmpeg,
            "-y",
            "-nostats",
            "-progress",
            "pipe:1",
            "-i",
            str(source_path.resolve()),
        ]

        # Build video filter chain (resolution downscaling and framerate capping)
        video_filters: list[str] = []
        res_str = str(video_resolution or "").lower()
        if "1080" in res_str:
            video_filters.append("scale='min(1920,iw)':-2:flags=lanczos")
        elif "720" in res_str:
            video_filters.append("scale='min(1280,iw)':-2:flags=lanczos")
        elif "480" in res_str:
            video_filters.append("scale='min(854,iw)':-2:flags=lanczos")
        elif "360" in res_str:
            video_filters.append("scale='min(640,iw)':-2:flags=lanczos")
        elif scale_percent and 0 < scale_percent < 100:
            pct = scale_percent / 100.0
            video_filters.append(f"scale='trunc(iw*{pct}/2)*2':'trunc(ih*{pct}/2)*2':flags=lanczos")

        fps_str = str(video_fps or "").lower()
        if "60" in fps_str:
            video_filters.append("fps=60")
        elif "30" in fps_str:
            video_filters.append("fps=30")
        elif "24" in fps_str:
            video_filters.append("fps=24")
        elif "15" in fps_str:
            video_filters.append("fps=15")

        # Configure encoding arguments based on target format
        if target_fmt == "mp4":
            if video_quality in ("copy", "remux") and not video_filters:
                args.extend(["-c:v", "copy"])
            else:
                gpu_enc, _ = get_best_hardware_encoder()
                if gpu_enc != "libx264" and not (video_quality in ("discord25", "target_mb") or target_mb):
                    args.extend(["-c:v", gpu_enc])
                    if gpu_enc == "h264_qsv":
                        q = "20" if video_quality == "high" else ("28" if video_quality == "low" else "24")
                        args.extend(["-global_quality", q])
                    elif gpu_enc == "h264_nvenc":
                        cq = "19" if video_quality == "high" else ("28" if video_quality == "low" else "23")
                        args.extend(["-cq", cq, "-preset", "p4"])
                    elif gpu_enc == "h264_amf":
                        args.extend(["-rc", "cbr"])
                    elif gpu_enc == "h264_videotoolbox":
                        if platform.machine() == "arm64":
                            q = "75" if video_quality == "high" else ("45" if video_quality == "low" else "60")
                            args.extend(["-q:v", q])
                        else:
                            b = "8M" if video_quality == "high" else ("2M" if video_quality == "low" else "4M")
                            args.extend(["-b:v", b])
                        args.extend(["-pix_fmt", "yuv420p"])
                else:
                    args.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
                    if video_quality == "high":
                        args.extend(["-crf", "18", "-preset", "slow"])
                    elif video_quality == "low":
                        args.extend(["-crf", "28", "-preset", "fast"])
                    elif (
                        video_quality in ("discord25", "target_mb") or target_mb
                    ):
                        duration = media_duration or 30.0
                        mb_limit = 24.0 if video_quality == "discord25" else (target_mb or 15.0)
                        total_kbits = (mb_limit * 8192) / duration
                        audio_kbps = 96
                        video_kbps = max(100, int(total_kbits - audio_kbps))
                        args.extend(["-b:v", f"{video_kbps}k", "-b:a", f"{audio_kbps}k", "-preset", "veryfast"])
                    else:  # medium default
                        args.extend(["-crf", "23", "-preset", "medium"])

                if video_filters:
                    args.extend(["-vf", ",".join(video_filters)])

            if mute_audio:
                args.append("-an")
            elif "-b:a" not in args:
                args.extend(["-c:a", "aac", "-b:a", "128k"])

        elif target_fmt == "webm":
            # Multi-threaded fast VP9 WebM encoding:
            # By default libvpx-vp9 runs single-threaded at cpu-used 1 which is painfully slow.
            # Adding -deadline good -cpu-used 4-6, -row-mt 1, -threads 0, -tile-columns 2, -frame-parallel 1
            # utilizes all CPU cores with parallel row processing, matching cloud converters (5x-10x faster).
            cpu_used = "4" if video_quality == "high" else ("6" if video_quality == "low" else "5")
            args.extend([
                "-c:v", "libvpx-vp9",
                "-deadline", "good",
                "-cpu-used", cpu_used,
                "-row-mt", "1",
                "-threads", "0",
                "-tile-columns", "2",
                "-frame-parallel", "1",
            ])
            if (video_quality in ("discord25", "target_mb") or target_mb):
                duration = media_duration or 30.0
                mb_limit = 24.0 if video_quality == "discord25" else (target_mb or 15.0)
                total_kbits = (mb_limit * 8192) / duration
                audio_kbps = 96
                video_kbps = max(100, int(total_kbits - audio_kbps))
                args.extend(["-b:v", f"{video_kbps}k", "-crf", "36"])
            else:
                crf = "28" if video_quality == "high" else ("38" if video_quality == "low" else "33")
                args.extend(["-b:v", "0", "-crf", crf])

            if video_filters:
                args.extend(["-vf", ",".join(video_filters)])

            if mute_audio:
                args.append("-an")
            else:
                args.extend(["-c:a", "libopus", "-b:a", "96k", "-vbr", "on"])

        elif target_fmt == "animated_webp":
            args.extend([
                "-vcodec", "libwebp",
                "-lossless", "0",
                "-q:v", "70",
                "-loop", "0",
                "-vf", "fps=15,scale='min(640,iw)':-2:flags=lanczos",
                "-an",
            ])

        elif target_fmt == "gif":
            args.extend([
                "-vf", "fps=12,scale='min(480,iw)':-2:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                "-an",
            ])

        elif target_fmt in ("extract_audio", "mp3"):
            args.extend(["-vn", "-c:a", "libmp3lame", "-b:a", audio_bitrate or "192k"])

        elif target_fmt == "aac":
            args.extend(["-vn", "-c:a", "aac", "-b:a", audio_bitrate or "192k"])

        elif target_fmt == "opus":
            args.extend(["-vn", "-c:a", "libopus", "-b:a", audio_bitrate or "128k"])

        elif target_fmt == "wav":
            args.extend(["-vn", "-c:a", "pcm_s16le"])

        if normalize_audio and not mute_audio and target_fmt not in ("animated_webp", "gif"):
            args.extend(["-af", "loudnorm"])

        args.append(str(temporary_file.resolve()))

        flags = (
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=flags,
        )

        last_cb_time = 0.0
        cancelled = False
        stalled = False
        # FFmpeg writes diagnostics to stderr while machine-readable progress
        # is emitted on stdout. Windows pipes have a small buffer; reading only
        # stdout can therefore deadlock once stderr fills (seen consistently on
        # GitHub's Windows runners and with some hardware encoders). Drain it
        # concurrently and retain only the tail needed for an actionable error.
        stderr_lines: deque[str] = deque(maxlen=200)

        def drain_stderr() -> None:
            if proc.stderr is None:
                return
            for error_line in proc.stderr:
                stderr_lines.append(error_line)

        stderr_thread = threading.Thread(
            target=drain_stderr,
            name="shadow-ffmpeg-stderr",
            daemon=True,
        )
        stderr_thread.start()

        stdout_queue: queue.Queue[str | None] = queue.Queue()

        def drain_stdout() -> None:
            try:
                if proc.stdout is not None:
                    for progress_line in proc.stdout:
                        stdout_queue.put(progress_line)
            finally:
                stdout_queue.put(None)

        stdout_thread = threading.Thread(
            target=drain_stdout,
            name="shadow-ffmpeg-progress",
            daemon=True,
        )
        stdout_thread.start()
        last_process_output = time.monotonic()

        while True:
            if cancel_check and cancel_check():
                cancelled = True
                _terminate_process(proc)
                break
            try:
                line = stdout_queue.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None and not stdout_thread.is_alive():
                    break
                if time.monotonic() - last_process_output > 120.0:
                    stalled = True
                    _terminate_process(proc)
                    break
                continue
            if line is None:
                if proc.poll() is not None:
                    break
                continue
            last_process_output = time.monotonic()
            line = line.strip()
            if not line:
                continue
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=")[1])
                    elapsed_sec = us / 1_000_000.0
                    now = time.monotonic()
                    if progress_callback and (now - last_cb_time >= 0.12):
                        last_cb_time = now
                        if media_duration and media_duration > 0:
                            fraction = max(0.01, min(0.99, elapsed_sec / media_duration))
                            pct_int = int(fraction * 100)
                            elapsed_m, elapsed_s = divmod(int(elapsed_sec), 60)
                            total_m, total_s = divmod(int(media_duration), 60)
                            msg = f"Encoding {source_path.name}: {pct_int}% ({elapsed_m:02d}:{elapsed_s:02d} / {total_m:02d}:{total_s:02d})"
                            progress_callback(fraction, msg)
                        else:
                            elapsed_m, elapsed_s = divmod(int(elapsed_sec), 60)
                            msg = f"Encoding {source_path.name}: {elapsed_m:02d}:{elapsed_s:02d} elapsed"
                            progress_callback(0.5, msg)
                except (ValueError, IndexError):
                    pass
            elif line == "progress=end" and progress_callback:
                progress_callback(1.0, f"Finishing {source_path.name}...")

        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            _terminate_process(proc)
        stdout_thread.join(timeout=2.0)
        stderr_thread.join(timeout=2.0)
        stderr_text = "".join(stderr_lines)
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()

        if cancelled:
            temporary_file.unlink(missing_ok=True)
            temp_tracker.unregister(temporary_file)
            return ConversionResult(
                source_path, None, original_size, None, "-", "Cancelled", "Operation cancelled"
            )

        if stalled:
            temporary_file.unlink(missing_ok=True)
            temp_tracker.unregister(temporary_file)
            return ConversionResult(
                source_path,
                None,
                original_size,
                None,
                "-",
                "Failed",
                "FFmpeg stopped responding for 120 seconds and was terminated",
            )

        if proc.returncode != 0:
            temporary_file.unlink(missing_ok=True)
            temp_tracker.unregister(temporary_file)
            clean_err = (stderr_text or "").strip()
            err_lines = [
                l.strip()
                for l in clean_err.splitlines()
                if l.strip() and not l.strip().startswith(("built with", "configuration:", "libav", "ffmpeg version"))
            ]
            err_msg = err_lines[-1] if err_lines else "Unknown conversion failure"
            raise RuntimeError(f"FFmpeg error: {err_msg}")

        # Atomic rename to final output path
        os.replace(temporary_file, output_path)
        temp_tracker.unregister(temporary_file)

        output_size = output_path.stat().st_size
        note = None
        if replace_source:
            try:
                resolved_source = source_path.resolve()
                resolved_output = output_path.resolve()
                if resolved_source != resolved_output and resolved_source.is_file():
                    resolved_source.unlink()
                    note = "Replaced original"
                elif resolved_source == resolved_output:
                    note = "Replaced in-place"
            except Exception as exc:
                note = f"Source delete error: {exc}"

        return ConversionResult(
            source_path,
            output_path,
            original_size,
            output_size,
            format_saved_percentage(original_size, output_size),
            "Completed",
            note=note,
        )
    except Exception as error:
        return ConversionResult(
            source_path, None, original_size, None, "-", "Failed", str(error)
        )
