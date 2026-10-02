"""PyInstaller collection shared by platform specs."""
from pathlib import Path
import importlib.util


def collect_studio():
    from PyInstaller.utils.hooks import collect_all
    datas, binaries, imports = [], [], []
    # Include native engines, voice data, CT2/ONNX DLLs, and PDFium resources.
    for package in ("pypdfium2", "pypdfium2_raw", "faster_whisper", "ctranslate2", "onnxruntime", "piper", "av", "tokenizers"):
        if importlib.util.find_spec(package) is not None:
            data, native, hidden = collect_all(package)
            datas.extend(data)
            binaries.extend(native)
            imports.extend(hidden)
    for folder in (Path("vendor/libreoffice"), Path("vendor/models")):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and ".cache" not in path.parts and path.suffix.lower() not in {".msi", ".log", ".download", ".lock"}:
                datas.append((str(path), str(path.parent)))
    if Path("vendor/models").is_dir():
        missing = [name for name in ("faster_whisper", "piper") if importlib.util.find_spec(name) is None]
        if missing:
            raise RuntimeError(f"Models exist but Studio packages are missing: {missing}. Install requirements-studio.txt")
    imports.extend(["studio_dialog", "studio_smoke", "studio_runtime", "office_engine", "speech_engine", "audio_tools", "pdf_tools", "document_preview", "pptx", "openpyxl"])
    return datas, binaries, imports
