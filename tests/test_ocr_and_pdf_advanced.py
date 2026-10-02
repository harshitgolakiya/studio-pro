from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: F401

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from studio_runtime import StagedOutput, StudioCancelled


def _font(size: int):
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _scan(path: Path, lines: list[str]) -> Path:
    image = Image.new("RGB", (1240, 900), "white")
    draw = ImageDraw.Draw(image)
    for row, text in enumerate(lines):
        draw.text((90, 90 + row * 140), text, fill="black", font=_font(46))
    if path.suffix == ".pdf":
        image.save(path, resolution=150)
    else:
        image.save(path, dpi=(150, 150))
    return path


def _text_pdf(path: Path, lines: list[str]) -> Path:
    from reportlab.pdfgen import canvas
    sheet = canvas.Canvas(str(path), pagesize=(595, 842))
    for row, text in enumerate(lines):
        sheet.setFont("Helvetica", 14)
        sheet.drawString(72, 760 - row * 30, text)
    sheet.showPage()
    sheet.setFont("Helvetica", 14)
    sheet.drawString(72, 760, "Second page stays as it is")
    sheet.save()
    return path


class StagedOutputTests(unittest.TestCase):
    def test_publishes_only_on_success_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "result.txt"
            with StagedOutput(target) as stage:
                stage.path.write_text("one")
            self.assertEqual(stage.output, target)
            with StagedOutput(target) as stage:
                stage.path.write_text("two")
            self.assertEqual(stage.output.name, "result_1.txt")
            self.assertEqual(target.read_text(), "one")
            with self.assertRaises(RuntimeError):
                with StagedOutput(Path(td) / "failed.txt") as stage:
                    stage.path.write_text("partial")
                    raise RuntimeError("boom")
            self.assertEqual(sorted(p.name for p in Path(td).iterdir()), ["result.txt", "result_1.txt"])


class OcrTests(unittest.TestCase):
    def test_image_to_text_json_and_searchable_pdf(self):
        from ocr_engine import ocr_document
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _scan(root / "invoice.png", ["Agency invoice 2026", "Total due 4250"])
            text = ocr_document(source, root / "out", "TXT").read_text(encoding="utf-8")
            self.assertIn("Agency invoice 2026", text)
            records = json.loads(ocr_document(source, root / "out", "JSON").read_text(encoding="utf-8"))
            self.assertEqual(records[0]["page"], 1)
            self.assertEqual(len(records[0]["lines"][0]["box"]), 4)
            searchable = ocr_document(source, root / "out", "PDF")
            page = PdfReader(searchable).pages[0]
            self.assertIn("Total due 4250", page.extract_text())
            self.assertTrue(page.images, "The scan itself must stay in the page")
            self.assertTrue(source.exists())

    def test_scanned_pdf_gains_text_layer_and_text_pages_are_kept(self):
        from doc_converter import to_markdown
        from ocr_engine import extract_text, ocr_document
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan = _scan(root / "scan.pdf", ["Campaign results", "Quarter three"])
            self.assertEqual((PdfReader(scan).pages[0].extract_text() or "").strip(), "")
            searchable = ocr_document(scan, root, "PDF")
            self.assertIn("Campaign results", PdfReader(searchable).pages[0].extract_text())
            # Already-searchable pages are read from their text layer, not re-recognized.
            records = extract_text(searchable)
            self.assertFalse(records[0]["ocr"])
            self.assertIn("Quarter three", records[0]["text"])
            # Document conversion falls back to OCR for scans.
            self.assertIn("Campaign results", to_markdown(scan))

    def test_invalid_requests_create_no_output(self):
        from ocr_engine import ocr_document
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            notes = root / "notes.txt"
            notes.write_text("hello")
            with self.assertRaises(ValueError):
                ocr_document(notes, root / "out")
            blank = root / "blank.png"
            Image.new("RGB", (300, 200), "white").save(blank)
            with self.assertRaises(ValueError):
                ocr_document(blank, root / "out", "TXT")
            with self.assertRaises(ValueError):
                ocr_document(blank, root / "out", "DOCX")
            with self.assertRaises(ValueError):
                ocr_document(blank, root / "out", "TXT", language="Klingon")
            with self.assertRaises(StudioCancelled):
                ocr_document(blank, root / "out", "TXT", cancel_check=lambda: True)
            self.assertFalse(list((root / "out").glob("*")) if (root / "out").exists() else [])


