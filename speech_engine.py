"""Offline speech transcription and neural speech synthesis.

Model downloads are an explicit setup operation, never a conversion side effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import textwrap
from typing import Callable
import wave

from converter import ConversionResult
from studio_runtime import StudioCancelled, check_cancel, model_directory
from utils import format_saved_percentage, publish_output_file, reserve_output_path, release_output_path

_speech_lock = threading.Lock()  # bounded CPU/memory use for local neural models


@contextmanager
def speech_slot(cancel_check):
    while not _speech_lock.acquire(timeout=0.1):
        check_cancel(cancel_check)
    try:
        check_cancel(cancel_check)
        yield
    finally:
        _speech_lock.release()


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


def timestamp(seconds: float, separator: str = ",") -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def format_transcript(segments: list[TranscriptSegment], fmt: str) -> str:
    if fmt == "TXT":
        return "\n".join(s.text.strip() for s in segments) + "\n"
    if fmt == "JSON":
        return json.dumps([{"start": s.start, "end": s.end, "text": s.text.strip()}
                           for s in segments], ensure_ascii=False, indent=2)
    if fmt not in {"SRT", "VTT"}:
        raise ValueError(f"Unsupported transcript format: {fmt}")
    sep = "," if fmt == "SRT" else "."
    blocks = []
    for index, s in enumerate(segments, 1):
        text = s.text.strip().replace("-->", "→")
        blocks.append(f"{index}\n{timestamp(s.start, sep)} --> {timestamp(s.end, sep)}\n{text}\n")
    return ("WEBVTT\n\n" if fmt == "VTT" else "") + "\n".join(blocks)


def default_whisper_model() -> Path:
    return model_directory() / "whisper-base.en"


def available_voices() -> list[Path]:
    return sorted((model_directory() / "voices").glob("*.onnx"))


def transcribe_media(source: Path, output_dir: Path, fmt: str = "TXT",
                     model_path: Path | None = None, language: str | None = "en",
                     overwrite: bool = False, cancel_check: Callable[[], bool] | None = None,
                     progress: Callable[[str], None] | None = None) -> ConversionResult:
    output = None
    size = source.stat().st_size if source.is_file() else None
    reservations: set[Path] = set()
    try:
        check_cancel(cancel_check)
        if not source.is_file():
            raise FileNotFoundError("The selected media no longer exists")
        fmt = fmt.upper()
        if fmt not in {"TXT", "SRT", "VTT", "JSON"}:
            raise ValueError("Choose TXT, SRT, VTT, or JSON")
        model_path = Path(model_path or default_whisper_model())
        if not (model_path / "model.bin").is_file():
            raise RuntimeError("Transcription model missing. Run setup_studio.ps1, or choose a local faster-whisper model directory.")
        from faster_whisper import WhisperModel
        output_dir.mkdir(parents=True, exist_ok=True)
        output = reserve_output_path(output_dir / f"{source.stem}-transcript.{fmt.lower()}", overwrite, reservations)
        with speech_slot(cancel_check):
            check_cancel(cancel_check)
            if progress:
                progress("Loading local speech recognition model…")
            model = WhisperModel(str(model_path), device="cpu", compute_type="int8", local_files_only=True,
                                 cpu_threads=4, num_workers=1)
            iterator, _info = model.transcribe(str(source), language=language, vad_filter=True, beam_size=5)
            segments = []
            for segment in iterator:
                check_cancel(cancel_check)
                segments.append(TranscriptSegment(segment.start, segment.end, segment.text))
                if progress:
                    progress(f"Transcribed through {timestamp(segment.end, '.')}")
            del model
        if not segments or not any(s.text.strip() for s in segments):
            raise ValueError("No speech was detected in this file")
        with tempfile.TemporaryDirectory(dir=output_dir, prefix=".shadow-speech-") as td:
            temporary = Path(td) / f"transcript.{fmt.lower()}"
            temporary.write_text(format_transcript(segments, fmt), encoding="utf-8")
            check_cancel(cancel_check)
            output = publish_output_file(temporary, output, overwrite, reservations)
        output_size = output.stat().st_size
        return ConversionResult(source, output, size, output_size, format_saved_percentage(size, output_size),
                                "Completed", note="Local transcription; review names, numbers, and subtitle timing")
    except StudioCancelled:
        return ConversionResult(source, None, size, None, "-", "Cancelled")
    except Exception as exc:
        return ConversionResult(source, None, size, None, "-", "Failed", str(exc))
    finally:
        if output:
            release_output_path(output, reservations)


def synthesize_speech(text: str, destination: Path, voice_path: Path | None = None,
                      speed: float = 1.0, overwrite: bool = False,
                      cancel_check: Callable[[], bool] | None = None,
                      progress: Callable[[str], None] | None = None) -> Path:
    check_cancel(cancel_check)
    if not text.strip():
        raise ValueError("Enter text to speak")
    if not 0.5 <= speed <= 2.0:
        raise ValueError("Speech speed must be between 0.5 and 2.0")
    if destination.suffix.lower() != ".wav":
        raise ValueError("Speech synthesis exports WAV; use the audio converter for MP3/AAC/Opus")
    voices = available_voices()
    voice_path = Path(voice_path) if voice_path else (voices[0] if voices else None)
    if voice_path is None or not voice_path.is_file() or not Path(str(voice_path) + ".json").is_file():
        raise RuntimeError("Voice model missing. Run setup_studio.ps1 or select a Piper .onnx voice with its .onnx.json configuration.")
    from piper import PiperVoice, SynthesisConfig
    destination.parent.mkdir(parents=True, exist_ok=True)
    reservations: set[Path] = set()
    output = reserve_output_path(destination, overwrite, reservations)
    try:
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".shadow-voice-") as td:
            temporary = Path(td) / "voice.wav"
            with speech_slot(cancel_check):
                check_cancel(cancel_check)
                voice = PiperVoice.load(voice_path)
                # Bound each synthesis call so cancellation is checked during long scripts.
                chunks = textwrap.wrap(text, width=800, replace_whitespace=False)
                with wave.open(str(temporary), "wb") as wav:
                    for index, chunk in enumerate(chunks):
                        check_cancel(cancel_check)
                        if progress:
                            progress(f"Generating speech {index + 1}/{len(chunks)}…")
                        voice.synthesize_wav(chunk, wav, SynthesisConfig(length_scale=1 / speed),
                                             set_wav_format=index == 0)
                del voice
            check_cancel(cancel_check)
            return publish_output_file(temporary, output, overwrite, reservations)
    finally:
        release_output_path(output, reservations)
