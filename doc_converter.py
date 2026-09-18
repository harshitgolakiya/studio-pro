from __future__ import annotations

import html as html_module
import os
from pathlib import Path
import re
import tempfile

from converter import ConversionResult
from utils import build_destination_filename, format_saved_percentage, reserve_output_path

SUPPORTED_DOCUMENT_EXTENSIONS = {".docx", ".pdf", ".html", ".htm", ".txt", ".md", ".markdown"}

TARGET_EXT_MAP = {
    "MD": ".md",
    "DOCX": ".docx",
    "PDF": ".pdf",
    "HTML": ".html",
    "TXT": ".txt",
}


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _docx_to_html(path: Path) -> str:
    import mammoth

    with path.open("rb") as f:
        result = mammoth.convert_to_html(f)
    return result.value


def _pdf_to_markdown(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    paragraphs = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError("No extractable text found in this PDF (it may be a scanned image).")
    return "\n\n".join(paragraphs)


def _html_to_markdown(html_text: str) -> str:
    from markdownify import markdownify as html2md

    return html2md(html_text, heading_style="ATX").strip() + "\n"


def to_markdown(source_path: Path) -> str:
    """Extract the contents of a supported document as Markdown text."""
    ext = source_path.suffix.lower()
    if ext in (".md", ".markdown", ".txt"):
        return _read_text_file(source_path)
    if ext in (".html", ".htm"):
        return _html_to_markdown(_read_text_file(source_path))
    if ext == ".docx":
        return _html_to_markdown(_docx_to_html(source_path))
    if ext == ".pdf":
        return _pdf_to_markdown(source_path)
    raise ValueError(f"Unsupported document format: {ext}")


def _markdown_to_html(md_text: str) -> str:
    import markdown as md_lib

    return md_lib.markdown(
        md_text,
        extensions=["extra", "sane_lists", "toc"],
        output_format="html5",
    )


def _markdown_to_txt(md_text: str) -> str:
    """Render Markdown to plain text by stripping the HTML it renders to."""
    html_text = _markdown_to_html(md_text)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)

    cleaned_lines: list[str] = []
    blank_run = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip() + "\n"


def _markdown_to_pdf_bytes(md_text: str) -> bytes:
    import io

    from xhtml2pdf import pisa

    body = _markdown_to_html(md_text)
    wrapped = f"<html><body>{body}</body></html>"
    buf = io.BytesIO()
    status = pisa.CreatePDF(wrapped, dest=buf)
    if status.err:
        raise RuntimeError("Failed to render PDF from Markdown content")
    return buf.getvalue()


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_INLINE_SPLIT_RE = re.compile(
    r"(\*\*\*.+?\*\*\*|___.+?___|\*\*.+?\*\*|__.+?__|\*[^*\s].*?\*|_[^_\s].*?_)"
)


def _add_inline_runs(paragraph, text: str) -> None:
    """Apply basic **bold** / *italic* / ***bold italic*** inline formatting to a docx paragraph."""
    for part in _INLINE_SPLIT_RE.split(text):
        if not part:
            continue
        if part.startswith(("***", "___")) and part.endswith(("***", "___")):
            run = paragraph.add_run(part[3:-3])
            run.bold = True
            run.italic = True
        elif part.startswith(("**", "__")) and part.endswith(("**", "__")):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith(("*", "_")) and part.endswith(("*", "_")):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            paragraph.add_run(part)


def _markdown_to_docx_bytes(md_text: str) -> bytes:
    """Render a practical subset of Markdown (headings, lists, bold/italic, fenced code) to .docx.

    This is a deliberately simple line-based renderer rather than a full
    CommonMark implementation -- it covers what people actually write in
    notes/docs. Anything it doesn't recognize is emitted as a plain
    paragraph, so content is never dropped, just under-formatted.
    """
    import io

    from docx import Document

    doc = Document()
    lines = md_text.splitlines()
    i = 0
    in_code_block = False
    code_lines: list[str] = []

    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lines = []
            else:
                in_code_block = False
                run = doc.add_paragraph().add_run("\n".join(code_lines))
                run.font.name = "Consolas"
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        heading_match = _HEADING_RE.match(line)
        bullet_match = _BULLET_RE.match(line)
        numbered_match = _NUMBERED_RE.match(line)

        if heading_match:
            level = min(len(heading_match.group(1)), 6)
            doc.add_heading(heading_match.group(2).strip(), level=level)
        elif bullet_match:
            _add_inline_runs(doc.add_paragraph(style="List Bullet"), bullet_match.group(1))
        elif numbered_match:
            _add_inline_runs(doc.add_paragraph(style="List Number"), numbered_match.group(1))
        elif line.strip() == "":
            pass
        else:
            _add_inline_runs(doc.add_paragraph(), line.strip())
        i += 1

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def convert_document(
    source_path: Path,
    output_directory: Path,
    target_format: str = "MD",
    overwrite: bool = False,
    reserved_paths: set[Path] | None = None,
    slugify_names: bool = False,
    filename_prefix: str = "",
    filename_suffix: str = "",
) -> ConversionResult:
    """Convert a document (.docx/.pdf/.html/.txt/.md) to/from Markdown."""
    original_size = None
    try:
        ext = source_path.suffix.lower()
        if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
            raise ValueError("Unsupported document format")
        if not source_path.is_file():
            raise FileNotFoundError("The selected document no longer exists")

        original_size = source_path.stat().st_size
        output_directory.mkdir(parents=True, exist_ok=True)

        fmt = target_format.upper().strip()
        dest_ext = TARGET_EXT_MAP.get(fmt, ".md")

        dest_filename = build_destination_filename(
            stem=source_path.stem,
            ext=dest_ext,
            slugify=slugify_names,
            prefix=filename_prefix,
            suffix=filename_suffix,
        )
        output_path = reserve_output_path(output_directory / dest_filename, overwrite, reserved_paths)

        md_text = to_markdown(source_path)

        temp_fd, temp_name = tempfile.mkstemp(suffix=f".tmp{dest_ext}", dir=str(output_directory))
        os.close(temp_fd)
        temporary_path = Path(temp_name)
        try:
            if fmt == "MD":
                temporary_path.write_text(md_text, encoding="utf-8")
            elif fmt == "TXT":
                temporary_path.write_text(_markdown_to_txt(md_text), encoding="utf-8")
            elif fmt == "HTML":
                body = _markdown_to_html(md_text)
                temporary_path.write_text(
                    "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
                    f"<title>{source_path.stem}</title></head><body>\n{body}\n</body></html>",
                    encoding="utf-8",
                )
            elif fmt == "DOCX":
                temporary_path.write_bytes(_markdown_to_docx_bytes(md_text))
            elif fmt == "PDF":
                temporary_path.write_bytes(_markdown_to_pdf_bytes(md_text))
            else:
                raise ValueError(f"Unsupported target document format: {target_format}")

            os.replace(temporary_path, output_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

        output_size = output_path.stat().st_size
        return ConversionResult(
            source_path,
            output_path,
            original_size,
            output_size,
            format_saved_percentage(original_size, output_size),
            "Completed",
        )
    except Exception as error:
        return ConversionResult(source_path, None, original_size, None, "-", "Failed", str(error))