class PdfPasswordTests(unittest.TestCase):
    def test_protect_then_unlock_roundtrip(self):
        from pdf_advanced import protect_pdf, unlock_pdf
        from pdf_tools import read_pdf
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _text_pdf(root / "contract.pdf", ["Confidential contract"])
            locked = protect_pdf(source, root / "locked.pdf", "s3cret", allow_copying=False)
            reader = PdfReader(locked)
            self.assertTrue(reader.is_encrypted)
            with self.assertRaises(ValueError):
                read_pdf(locked)
            with self.assertRaises(ValueError):
                read_pdf(locked, "wrong")
            self.assertIn("Confidential", read_pdf(locked, "s3cret").pages[0].extract_text())
            unlocked = unlock_pdf(locked, root / "open.pdf", "s3cret")
            self.assertFalse(PdfReader(unlocked).is_encrypted)
            with self.assertRaises(ValueError):
                unlock_pdf(source, root / "again.pdf", "x")
            with self.assertRaises(ValueError):
                protect_pdf(source, source, "pw")
            with self.assertRaises(ValueError):
                protect_pdf(source, root / "empty.pdf", "")


class PdfRedactionTests(unittest.TestCase):
    def test_redacted_text_is_gone_and_other_pages_survive(self):
        from pdf_advanced import REDACTION_PRESETS, redact_pdf
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _text_pdf(root / "brief.pdf", ["Client: Acme Holdings", "Contact jane@acme.example today"])
            output, count = redact_pdf(source, root / "redacted.pdf", ["acme holdings"])
            self.assertEqual(count, 1)
            reader = PdfReader(output)
            self.assertEqual(len(reader.pages), 2)
            self.assertNotIn("Acme Holdings", reader.pages[0].extract_text() or "")
            self.assertNotIn(b"Acme Holdings", output.read_bytes())
            self.assertIn("Second page", reader.pages[1].extract_text())
            emails, count = redact_pdf(source, root / "emails.pdf", [REDACTION_PRESETS["Email addresses"]], regex=True)
            self.assertGreaterEqual(count, 1)
            self.assertNotIn(b"jane@acme.example", emails.read_bytes())
            # The blacked-out area is really painted.
            from pdf_tools import render_pdf_page
            image, _ = render_pdf_page(output, 0, scale=1)
            try:
                dark = sum(image.convert("L").point(lambda value: 1 if value < 20 else 0).tobytes())
            finally:
                image.close()
            self.assertGreater(dark, 500)
            self.assertIn("Acme Holdings", PdfReader(source).pages[0].extract_text())

    def test_no_match_and_bad_pattern_write_nothing(self):
        from pdf_advanced import redact_pdf
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _text_pdf(root / "brief.pdf", ["Nothing secret"])
            with self.assertRaises(ValueError):
                redact_pdf(source, root / "out.pdf", ["absent phrase"])
            with self.assertRaises(ValueError):
                redact_pdf(source, root / "out.pdf", ["(unclosed"], regex=True)
            with self.assertRaises(ValueError):
                redact_pdf(source, root / "out.pdf", [])
            self.assertFalse((root / "out.pdf").exists())

    def test_region_redaction(self):
        from pdf_advanced import redact_pdf
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _text_pdf(root / "brief.pdf", ["Top line secret"])
            output, count = redact_pdf(source, root / "region.pdf", regions=[(1, 60, 60, 400, 100)])
            self.assertEqual(count, 1)
            self.assertNotIn("secret", PdfReader(output).pages[0].extract_text() or "")


class PdfFormTests(unittest.TestCase):
    def _form(self, path: Path) -> Path:
        from reportlab.pdfgen import canvas
        sheet = canvas.Canvas(str(path), pagesize=(400, 300))
        sheet.drawString(40, 250, "Client intake")
        sheet.acroForm.textfield(name="client", x=40, y=200, width=200, height=24)
        sheet.acroForm.textfield(name="budget", x=40, y=150, width=200, height=24)
        sheet.save()
        return path

    def test_list_fill_and_flatten(self):
        from pdf_advanced import fill_form, list_form_fields
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._form(root / "form.pdf")
            self.assertEqual({f["name"] for f in list_form_fields(source)}, {"client", "budget"})
            filled = fill_form(source, root / "filled.pdf", {"client": "Acme", "budget": "2500"})
            values = {f["name"]: f["value"] for f in list_form_fields(filled)}
            self.assertEqual(values, {"client": "Acme", "budget": "2500"})
            flat = fill_form(source, root / "flat.pdf", {"client": "Acme"}, flatten=True)
            self.assertIn("Acme", PdfReader(flat).pages[0].extract_text())
            with self.assertRaises(ValueError) as caught:
                fill_form(source, root / "bad.pdf", {"missing": "x"})
            self.assertIn("client", str(caught.exception))
            self.assertFalse((root / "bad.pdf").exists())
            with self.assertRaises(ValueError):
                fill_form(_text_pdf(root / "plain.pdf", ["no fields"]), root / "none.pdf", {"a": "b"})


