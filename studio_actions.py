"""Shared, GUI-independent entry points for expanded Studio workflows."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from studio_runtime import check_cancel


ACTION_LABELS = {
    "ocr": "Recognize text / searchable PDF",
    "data-convert": "Convert data",
    "data-clean": "Clean data",
    "data-export-sheets": "Export every workbook sheet",
    "archive-create": "Create archive",
    "archive-extract": "Extract archive",
    "delivery-create": "Create delivery package",
    "delivery-verify": "Verify delivery package",
}
from studio_workflows import WORKFLOWS
ACTION_LABELS.update({key: definition[1] for key, definition in WORKFLOWS.items()})


@dataclass
class StudioResult:
    outputs: list[Path] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    ok: bool = True


def run_action(action: str, sources: list[Path], output_dir: Path, *, fmt: str | None = None,
               sheet: str | None = None, language: str | None = None, pages: str = "all",
               dpi: int = 200, force: bool = False, drop_duplicates: bool = False,
               normalize_headers: bool = False, client: str = "", project: str = "",
               options: dict | None = None,
               cancel_check: Callable[[], bool] | None = None,
               progress: Callable[[str], None] | None = None) -> StudioResult:
    """Keep originals and publish through each engine's collision-safe output API."""
    if action not in ACTION_LABELS:
        raise ValueError(f"Unknown Studio action: {action}")
    if action in WORKFLOWS:
        from studio_workflows import run_workflow
        return run_workflow(action, sources, output_dir, options, cancel_check, progress)
    if not sources or any(not source.exists() for source in sources):
        raise ValueError("Select existing input files or folders")
    check_cancel(cancel_check)
    options = options or {}
    if set(options) - {"password", "notes", "prepared_by"}:
        raise ValueError("Unsupported options for this action")
    password = options.get("password") or None
    if action in {"archive-create", "delivery-create"}:
        from archive_tools import create_archive, build_delivery_package
        extension = (fmt or "ZIP").lower()
        if extension not in {"zip", "7z", "tar", "tar.gz", "tar.xz"}:
            raise ValueError("Choose ZIP, 7Z, TAR, TAR.GZ, or TAR.XZ")
        destination = output_dir / f"{sources[0].stem}-{'delivery' if action == 'delivery-create' else 'archive'}.{extension}"
        if action == "delivery-create":
            path = build_delivery_package(sources, destination, client=client, project=project,
                                          password=password, notes=options.get("notes", ""), prepared_by=options.get("prepared_by", ""),
                                          cancel_check=cancel_check, progress=progress)
        else:
            path = create_archive(sources, destination, password=password, cancel_check=cancel_check, progress=progress)
        return StudioResult([path])
    if len(sources) != 1:
        raise ValueError("Select one input for this operation")
    source = sources[0]
    if not source.is_file():
        raise ValueError("Select a file for this operation")
    if action == "ocr":
        from ocr_engine import DEFAULT_OCR_LANGUAGE, ocr_document
        return StudioResult([ocr_document(source, output_dir, fmt or "TXT", language or DEFAULT_OCR_LANGUAGE,
                                           pages, dpi, force, cancel_check=cancel_check, progress=progress)])
    if action.startswith("data-"):
        from data_tools import DATA_WRITE_FORMATS, convert_data, clean_data, export_sheets
        target = (fmt or "CSV").upper()
        if target not in DATA_WRITE_FORMATS:
            raise ValueError(f"Choose a data format: {', '.join(DATA_WRITE_FORMATS)}")
        if action == "data-export-sheets":
            return StudioResult(export_sheets(source, output_dir, target, cancel_check=cancel_check))
        destination = output_dir / f"{source.stem}-{'clean' if action == 'data-clean' else 'data'}{DATA_WRITE_FORMATS[target]}"
        if action == "data-clean":
            path, report = clean_data(source, destination, sheet=sheet,
                                      drop_duplicates=drop_duplicates, normalize_headers=normalize_headers)
            return StudioResult([path], report)
        path, count = convert_data(source, destination, sheet=sheet)
        return StudioResult([path], {"rows_written": count})
    from archive_tools import extract_archive, verify_package
    if action == "archive-extract":
        return StudioResult([extract_archive(source, output_dir, password=password, cancel_check=cancel_check, progress=progress)])
    report = verify_package(source, password=password, cancel_check=cancel_check)
    return StudioResult(details=report, ok=report["ok"])
