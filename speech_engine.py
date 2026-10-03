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
    speaker: str = ""


# Spoken languages offered in the UI; any Whisper language code also works.
SPEECH_LANGUAGES = {
    "Auto-detect": None, "English": "en", "Spanish": "es", "French": "fr", "German": "de", "Italian": "it",
    "Portuguese": "pt", "Dutch": "nl", "Russian": "ru", "Ukrainian": "uk", "Polish": "pl", "Turkish": "tr",
    "Arabic": "ar", "Hindi": "hi", "Urdu": "ur", "Chinese": "zh", "Japanese": "ja", "Korean": "ko",
    "Indonesian": "id", "Vietnamese": "vi", "Swedish": "sv",
}


def timestamp(seconds: float, separator: str = ",") -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def format_transcript(segments: list[TranscriptSegment], fmt: str) -> str:
    if fmt == "TXT":
        lines, previous = [], None
        for s in segments:
            # Name the speaker once per turn, not on every line.
            if s.speaker and s.speaker != previous:
                lines.append(f"{s.speaker}: {s.text.strip()}")
            else:
                lines.append(s.text.strip())
            previous = s.speaker
        return "\n".join(lines) + "\n"
    if fmt == "JSON":
        return json.dumps([{"start": s.start, "end": s.end, "text": s.text.strip(),
                            **({"speaker": s.speaker} if s.speaker else {})}
                           for s in segments], ensure_ascii=False, indent=2)
    if fmt not in {"SRT", "VTT"}:
        raise ValueError(f"Unsupported transcript format: {fmt}")
    sep = "," if fmt == "SRT" else "."
    blocks = []
    for index, s in enumerate(segments, 1):
        text = s.text.strip().replace("-->", "→")
        if s.speaker:
            text = f"<v {s.speaker}>{text}" if fmt == "VTT" else f"[{s.speaker}] {text}"
        blocks.append(f"{index}\n{timestamp(s.start, sep)} --> {timestamp(s.end, sep)}\n{text}\n")
    return ("WEBVTT\n\n" if fmt == "VTT" else "") + "\n".join(blocks)


def available_whisper_models() -> dict[str, Path]:
    """Installed transcription models by name, e.g. ``{"base.en": ..., "small": ...}``."""
    root = model_directory()
    if not root.is_dir():
        return {}
    return {path.name.removeprefix("whisper-"): path for path in sorted(root.glob("whisper-*"))
            if (path / "model.bin").is_file()}


def default_whisper_model() -> Path:
    """The user's preferred installed model, else English base, else any installed model."""
    models = available_whisper_models()
    try:
        from settings import load_settings
        preferred = str(load_settings().get("studio_whisper_model", ""))
    except Exception:
        preferred = ""
    for name in (preferred, "base.en"):
        if name in models:
            return models[name]
    return next(iter(models.values()), model_directory() / "whisper-base.en")


def available_voices() -> list[Path]:
    from natural_speech import voice_ready
    root = model_directory()
    return [path for path in sorted((root / 'kokoro-v1' / 'voices').glob('*.voice.json')) if voice_ready(path)] + sorted((root / "voices").glob("*.onnx"))


def default_voice() -> Path | None:
    voices = available_voices()
    try:
        from settings import load_settings
        preferred = str(load_settings().get("studio_voice", ""))
    except Exception:
        preferred = ""
    for voice in voices:
        if voice.stem == preferred:
            return voice
    return next((voice for voice in voices if voice.name == 'af_heart.voice.json'),
                next((voice for voice in voices if voice.stem.startswith("en_US-lessac")), voices[0] if voices else None))


def diarization_models() -> tuple[Path, Path]:
    folder = model_directory() / "diarization"
    return folder / "segmentation.onnx", folder / "embedding.onnx"


def _decode_mono_16k(source: Path, cancel_check) -> "object":
    """Decode any media file to 16 kHz mono float samples."""
    import numpy as np
    from media_engine import get_ffmpeg_path
    from studio_runtime import run_engine
    engine = get_ffmpeg_path()
    if not engine:
        raise RuntimeError("FFmpeg is missing. Run fetch_ffmpeg.ps1")
    with tempfile.TemporaryDirectory(prefix="shadow-speakers-") as td:
        decoded = Path(td) / "audio.wav"
        run_engine([engine, "-hide_banner", "-nostdin", "-y", "-i", str(source.resolve()), "-map", "0:a:0", "-vn",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(decoded)], timeout=3600,
                   cancel_check=cancel_check)
        with wave.open(str(decoded)) as wav:
            return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def detect_speakers(source: Path, speaker_count: int | None = None,
                    cancel_check: Callable[[], bool] | None = None) -> list[tuple[float, float, int]]:
    """Speaker turns as ``(start, end, speaker_index)``, ordered by start time."""
    segmentation, embedding = diarization_models()
    if not segmentation.is_file() or not embedding.is_file():
        raise RuntimeError("Speaker label models are not installed. Add them in Studio Tools → Models, "
                           "or run setup_studio.ps1.")
    if speaker_count is not None and not 1 <= speaker_count <= 20:
        raise ValueError("Speaker count must be between 1 and 20")
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError("Speaker labelling engine is missing. Install requirements-studio.txt") from exc
    samples = _decode_mono_16k(source, cancel_check)
    check_cancel(cancel_check)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation))),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding)),
        # A fixed count is used when given; otherwise voices are grouped by similarity.
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speaker_count or -1, threshold=0.5),
        min_duration_on=0.3, min_duration_off=0.5)
    if not config.validate():
        raise RuntimeError("Speaker label models could not be loaded. Reinstall them in Studio Tools → Models.")
    turns = sherpa_onnx.OfflineSpeakerDiarization(config).process(samples).sort_by_start_time()
    return [(float(turn.start), float(turn.end), int(turn.speaker)) for turn in turns]


