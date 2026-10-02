"""Catalog of optional local models and the explicit downloads that install them.

Nothing here runs during a conversion. A model is fetched only when the user
asks for it in Studio Tools → Models or runs ``setup_studio_models.py``; after
that every engine works offline from ``vendor/models`` (or ``SHADOW_MODEL_DIR``).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Callable
import urllib.request

from studio_runtime import check_cancel, model_directory

_HF = "https://huggingface.co"
_USER_AGENT = "Shadow-Studio-Setup"
KIND_LABELS = {"whisper": "Transcription", "voice": "Voices", "ocr": "OCR scripts",
               "translation": "Translation", "diarization": "Speaker labels",
               "denoise": "Voice isolation", "color": "Print color"}


@dataclass(frozen=True)
class ModelEntry:
    key: str
    kind: str
    label: str
    language: str  # human-readable coverage
    size_mb: int   # approximate download size
    folder: str    # install location below the model directory
    marker: str    # file whose presence means "installed"
    repo: str = ""                                  # Hugging Face repository to mirror into ``folder``
    files: tuple[tuple[str, str], ...] = ()         # (url, file name) pairs
    archive: tuple[str, str, str] | None = None     # (url, member suffix, saved file name)
    sha256: str = ""                                # for single-file entries


def _voice(code: str, name: str, quality: str, language: str, size: int) -> ModelEntry:
    stem = f"{code}-{name}-{quality}"
    base = f"{_HF}/rhasspy/piper-voices/resolve/main/{code.split('_')[0]}/{code}/{name}/{quality}/"
    return ModelEntry(f"voice-{stem}", "voice", f"{language} — {name.title()}", language, size, "voices",
                      f"{stem}.onnx.json", files=((base + f"{stem}.onnx", f"{stem}.onnx"),
                                                  (base + f"{stem}.onnx.json", f"{stem}.onnx.json")))


def _whisper(name: str, repo: str, language: str, size: int) -> ModelEntry:
    return ModelEntry(f"whisper-{name}", "whisper", f"Whisper {name}", language, size, f"whisper-{name}",
                      "model.bin", repo=repo)


def _translation(source: str, target: str, repo: str, label: str, size: int) -> ModelEntry:
    return ModelEntry(f"translate-{source}-{target}", "translation", label, label, size,
                      f"translation/{source}-{target}", "model.bin", repo=repo)


LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
                  "nl": "Dutch", "ru": "Russian", "ar": "Arabic", "zh": "Chinese", "hi": "Hindi",
                  "ja": "Japanese", "tr": "Turkish", "uk": "Ukrainian", "pl": "Polish", "ko": "Korean",
                  "pt": "Portuguese", "sv": "Swedish", "id": "Indonesian", "vi": "Vietnamese"}

_TO_ENGLISH = {"es": "gaudi/opus-mt-es-en-ctranslate2", "fr": "gaudi/opus-mt-fr-en-ctranslate2",
               "de": "gaudi/opus-mt-de-en-ctranslate2", "it": "gaudi/opus-mt-it-en-ctranslate2",
               "nl": "gaudi/opus-mt-nl-en-ctranslate2", "ru": "gaudi/opus-mt-ru-en-ctranslate2",
               "ar": "gaudi/opus-mt-ar-en-ctranslate2", "zh": "gaudi/opus-mt-zh-en-ctranslate2",
               "hi": "gaudi/opus-mt-hi-en-ctranslate2", "ja": "gaudi/opus-mt-ja-en-ctranslate2",
               "tr": "gaudi/opus-mt-tr-en-ctranslate2", "uk": "gaudi/opus-mt-uk-en-ctranslate2",
               "pl": "gaudi/opus-mt-pl-en-ctranslate2", "ko": "gaudi/opus-mt-ko-en-ctranslate2",
               "sv": "gaudi/opus-mt-sv-en-ctranslate2", "id": "gaudi/opus-mt-id-en-ctranslate2",
               "vi": "gaudi/opus-mt-vi-en-ctranslate2"}
_FROM_ENGLISH = {"es": "michaelfeil/ct2fast-opus-mt-en-es", "fr": "michaelfeil/ct2fast-opus-mt-en-fr",
                 "de": "gaudi/opus-mt-en-de-ctranslate2", "it": "ooeoeo/opus-mt-en-it-ct2-float16",
                 "ru": "ooeoeo/opus-mt-en-ru-ct2-float16", "ar": "ooeoeo/opus-mt-en-ar-ct2-float16",
                 "zh": "gaudi/opus-mt-en-zh-ctranslate2", "vi": "gaudi/opus-mt-en-vi-ctranslate2"}

_OCR_FILES = {"Cyrillic": "cyrillic_PP-OCRv5_rec_mobile", "East Slavic": "eslav_PP-OCRv5_rec_mobile",
              "Arabic": "arabic_PP-OCRv5_rec_mobile", "Devanagari": "devanagari_PP-OCRv5_rec_mobile",
              "Korean": "korean_PP-OCRv5_rec_mobile", "Thai": "th_PP-OCRv5_rec_mobile",
              "Greek": "el_PP-OCRv5_rec_mobile", "Tamil": "ta_PP-OCRv5_rec_mobile",
              "Telugu": "te_PP-OCRv5_rec_mobile"}

_SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"


def _ocr_entries() -> list[ModelEntry]:
    """OCR recognition models, with URLs and checksums taken from the installed OCR package."""
    try:
        import rapidocr
        import yaml
        listing = yaml.safe_load((Path(rapidocr.__file__).parent / "default_models.yaml").read_text(encoding="utf-8"))
        models = listing["onnxruntime"]["PP-OCRv5"]["rec"]
    except Exception:
        return []
    entries = []
    for language, name in _OCR_FILES.items():
        details = models.get(name)
        if details:
            entries.append(ModelEntry(f"ocr-{name}", "ocr", f"{language} text", language, 16, "ocr", f"{name}.onnx",
                                      files=((details["model_dir"], f"{name}.onnx"),), sha256=details.get("SHA256", "")))
    return entries


def catalog() -> list[ModelEntry]:
    entries = [
        _whisper("base.en", "Systran/faster-whisper-base.en", "English only", 145),
        _whisper("base", "Systran/faster-whisper-base", "99 languages, fastest", 145),
        _whisper("small", "Systran/faster-whisper-small", "99 languages, balanced", 485),
        _whisper("medium", "Systran/faster-whisper-medium", "99 languages, accurate", 1530),
        _whisper("large-v3-turbo", "deepdml/faster-whisper-large-v3-turbo-ct2", "99 languages, best accuracy", 1620),
        _voice("en_US", "lessac", "medium", "English (US)", 63),
        _voice("en_US", "amy", "medium", "English (US)", 63),
        _voice("en_GB", "alan", "medium", "English (UK)", 63),
        _voice("es_ES", "davefx", "medium", "Spanish", 63),
        _voice("fr_FR", "siwis", "medium", "French", 63),
        _voice("de_DE", "thorsten", "medium", "German", 63),
        _voice("it_IT", "paola", "medium", "Italian", 63),
        _voice("pt_BR", "faber", "medium", "Portuguese (Brazil)", 63),
        _voice("nl_NL", "mls", "medium", "Dutch", 63),
        _voice("ru_RU", "irina", "medium", "Russian", 63),
        _voice("ar_JO", "kareem", "medium", "Arabic", 63),
        _voice("zh_CN", "huayan", "medium", "Chinese (Mandarin)", 63),
        _voice("hi_IN", "pratham", "medium", "Hindi", 63),
        *_ocr_entries(),
    ]
    for code, repo in _TO_ENGLISH.items():
        entries.append(_translation(code, "en", repo, f"{LANGUAGE_NAMES[code]} → English", 150))
    for code, repo in _FROM_ENGLISH.items():
        entries.append(_translation("en", code, repo, f"English → {LANGUAGE_NAMES[code]}", 150))
    entries += [
        ModelEntry("diarization-segmentation", "diarization", "Speaker change detection", "Any language", 7,
                   "diarization", "segmentation.onnx",
                   archive=(_SHERPA + "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
                            "/model.onnx", "segmentation.onnx")),
        ModelEntry("diarization-embedding", "diarization", "Speaker voice matching", "Any language", 38,
                   "diarization", "embedding.onnx",
                   files=((_SHERPA + "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
                           "embedding.onnx"),)),
        ModelEntry("denoise-speech", "denoise", "Speech isolation (RNNoise)", "Any language", 1, "denoise", "sh.rnnn",
                   files=(("https://raw.githubusercontent.com/GregorR/rnnoise-models/master/"
                           "somnolent-hogwash-2018-09-01/sh.rnnn", "sh.rnnn"),)),
        ModelEntry("color-cmyk", "color", "CMYK press profile (CGATS TR 001)", "Print", 1, "color",
                   "CGATS001Compat-v2-micro.icc",
                   files=(("https://raw.githubusercontent.com/saucecontrol/Compact-ICC-Profiles/master/profiles/"
                           "CGATS001Compat-v2-micro.icc", "CGATS001Compat-v2-micro.icc"),)),
    ]
    return entries


def find_entry(key: str) -> ModelEntry:
    for entry in catalog():
        if entry.key == key:
            return entry
    raise ValueError(f"Unknown model: {key}")


def entry_path(entry: ModelEntry) -> Path:
    return model_directory() / entry.folder


def is_installed(entry: ModelEntry) -> bool:
    return (entry_path(entry) / entry.marker).is_file()


def _owned_files(entry: ModelEntry) -> list[Path]:
    """Files this entry placed in a folder it shares with other entries."""
    folder = entry_path(entry)
    names = [name for _, name in entry.files]
    if entry.archive:
        names.append(entry.archive[2])
    return [folder / name for name in names]


def installed_bytes(entry: ModelEntry) -> int:
    if not is_installed(entry):
        return 0
    if entry.repo:
        return sum(p.stat().st_size for p in entry_path(entry).rglob("*") if p.is_file())
    return sum(p.stat().st_size for p in _owned_files(entry) if p.is_file())


def remove(entry: ModelEntry) -> None:
    """Delete an installed model. Only paths inside the model directory are touched."""
    folder = entry_path(entry).resolve()
    root = model_directory().resolve()
    if root not in folder.parents:
        raise ValueError("Refusing to remove a path outside the model directory")
    if entry.repo:
        shutil.rmtree(folder, ignore_errors=True)
    else:
        for path in _owned_files(entry):
            path.unlink(missing_ok=True)


def _download(url: str, destination: Path, sha256: str = "", label: str = "",
              progress: Callable[[str], None] | None = None,
              cancel_check: Callable[[], bool] | None = None) -> None:
    """Stream to a ``.download`` sibling, verify, then move into place."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as stream:
            total = int(response.headers.get("Content-Length") or 0)
            received, reported = 0, -1
            while chunk := response.read(1024 * 256):
                check_cancel(cancel_check)
                stream.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                percent = int(received * 100 / total) if total else received // (1024 * 1024)
                if progress and percent != reported:
                    reported = percent
                    progress(f"Downloading {label or destination.name}: "
                             + (f"{percent}%" if total else f"{percent} MB"))
        if sha256 and digest.hexdigest().lower() != sha256.lower():
            raise RuntimeError(f"Checksum mismatch for {destination.name}; the download was discarded")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _repository_files(repo: str) -> list[str]:
    request = urllib.request.Request(f"{_HF}/api/models/{repo}", headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        listing = json.load(response)
    names = [item["rfilename"] for item in listing.get("siblings", [])]
    return [name for name in names if not name.startswith(".") and name.lower() != "readme.md"]


def install(entry: ModelEntry, progress: Callable[[str], None] | None = None,
            cancel_check: Callable[[], bool] | None = None) -> Path:
    """Download one model. A partial install never leaves the marker file behind."""
    folder = entry_path(entry)
    check_cancel(cancel_check)
    try:
        if entry.repo:
            names = _repository_files(entry.repo)
            if entry.marker not in names:
                raise RuntimeError(f"{entry.repo} does not provide {entry.marker}")
            # The marker goes last so an interrupted install is not mistaken for a complete one.
            for name in sorted(names, key=lambda item: item == entry.marker):
                _download(f"{_HF}/{entry.repo}/resolve/main/{name}", folder / name, label=f"{entry.label} ({name})",
                          progress=progress, cancel_check=cancel_check)
        elif entry.archive:
            url, member_suffix, saved = entry.archive
            with tempfile.TemporaryDirectory(prefix="shadow-model-") as td:
                packed = Path(td) / "model.tar.bz2"
                _download(url, packed, label=entry.label, progress=progress, cancel_check=cancel_check)
                with tarfile.open(packed) as archive:
                    member = next((m for m in archive if m.isfile() and ("/" + m.name).endswith(member_suffix)), None)
                    if member is None:
                        raise RuntimeError(f"{entry.label}: the download does not contain {member_suffix}")
                    folder.mkdir(parents=True, exist_ok=True)
                    temporary = folder / (saved + ".download")
                    try:
                        with archive.extractfile(member) as source, temporary.open("wb") as stream:
                            shutil.copyfileobj(source, stream)
                        temporary.replace(folder / saved)
                    finally:
                        temporary.unlink(missing_ok=True)
        else:
            for url, name in sorted(entry.files, key=lambda item: item[1] == entry.marker):
                _download(url, folder / name, sha256=entry.sha256, label=entry.label,
                          progress=progress, cancel_check=cancel_check)
    except OSError as exc:
        raise RuntimeError(f"Could not download {entry.label}. Check the internet connection and try again. ({exc})")
    if not is_installed(entry):
        raise RuntimeError(f"{entry.label} did not install correctly")
    return folder
