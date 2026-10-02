"""Local OCR for scans and screenshots: extracted text and searchable PDFs.

Recognition runs on ONNX models that are already on disk. The multilingual
model shipped with the OCR package covers Latin scripts, Chinese, and Japanese;
other scripts use recognition models staged by setup or the model manager.
Nothing is downloaded during a conversion.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
import tempfile
import threading
from typing import Callable

from studio_runtime import check_cancel, model_directory
from utils import publish_output_file, release_output_path, reserve_output_path

OCR_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
OCR_EXTENSIONS = OCR_IMAGE_EXTENSIONS | {".pdf"}
OCR_FORMATS = {"TXT": ".txt", "MD": ".md", "JSON": ".json", "PDF": ".pdf"}

# Label -> recognition model file under <models>/ocr. None is the bundled model.
OCR_LANGUAGES: dict[str, str | None] = {
    "Latin, Chinese, Japanese": None,
    "Cyrillic": "cyrillic_PP-OCRv5_rec_mobile.onnx",
    "East Slavic": "eslav_PP-OCRv5_rec_mobile.onnx",
    "Arabic": "arabic_PP-OCRv5_rec_mobile.onnx",
    "Devanagari": "devanagari_PP-OCRv5_rec_mobile.onnx",
    "Korean": "korean_PP-OCRv5_rec_mobile.onnx",
    "Thai": "th_PP-OCRv5_rec_mobile.onnx",
    "Greek": "el_PP-OCRv5_rec_mobile.onnx",
    "Tamil": "ta_PP-OCRv5_rec_mobile.onnx",
    "Telugu": "te_PP-OCRv5_rec_mobile.onnx",
}
DEFAULT_OCR_LANGUAGE = "Latin, Chinese, Japanese"

# A page that already carries this much text is treated as born-digital.
_TEXT_PAGE_THRESHOLD = 24
_MAX_RENDER_SIDE = 3600

_ocr_lock = threading.Lock()  # one recognition at a time bounds CPU and memory
_engines: dict[str, object] = {}

# 652-byte TrueType font whose single glyph is a half-em box. Invisible text
# needs a font object, a real typeface would drop every character it has no
# glyph for, and the box gives each character a selectable, searchable area.
_GLYPHLESS_FONT = base64.b64decode(
    "AAEAAAAKAIAAAwAgT1MvMkUAQ7AAAAEoAAAAYGNtYXAADABzAAABkAAAADRnbHlmA24B+AAAAcwAAAAaaGVhZC7WHWIAAACs"
    "AAAANmhoZWEFFgEuAAAA5AAAACRobXR4AfQAAAAAAYgAAAAGbG9jYQANAAAAAAHEAAAABm1heHAABAAGAAABCAAAACBuYW1l"
    "/vF1kAAAAegAAAB4cG9zdHB+A2IAAAJgAAAAKgABAAAAAQAAyeLhX18PPPUAAwPoAAAAAOblbRUAAAAA5uVtFQAA/zgB9AMg"
    "AAAAAwACAAAAAAAAAAEAAAMg/zgAAAH0AAAAAAH0AAEAAAAAAAAAAAAAAAAAAAABAAEAAAACAAQAAQAAAAAAAgAAAAAAAAAA"
    "AAAAAAAAAAAAAwH0AZAABQAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAPz8/PwAA"
    "ACAAIAMg/zgAAAMgAMgAAAAAAAAAAAAAAAAAAAAgAAAB9AAAAAAAAAAAAAIAAAADAAAAFAADAAEAAAAUAAQAIAAAAAQABAAB"
    "AAAAIP//AAAAIP///+EAAQAAAAAAAAAAAA0AAAABAAD/OAH0AyAAAwAAFREhEQH0yAPo/BgAAAAAAAAEADYAAQAAAAAAAQAP"
    "AAAAAQAAAAAAAgAHAA8AAwABBAkAAQAeABYAAwABBAkAAgAOADRTaGFkb3dHbHlwaGxlc3NSZWd1bGFyAFMAaABhAGQAbwB3"
    "AEcAbAB5AHAAaABsAGUAcwBzAFIAZQBnAHUAbABhAHIAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAABAgNi"
    "b3gAAA=="
)
_TO_UNICODE = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
               b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def "
               b"/CMapName /Adobe-Identity-UCS def /CMapType 2 def "
               b"1 begincodespacerange <0000> <FFFF> endcodespacerange "
               b"1 beginbfrange <0000> <FFFF> <0000> endbfrange "
               b"endcmap CMapName currentdict /CMap defineresource pop end end")


@dataclass(frozen=True)
class OcrLine:
    text: str
    score: float
    box: tuple[tuple[float, float], ...]  # four corners in image pixels, clockwise from top-left


def ocr_model_directory() -> Path:
    return model_directory() / "ocr"


def ocr_language_ready(language: str) -> bool:
    if language not in OCR_LANGUAGES:
        return False
    name = OCR_LANGUAGES[language]
    return name is None or (ocr_model_directory() / name).is_file()


def available_ocr_languages() -> list[str]:
    return [label for label in OCR_LANGUAGES if ocr_language_ready(label)]


def _engine(language: str):
    if language not in OCR_LANGUAGES:
        raise ValueError(f"Unknown OCR language: {language}. Choose: {', '.join(OCR_LANGUAGES)}")
    if language not in _engines:
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise RuntimeError("OCR engine is missing. Install requirements-studio.txt") from exc
        params: dict[str, object] = {"Global.log_level": "error",
                                     "EngineConfig.onnxruntime.intra_op_num_threads": 4,
                                     "EngineConfig.onnxruntime.inter_op_num_threads": 1}
        name = OCR_LANGUAGES[language]
        if name is not None:
            model = ocr_model_directory() / name
            if not model.is_file():
                raise RuntimeError(f"The {language} OCR model is not installed. "
                                   "Add it in Studio Tools → Models, or run setup_studio.ps1.")
            params["Rec.model_path"] = str(model)
        _engines[language] = RapidOCR(params=params)
    return _engines[language]


def recognize_image(image, language: str = DEFAULT_OCR_LANGUAGE,
                    cancel_check: Callable[[], bool] | None = None) -> list[OcrLine]:
    """Recognize one PIL image and return its lines in reading order."""
    import numpy as np
    check_cancel(cancel_check)
    pixels = np.array(image.convert("RGB"))
    while not _ocr_lock.acquire(timeout=0.1):
        check_cancel(cancel_check)
    try:
        result = _engine(language)(pixels)
    finally:
        _ocr_lock.release()
    if result.boxes is None or result.txts is None:
        return []
    lines = [OcrLine(str(text), float(score), tuple((float(x), float(y)) for x, y in box))
             for box, text, score in zip(result.boxes, result.txts, result.scores) if str(text).strip()]
    return _reading_order(lines)


def _reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    """Top-to-bottom rows, left-to-right inside a row."""
    def top(line):
        return min(y for _, y in line.box)

    def height(line):
        return max(y for _, y in line.box) - top(line)

    ordered: list[OcrLine] = []
    row: list[OcrLine] = []
    for line in sorted(lines, key=top):
        if row and top(line) - top(row[0]) > 0.6 * max(height(row[0]), 1):
            ordered.extend(sorted(row, key=lambda item: min(x for x, _ in item.box)))
            row = []
        row.append(line)
    ordered.extend(sorted(row, key=lambda item: min(x for x, _ in item.box)))
    return ordered


def lines_to_text(lines: list[OcrLine]) -> str:
    return "\n".join(line.text for line in lines)


def _open_frames(source: Path):
    """Yield (image, dpi) for each frame of an image file."""
    from PIL import Image, ImageOps, ImageSequence
    with Image.open(source) as opened:
        for frame in ImageSequence.Iterator(opened):
            image = ImageOps.exif_transpose(frame).convert("RGB")
            dpi = opened.info.get("dpi", (0, 0))[0] or 0
            yield image, float(dpi) if 50 <= float(dpi) <= 1200 else 200.0


def _text_overlay(width: float, height: float, lines: list[OcrLine], scale: float) -> bytes:
    """One-page PDF holding only invisible text positioned over the scan."""
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject,
                               NameObject, NumberObject, TextStringObject)
    commands = []
    for line in lines:
        (x0, y0), (x1, y1), _, (x3, y3) = line.box
        box_width = math.hypot(x1 - x0, y1 - y0) / scale
        box_height = math.hypot(x3 - x0, y3 - y0) / scale
        units = line.text.encode("utf-16-be")
        if box_width <= 0 or box_height <= 0 or not units:
            continue
        size = max(1.0, box_height)
        # Every glyph of the box font is half an em wide; stretch to the line.
        stretch = 100 * box_width / (len(units) / 2 * size * 0.5)
        angle = math.atan2(-(y1 - y0), x1 - x0)
        cos, sin = math.cos(angle), math.sin(angle)
        # The glyph box descends 0.2 em, so lift the baseline to fill the detected box.
        left, bottom = x3 / scale - 0.2 * size * sin, height - y3 / scale + 0.2 * size * cos
        commands.append(f"BT 3 Tr /F1 {size:.2f} Tf {cos:.4f} {sin:.4f} {-sin:.4f} {cos:.4f} "
                        f"{left:.2f} {bottom:.2f} Tm {stretch:.2f} Tz <{units.hex()}> Tj ET")
    writer = PdfWriter()
    try:
        page = writer.add_blank_page(width=width, height=height)
        font_file = DecodedStreamObject()
        font_file.set_data(_GLYPHLESS_FONT)
        font_file[NameObject("/Length1")] = NumberObject(len(_GLYPHLESS_FONT))
        cid_map = DecodedStreamObject()
        cid_map.set_data(b"\x00\x01" * 65536)  # every character draws glyph 1, the box
        to_unicode = DecodedStreamObject()
        to_unicode.set_data(_TO_UNICODE)
        descriptor = DictionaryObject({
            NameObject("/Type"): NameObject("/FontDescriptor"), NameObject("/FontName"): NameObject("/ShadowGlyphless"),
            NameObject("/Flags"): NumberObject(5), NameObject("/ItalicAngle"): NumberObject(0),
            NameObject("/FontBBox"): ArrayObject([NumberObject(0), NumberObject(-200), NumberObject(500), NumberObject(800)]),
            NameObject("/Ascent"): NumberObject(800), NameObject("/Descent"): NumberObject(-200),
            NameObject("/CapHeight"): NumberObject(800), NameObject("/StemV"): NumberObject(80),
            NameObject("/FontFile2"): writer._add_object(font_file),
        })
        descendant = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/CIDFontType2"),
            NameObject("/BaseFont"): NameObject("/ShadowGlyphless"),
            NameObject("/CIDSystemInfo"): DictionaryObject({
                NameObject("/Registry"): TextStringObject("Adobe"), NameObject("/Ordering"): TextStringObject("Identity"),
                NameObject("/Supplement"): NumberObject(0)}),
            NameObject("/FontDescriptor"): writer._add_object(descriptor),
            NameObject("/DW"): NumberObject(500),
            NameObject("/CIDToGIDMap"): writer._add_object(cid_map),
        })
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/ShadowGlyphless"), NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/DescendantFonts"): ArrayObject([writer._add_object(descendant)]),
            NameObject("/ToUnicode"): writer._add_object(to_unicode),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
        page.mediabox.upper_right = (FloatObject(width), FloatObject(height))
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    finally:
        writer.close()


def _render_scale(width: float, height: float, dpi: int) -> float:
    return min(dpi / 72, _MAX_RENDER_SIDE / max(width, height, 1))


def _recognize_pdf_pages(source: Path, pages: str, language: str, dpi: int, force: bool,
                         cancel_check, progress):
    """Yield (index, page_text, lines, scale) for each requested page.

    ``lines`` is None for a page that already has a text layer and was left alone.
    """
    from pdf_tools import parse_pages, read_pdf, render_pdf_page
    reader = read_pdf(source)
    indices = parse_pages(pages, len(reader.pages))
    for position, index in enumerate(indices, 1):
        check_cancel(cancel_check)
        existing = (reader.pages[index].extract_text() or "").strip()
        if not force and len(existing) >= _TEXT_PAGE_THRESHOLD:
            yield index, existing, None, 1.0
            continue
        if progress:
            progress(f"Recognizing page {position} of {len(indices)}…")
        box = reader.pages[index].cropbox
        scale = _render_scale(float(box.width), float(box.height), dpi)
        image, _ = render_pdf_page(source, index, scale=min(scale, 4))
        try:
            # render_pdf_page may lower the scale for oversized pages.
            actual = image.width / max(float(box.width), 1) if reader.pages[index].rotation % 180 == 0 \
                else image.width / max(float(box.height), 1)
            lines = recognize_image(image, language, cancel_check)
        finally:
            image.close()
        yield index, lines_to_text(lines), lines, actual


def extract_text(source: Path, language: str = DEFAULT_OCR_LANGUAGE, pages: str = "all", dpi: int = 200,
                 force: bool = False, cancel_check: Callable[[], bool] | None = None,
                 progress: Callable[[str], None] | None = None) -> list[dict]:
    """Return one record per page/frame: page number, text, and recognized lines."""
    extension = source.suffix.lower()
    if extension not in OCR_EXTENSIONS:
        raise ValueError(f"OCR reads images and PDFs, not {extension or 'this file'}")
    if not source.is_file():
        raise FileNotFoundError("The selected file no longer exists")
    records = []
    if extension == ".pdf":
        for index, text, lines, _ in _recognize_pdf_pages(source, pages, language, dpi, force, cancel_check, progress):
            records.append({"page": index + 1, "text": text, "ocr": lines is not None,
                            "lines": [{"text": l.text, "score": round(l.score, 4), "box": l.box} for l in lines or []]})
    else:
        for number, (image, _) in enumerate(_open_frames(source), 1):
            check_cancel(cancel_check)
            if progress:
                progress(f"Recognizing image {number}…")
            lines = recognize_image(image, language, cancel_check)
            records.append({"page": number, "text": lines_to_text(lines), "ocr": True,
                            "lines": [{"text": l.text, "score": round(l.score, 4), "box": l.box} for l in lines]})
    return records


def _searchable_pdf(source: Path, temporary: Path, language: str, pages: str, dpi: int, force: bool,
                    cancel_check, progress) -> int:
    """Write a PDF whose scanned pages carry an invisible text layer. Returns recognized page count."""
    from pypdf import PdfReader, PdfWriter
    recognized = 0
    if source.suffix.lower() == ".pdf":
        from pdf_tools import read_pdf
        writer = PdfWriter(clone_from=read_pdf(source))
        try:
            for index, _text, lines, scale in _recognize_pdf_pages(source, pages, language, dpi, force, cancel_check, progress):
                if not lines:
                    continue
                page = writer.pages[index]
                # The render is upright; make the page content upright too so
                # image pixels and PDF coordinates share one orientation.
                if page.rotation:
                    page.transfer_rotation_to_content()
                box = page.cropbox
                overlay = PdfReader(io.BytesIO(_text_overlay(float(box.width), float(box.height), lines, scale))).pages[0]
                if float(box.left) or float(box.bottom):
                    from pypdf import Transformation
                    overlay.add_transformation(Transformation().translate(float(box.left), float(box.bottom)))
                page.merge_page(overlay)
                recognized += 1
            with temporary.open("wb") as stream:
                writer.write(stream)
        finally:
            writer.close()
        return recognized
    writer = PdfWriter()
    try:
        for number, (image, image_dpi) in enumerate(_open_frames(source), 1):
            check_cancel(cancel_check)
            if progress:
                progress(f"Recognizing image {number}…")
            lines = recognize_image(image, language, cancel_check)
            buffer = io.BytesIO()
            image.save(buffer, format="PDF", resolution=image_dpi)
            page = writer.add_page(PdfReader(io.BytesIO(buffer.getvalue())).pages[0])
            if lines:
                scale = image_dpi / 72
                page.merge_page(PdfReader(io.BytesIO(
                    _text_overlay(image.width / scale, image.height / scale, lines, scale))).pages[0])
                recognized += 1
        with temporary.open("wb") as stream:
            writer.write(stream)
    finally:
        writer.close()
    return recognized


def ocr_document(source: Path, output_dir: Path, fmt: str = "TXT", language: str = DEFAULT_OCR_LANGUAGE,
                 pages: str = "all", dpi: int = 200, force: bool = False, overwrite: bool = False,
                 cancel_check: Callable[[], bool] | None = None,
                 progress: Callable[[str], None] | None = None) -> Path:
    """Recognize a scan or screenshot and publish TXT, Markdown, JSON, or a searchable PDF."""
    fmt = fmt.upper()
    if fmt not in OCR_FORMATS:
        raise ValueError("Choose TXT, MD, JSON, or PDF")
    if not 72 <= dpi <= 600:
        raise ValueError("OCR resolution must be between 72 and 600 DPI")
    if source.suffix.lower() not in OCR_EXTENSIONS:
        raise ValueError(f"OCR reads images and PDFs, not {source.suffix.lower() or 'this file'}")
    if not source.is_file():
        raise FileNotFoundError("The selected file no longer exists")
    _engine(language)  # fail before creating anything when the model is missing
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-searchable" if fmt == "PDF" else "-ocr"
    reservations: set[Path] = set()
    output = reserve_output_path(output_dir / f"{source.stem}{suffix}{OCR_FORMATS[fmt]}", overwrite, reservations)
    try:
        with tempfile.TemporaryDirectory(dir=output_dir, prefix=".shadow-ocr-") as td:
            temporary = Path(td) / ("result" + OCR_FORMATS[fmt])
            if fmt == "PDF":
                _searchable_pdf(source, temporary, language, pages, dpi, force, cancel_check, progress)
            else:
                records = extract_text(source, language, pages, dpi, force, cancel_check, progress)
                if not any(record["text"].strip() for record in records):
                    raise ValueError("No text was recognized in this file")
                if fmt == "JSON":
                    body = json.dumps(records, ensure_ascii=False, indent=2)
                elif fmt == "MD":
                    body = "\n\n".join(f"## Page {r['page']}\n\n{r['text']}" for r in records) + "\n"
                else:
                    body = "\n\n".join(r["text"] for r in records) + "\n"
                temporary.write_text(body, encoding="utf-8")
            check_cancel(cancel_check)
            return publish_output_file(temporary, output, overwrite, reservations)
    finally:
        release_output_path(output, reservations)
