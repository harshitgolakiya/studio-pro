"""Audio mastering and delivery using the bundled FFmpeg engine."""
from __future__ import annotations

from pathlib import Path
import json
import math
import re
import tempfile
from typing import Callable

from media_engine import get_ffmpeg_path
from studio_runtime import check_cancel, run_engine
from utils import publish_output_file, release_output_path, reserve_output_path

ENCODERS = {
    "WAV": (".wav", ["-c:a", "pcm_s16le"]),
    "MP3": (".mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "FLAC": (".flac", ["-c:a", "flac"]),
    "AAC": (".m4a", ["-c:a", "aac", "-b:a", "192k"]),
    "OPUS": (".opus", ["-c:a", "libopus", "-b:a", "128k"]),
}


def process_audio(source: Path, destination: Path, fmt: str = "WAV", normalize: bool = True,
                  denoise: bool = False, start: float = 0, duration: float | None = None,
                  overwrite: bool = False, cancel_check: Callable[[], bool] | None = None) -> Path:
    if not source.is_file():
        raise FileNotFoundError("Choose an existing audio or video file")
    if fmt not in ENCODERS:
        raise ValueError("Choose WAV, MP3, FLAC, AAC, or OPUS")
    if start < 0 or (duration is not None and duration <= 0):
        raise ValueError("Start must be non-negative; duration must be positive or empty")
    extension, codec = ENCODERS[fmt]
    if destination.suffix.lower() != extension:
        raise ValueError(f"{fmt} requires a {extension} destination")
    if destination.resolve() == source.resolve():
        raise ValueError("Choose a different output filename to keep the source")
    engine = get_ffmpeg_path()
    if not engine:
        raise RuntimeError("FFmpeg is missing. Run fetch_ffmpeg.ps1")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reservations: set[Path] = set()
    output = reserve_output_path(destination, overwrite, reservations)
    try:
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".shadow-audio-") as td:
            temporary = Path(td) / ("audio" + extension)
            args = [engine, "-hide_banner", "-nostdin", "-y"]
            if start:
                args.extend(["-ss", str(start)])
            args.extend(["-i", str(source.resolve()), "-map", "0:a:0", "-vn"])
            if duration is not None:
                args.extend(["-t", str(duration)])
            filters = []
            if denoise:
                filters.append("afftdn=nf=-25")
            if normalize:
                # Measure first. Digital silence has no finite integrated
                # loudness; applying dynamic gain to it can create NaNs.
                analysis_filter = ",".join([*filters, "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json"])
                diagnostic = run_engine([*args, "-af", analysis_filter, "-f", "null", "-"],
                                        timeout=3600, cancel_check=cancel_check)
                match = re.search(r'\{\s*"input_i".*?\}', diagnostic, re.S)
                if not match:
                    raise RuntimeError("FFmpeg did not return loudness measurements")
                measured = json.loads(match.group())
                keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
                values = [float(measured[key]) for key in keys]
                if all(math.isfinite(value) for value in values):
                    filters.append("loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:"
                                   f"measured_I={values[0]}:measured_TP={values[1]}:measured_LRA={values[2]}:"
                                   f"measured_thresh={values[3]}:offset={values[4]}")
            if filters:
                args.extend(["-af", ",".join(filters)])
            args.extend([*codec, str(temporary)])
            run_engine(args, timeout=3600, cancel_check=cancel_check)
            if not temporary.is_file() or temporary.stat().st_size < 16:
                raise RuntimeError("No audio was produced. Check the source has an audio track and the selected trim range.")
            check_cancel(cancel_check)
            return publish_output_file(temporary, output, overwrite, reservations)
    finally:
        release_output_path(output, reservations)
