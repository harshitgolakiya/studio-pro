"""Layout-preserving Office conversions with isolated LibreOffice profiles."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Callable

from studio_runtime import find_libreoffice, run_engine

WRITER_EXTENSIONS = {".doc", ".docx", ".docm", ".odt", ".ott", ".rtf", ".wps", ".fodt"}
PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".odp", ".otp", ".fodp"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".ods", ".ots", ".csv", ".tsv", ".fods"}
DRAWING_EXTENSIONS = {".odg", ".otg", ".fodg"}
OFFICE_EXTENSIONS = WRITER_EXTENSIONS | PRESENTATION_EXTENSIONS | SPREADSHEET_EXTENSIONS | DRAWING_EXTENSIONS

FILTERS = {
    "writer": {"PDF": "pdf:writer_pdf_Export", "DOCX": "docx:Office Open XML Text",
               "DOC": "doc:MS Word 97", "ODT": "odt:writer8", "RTF": "rtf:Rich Text Format",
               "HTML": "html:HTML (StarWriter)", "TXT": "txt:Text (encoded):UTF8"},
    "presentation": {"PDF": "pdf:impress_pdf_Export", "PPTX": "pptx:Impress MS PowerPoint 2007 XML",
                     "PPT": "ppt:MS PowerPoint 97", "ODP": "odp:impress8"},
    "spreadsheet": {"PDF": "pdf:calc_pdf_Export", "XLSX": "xlsx:Calc MS Excel 2007 XML",
                    "XLS": "xls:MS Excel 97", "ODS": "ods:calc8",
                    "CSV": "csv:Text - txt - csv (StarCalc):44,34,76,1",
                    "TSV": "tsv:Text - txt - csv (StarCalc):9,34,76,1"},
    "drawing": {"PDF": "pdf:draw_pdf_Export"},
}


def office_family(path: Path) -> str | None:
    ext = path.suffix.lower()
    for family, extensions in (("writer", WRITER_EXTENSIONS), ("presentation", PRESENTATION_EXTENSIONS),
                               ("spreadsheet", SPREADSHEET_EXTENSIONS), ("drawing", DRAWING_EXTENSIONS)):
        if ext in extensions:
            return family
    return None


def office_targets(path: Path) -> tuple[str, ...]:
    return tuple(FILTERS.get(office_family(path), {}))


# PDF pages opened as positioned text and graphics, then saved as Office files.
# target -> (import filter, export filter)
PDF_IMPORT_FILTERS = {
    "DOCX": ("writer_pdf_import", "docx:Office Open XML Text"),
    "ODT": ("writer_pdf_import", "odt:writer8"),
    "PPTX": ("impress_pdf_import", "pptx:Impress MS PowerPoint 2007 XML"),
    "ODP": ("impress_pdf_import", "odp:impress8"),
}


def render_office(source: Path, destination: Path, target: str,
                  cancel_check: Callable[[], bool] | None = None) -> None:
    import_filter = None
    if source.suffix.lower() == ".pdf":
        if target not in PDF_IMPORT_FILTERS:
            raise ValueError(f"PDF layout import supports: {', '.join(PDF_IMPORT_FILTERS)}")
        import_filter, filter_name = PDF_IMPORT_FILTERS[target]
    else:
        filter_name = FILTERS.get(office_family(source), {}).get(target)
    if not filter_name:
        raise ValueError(f"{source.suffix} cannot be converted to {target}. Choose: {', '.join(office_targets(source))}")
    engine = find_libreoffice()
    if not engine:
        raise RuntimeError("Office engine is missing. Run setup_studio.ps1 or install LibreOffice; "
                           "you can also set SHADOW_LIBREOFFICE to its soffice executable.")
    with tempfile.TemporaryDirectory(prefix="shadow-office-") as td:
        root = Path(td)
        # A unique writable profile prevents parallel jobs or an open desktop
        # LibreOffice session from intercepting this conversion.
        diagnostic = run_engine([engine, f"-env:UserInstallation={(root / 'profile').as_uri()}",
                                 "--headless", "--nologo", "--nodefault", "--norestore",
                                 *([f"--infilter={import_filter}"] if import_filter else []),
                                 "--convert-to", filter_name, "--outdir", str(root), str(source.resolve())],
                                cancel_check=cancel_check)
        generated = root / f"{source.stem}.{target.lower()}"
        if not generated.is_file() or generated.stat().st_size == 0:
            raise RuntimeError(f"LibreOffice did not produce a {target} file. The document may be damaged, "
                               f"password-protected, or unsupported. {diagnostic[-1000:]}")
        shutil.copyfile(generated, destination)
