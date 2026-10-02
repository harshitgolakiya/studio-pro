"""Non-destructive PDF operations and local page rendering."""
from __future__ import annotations

import io
from pathlib import Path
import tempfile
import threading
from typing import Callable
import zipfile

from studio_runtime import check_cancel
from utils import publish_output_file, reserve_output_path, release_output_path

_render_lock = threading.Lock()  # PDFium's C API is not thread safe


def parse_pages(value: str, count: int) -> list[int]:
    """One-based inclusive UI ranges to ordered zero-based indices."""
    if not value.strip() or value.strip().lower() == "all":
        return list(range(count))
    result = []
    for part in value.split(","):
        limits = part.strip().split("-")
        if len(limits) > 2 or not all(n.strip().isdigit() for n in limits):
            raise ValueError("Use page numbers and ranges, such as 1,3-5")
        first = int(limits[0])
        last = int(limits[-1])
        if first < 1 or last < first or last > count:
            raise ValueError(f"Page range must be between 1 and {count}")
        for index in range(first - 1, last):
            if index not in result:
                result.append(index)
    return result


def read_pdf(path: Path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("This PDF is password-protected. Open an unlocked copy first.")
    return reader


def render_pdf_page(source: Path | bytes, index: int = 0, scale: float = 1.4):
    import pypdfium2 as pdfium
    if not 0.1 <= scale <= 4:
        raise ValueError("Render scale must be between 0.1 and 4")
    with _render_lock:
        with pdfium.PdfDocument(str(source) if isinstance(source, Path) else source) as document:
            count = len(document)
            if index < 0 or index >= count:
                raise ValueError("Page number is out of range")
            page = document[index]
            try:
                # Bound output allocation for PDFs with oversized page boxes.
                width, height = page.get_size()
                scale = min(scale, 2400 / max(width, height))
                bitmap = page.render(scale=scale)
                try:
                    return bitmap.to_pil().copy(), count
                finally:
                    bitmap.close()
            finally:
                page.close()


def process_pdf(sources: list[Path], destination: Path, operation: str = "merge",
                pages: str = "all", rotation: int = 90, overwrite: bool = False,
                cancel_check: Callable[[], bool] | None = None) -> Path:
    """Merge, extract, rotate, losslessly compress, or export page PNGs as ZIP."""
    if not sources or operation not in {"merge", "extract", "rotate", "compress", "images"}:
        raise ValueError("Choose PDF inputs and a supported operation")
    if operation != "merge" and len(sources) != 1:
        raise ValueError("Select one PDF for this operation")
    expected = ".zip" if operation == "images" else ".pdf"
    if destination.suffix.lower() != expected:
        raise ValueError(f"This operation requires a {expected} output")
    if rotation not in {90, 180, 270}:
        raise ValueError("Rotation must be 90, 180, or 270 degrees")
    if destination.resolve() in {source.resolve() for source in sources}:
        raise ValueError("Choose a new output path to keep your original PDFs")
    from pypdf import PdfWriter
    destination.parent.mkdir(parents=True, exist_ok=True)
    reservations: set[Path] = set()
    output = reserve_output_path(destination, overwrite, reservations)
    try:
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".shadow-pdf-") as td:
            temporary = Path(td) / ("result" + expected)
            check_cancel(cancel_check)
            if operation == "images":
                reader = read_pdf(sources[0])
                indices = parse_pages(pages, len(reader.pages))
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for index in indices:
                        check_cancel(cancel_check)
                        image, _ = render_pdf_page(sources[0], index, scale=2)
                        try:
                            buffer = io.BytesIO()
                            image.save(buffer, format="PNG")
                            archive.writestr(f"page-{index + 1:04}.png", buffer.getvalue())
                        finally:
                            image.close()
            else:
                original = read_pdf(sources[0]) if operation in {"rotate", "compress"} else None
                writer = PdfWriter(clone_from=original) if original is not None else PdfWriter()
                try:
                    if original is not None:
                        for index in parse_pages(pages, len(writer.pages)):
                            check_cancel(cancel_check)
                            page = writer.pages[index]
                            if operation == "rotate":
                                page.rotate(rotation)
                            else:
                                page.compress_content_streams()
                    else:
                        for source in sources:
                            check_cancel(cancel_check)
                            reader = read_pdf(source)
                            for index in parse_pages(pages, len(reader.pages)):
                                check_cancel(cancel_check)
                                writer.add_page(reader.pages[index])
                    with temporary.open("wb") as stream:
                        writer.write(stream)
                finally:
                    writer.close()
            check_cancel(cancel_check)
            return publish_output_file(temporary, output, overwrite, reservations)
    finally:
        release_output_path(output, reservations)