def label_speakers(segments: list[TranscriptSegment],
                   turns: list[tuple[float, float, int]]) -> list[TranscriptSegment]:
    """Give each segment the speaker who talks for most of it, numbered in order of first appearance."""
    names: dict[int, str] = {}
    labelled = []
    for segment in segments:
        overlap: dict[int, float] = {}
        for start, end, speaker in turns:
            shared = min(segment.end, end) - max(segment.start, start)
            if shared > 0:
                overlap[speaker] = overlap.get(speaker, 0.0) + shared
        if not overlap:
            labelled.append(segment)
            continue
        speaker = max(overlap, key=overlap.get)
        names.setdefault(speaker, f"Speaker {len(names) + 1}")
        labelled.append(TranscriptSegment(segment.start, segment.end, segment.text, names[speaker]))
    return labelled


def transcribe_media(source: Path, output_dir: Path, fmt: str = "TXT",
                     model_path: Path | None = None, language: str | None = "en",
                     overwrite: bool = False, cancel_check: Callable[[], bool] | None = None,
                     progress: Callable[[str], None] | None = None, translate: bool = False,
                     speakers: bool = False, speaker_count: int | None = None) -> ConversionResult:
    """Transcribe speech. ``translate`` writes English from any spoken language;
    ``speakers`` labels who is talking."""
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
        if speakers and not all(path.is_file() for path in diarization_models()):
            raise RuntimeError("Speaker label models are not installed. Add them in Studio Tools → Models, "
                               "or run setup_studio.ps1.")
        from faster_whisper import WhisperModel
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = "-english" if translate else "-transcript"
        output = reserve_output_path(output_dir / f"{source.stem}{suffix}.{fmt.lower()}", overwrite, reservations)
        with speech_slot(cancel_check):
            check_cancel(cancel_check)
            if progress:
                progress("Loading local speech recognition model…")
            model = WhisperModel(str(model_path), device="cpu", compute_type="int8", local_files_only=True,
                                 cpu_threads=4, num_workers=1)
            if not model.model.is_multilingual and (translate or language not in (None, "en")):
                raise ValueError("The selected transcription model is English-only. Install a multilingual "
                                 "model in Studio Tools → Models and select it.")
            iterator, _info = model.transcribe(str(source), language=language, vad_filter=True, beam_size=5,
                                               task="translate" if translate else "transcribe")
            segments = []
            for segment in iterator:
                check_cancel(cancel_check)
                segments.append(TranscriptSegment(segment.start, segment.end, segment.text))
                if progress:
                    progress(f"Transcribed through {timestamp(segment.end, '.')}")
            del model
            if speakers and segments:
                if progress:
                    progress("Identifying speakers…")
                segments = label_speakers(segments, detect_speakers(source, speaker_count, cancel_check))
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


def transcribe_batch(sources: list[Path], output_dir: Path,
                     on_result: Callable[[ConversionResult], None] | None = None,
                     cancel_check: Callable[[], bool] | None = None,
                     progress: Callable[[str], None] | None = None, **options) -> list[ConversionResult]:
    """Transcribe a queue of recordings one after another. A failed file does not stop the rest."""
    results = []
    for number, source in enumerate(sources, 1):
        if cancel_check and cancel_check():
            result = ConversionResult(source, None, None, None, "-", "Cancelled")
        else:
            def report(message: str, number=number, source=source) -> None:
                if progress:
                    progress(f"[{number}/{len(sources)}] {source.name}: {message}")
            result = transcribe_media(source, output_dir, cancel_check=cancel_check, progress=report, **options)
        results.append(result)
        if on_result:
            on_result(result)
    return results


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
    voice_path = Path(voice_path) if voice_path else default_voice()
    from natural_speech import voice_ready, synthesize_kokoro, speech_chunks
    if voice_path is None or not voice_ready(voice_path):
        raise RuntimeError("Voice model missing. Run setup_studio.ps1 or select a Piper .onnx voice with its .onnx.json configuration.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reservations: set[Path] = set()
    output = reserve_output_path(destination, overwrite, reservations)
    try:
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".shadow-voice-") as td:
            temporary = Path(td) / "voice.wav"
            with speech_slot(cancel_check):
                check_cancel(cancel_check)
                if voice_path.name.endswith('.voice.json'):
                    synthesize_kokoro(text, temporary, voice_path, speed, cancel_check, progress)
                else:
                    from piper import PiperVoice, SynthesisConfig
                    voice = PiperVoice.load(voice_path)
                    # Bound each synthesis call so cancellation is checked during long scripts.
                    chunks = speech_chunks(text)
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
