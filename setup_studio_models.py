"""Explicit one-time download of English speech models for offline deployment."""
from pathlib import Path
import urllib.request

from studio_runtime import model_directory


def main() -> None:
    from huggingface_hub import snapshot_download
    root = model_directory()
    print("Downloading English transcription model…", flush=True)
    snapshot_download("Systran/faster-whisper-base.en", local_dir=root / "whisper-base.en")
    voice_dir = root / "voices"
    voice_dir.mkdir(parents=True, exist_ok=True)
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/"
    for name in ("en_US-lessac-medium.onnx", "en_US-lessac-medium.onnx.json", "MODEL_CARD"):
        destination = voice_dir / name
        if destination.is_file():
            continue
        print(f"Downloading {name}…", flush=True)
        temporary = destination.with_suffix(destination.suffix + ".download")
        try:
            urllib.request.urlretrieve(base + name, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    # Small models behind speaker labels, voice isolation, and CMYK delivery.
    from model_catalog import find_entry, install, is_installed
    for key in ("diarization-segmentation", "diarization-embedding", "denoise-speech", "color-cmyk"):
        entry = find_entry(key)
        if not is_installed(entry):
            print(f"Downloading {entry.label}…", flush=True)
            install(entry)
    print(f"Models ready: {root}", flush=True)


if __name__ == "__main__":
    main()
