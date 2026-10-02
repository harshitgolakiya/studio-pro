"""PyInstaller collection shared by platform specs."""
from pathlib import Path
import importlib.util
import sys


def collect_studio():
    from PyInstaller.utils.hooks import collect_all
    datas, binaries, imports = [], [], []
    # Include native engines, voice data, CT2/ONNX DLLs, and PDFium resources.
    for package in ("pypdfium2", "pypdfium2_raw", "faster_whisper", "ctranslate2", "onnxruntime", "piper", "av", "tokenizers",
                    "rapidocr", "sherpa_onnx", "sentencepiece", "py7zr", "pdfplumber", "pdfminer", "pyhanko",
                    "pyhanko_certvalidator", "jsonschema", "jsonschema_specifications"):
        if importlib.util.find_spec(package) is not None:
            data, native, hidden = collect_all(package)
            datas.extend(data)
            binaries.extend(native)
            imports.extend(hidden)
    for folder in (Path("vendor/libreoffice"), Path("vendor/models"), Path("vendor/ghostscript")):
        # macOS keeps LibreOffice's signed .app, framework symlinks, and native
        # layout intact via the post-build staging step.
        if sys.platform == "darwin" and folder.name == "libreoffice":
            continue
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and ".cache" not in path.parts and "$PLUGINSDIR" not in path.parts and path.suffix.lower() not in {".msi", ".log", ".download", ".lock", ".nsis"}:
                datas.append((str(path), str(path.parent)))
    if sys.platform == "darwin" and Path("vendor/ghostscript/bin/gs").is_file():
        binaries.append(("vendor/ghostscript/bin/gs", "vendor/ghostscript/bin"))
    if Path("THIRD_PARTY_NOTICES.md").is_file():
        datas.append(("THIRD_PARTY_NOTICES.md", "."))
    if Path("vendor/models").is_dir():
        missing = [name for name in ("faster_whisper", "piper") if importlib.util.find_spec(name) is None]
        if missing:
            raise RuntimeError(f"Models exist but Studio packages are missing: {missing}. Install requirements-studio.txt")
    imports.extend(["studio_dialog", "studio_smoke", "studio_runtime", "office_engine", "speech_engine", "audio_tools", "pdf_tools", "document_preview", "pptx", "openpyxl",
                    "ocr_engine", "pdf_advanced", "office_edit", "data_tools", "archive_tools", "model_catalog",
                    "translation_engine", "subtitle_tools", "studio_actions", "studio_expansion_ui",
                    "studio_workflows", "studio_workflow_ui", "agency_projects", "agency_ui", "agency_integrations", "print_tools",
                    "yaml", "defusedxml", "cv2"])
    return datas, binaries, imports
