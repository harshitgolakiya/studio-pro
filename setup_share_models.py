"""Stage the default offline models for a compact, shareable installer."""
from model_catalog import find_entry, install, is_installed

DEFAULT_MODELS = (
    "voice-kokoro-v1", "whisper-base.en", "whisper-base",
    "diarization-segmentation", "diarization-embedding", "denoise-speech", "color-cmyk",
)

if __name__ == "__main__":
    for key in DEFAULT_MODELS:
        entry = find_entry(key)
        if not is_installed(entry):
            print(f"Installing {key}", flush=True)
            install(entry, progress=lambda message: print(message, flush=True))
    from setup_model_notices import main
    main()