class PdfSignatureTests(unittest.TestCase):
    def test_sign_verify_and_detect_tampering(self):
        from pdf_advanced import create_signing_identity, sign_pdf, verify_signatures
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _text_pdf(root / "contract.pdf", ["Signed agreement"])
            identity = create_signing_identity("Jordan Example", root / "identity.p12", "passphrase",
                                               organization="Example Agency")
            signed = sign_pdf(source, root / "signed.pdf", identity, "passphrase", reason="Approved")
            reports = verify_signatures(signed)
            self.assertEqual(len(reports), 1)
            self.assertTrue(reports[0]["intact"], reports[0])
            self.assertTrue(reports[0]["covers_whole_document"])
            self.assertIn("Jordan Example", reports[0]["signer"])
            self.assertEqual(verify_signatures(source), [])
            data = bytearray(signed.read_bytes())
            position = data.find(b"stream") + 12  # inside the first signed content stream
            self.assertGreater(position, 12)
            data[position] ^= 0xFF
            tampered = root / "tampered.pdf"
            tampered.write_bytes(bytes(data))
            self.assertFalse(verify_signatures(tampered)[0]["intact"])
            with self.assertRaises(ValueError):
                sign_pdf(source, root / "wrong.pdf", identity, "not-the-passphrase")
            self.assertFalse((root / "wrong.pdf").exists())
            with self.assertRaises(ValueError):
                create_signing_identity("", root / "x.p12", "passphrase")


class PdfRepairAndTableTests(unittest.TestCase):
    def test_repair_recovers_broken_cross_reference(self):
        from pdf_advanced import repair_pdf
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _text_pdf(root / "report.pdf", ["Recoverable report"])
            data = source.read_bytes()
            broken = root / "broken.pdf"
            broken.write_bytes(data[:data.rfind(b"xref")] + b"xref\n0 1\ngarbage\n%%EOF")
            repaired, pages = repair_pdf(broken, root / "repaired.pdf")
            self.assertEqual(pages, 2)
            self.assertIn("Recoverable report", PdfReader(repaired, strict=True).pages[0].extract_text())
            junk = root / "junk.pdf"
            junk.write_bytes(b"this is not a pdf")
            with self.assertRaises(RuntimeError):
                repair_pdf(junk, root / "junk-out.pdf")
            self.assertFalse((root / "junk-out.pdf").exists())

    def test_tables_to_xlsx_csv_and_json(self):
        from openpyxl import load_workbook
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        from pdf_advanced import extract_tables
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "budget.pdf"
            table = Table([["Channel", "Budget"], ["Search", "1200"], ["Social", "800"]])
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
            SimpleDocTemplate(str(source)).build([table])
            workbook_path, count = extract_tables(source, root / "tables.xlsx")
            self.assertEqual(count, 1)
            book = load_workbook(workbook_path)
            try:
                self.assertEqual([c.value for c in book.worksheets[0][2]], ["Search", "1200"])
            finally:
                book.close()
            csv_path, _ = extract_tables(source, root / "tables.csv")
            self.assertIn("Social,800", csv_path.read_text(encoding="utf-8-sig"))
            data = json.loads(extract_tables(source, root / "tables.json")[0].read_text(encoding="utf-8"))
            self.assertEqual(data[0]["rows"][0], ["Channel", "Budget"])
            with self.assertRaises(ValueError):
                extract_tables(_text_pdf(root / "prose.pdf", ["Just a sentence"]), root / "none.xlsx")
            with self.assertRaises(ValueError):
                extract_tables(source, root / "tables.docx")


if __name__ == "__main__":
    unittest.main()
