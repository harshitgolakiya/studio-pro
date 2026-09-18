from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from doc_converter import convert_document, to_markdown


class DocConverterTests(unittest.TestCase):
    def test_txt_to_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "notes.txt"
            src.write_text("Hello world\nSecond line", encoding="utf-8")

            res = convert_document(src, root / "out", target_format="MD")
            self.assertEqual(res.status, "Completed")
            self.assertEqual(res.output_path.suffix, ".md")
            self.assertIn("Hello world", res.output_path.read_text(encoding="utf-8"))

    def test_markdown_to_html(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "doc.md"
            src.write_text("# Title\n\nSome **bold** text.\n\n- item one\n- item two\n", encoding="utf-8")

            res = convert_document(src, root / "out", target_format="HTML")
            self.assertEqual(res.status, "Completed")
            html = res.output_path.read_text(encoding="utf-8")
            self.assertIn("<h1", html)
            self.assertIn("<strong>bold</strong>", html)
            self.assertIn("<li>item one</li>", html)

    def test_html_to_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "page.html"
            src.write_text(
                "<html><body><h1>Title</h1><p>Some <strong>bold</strong> text.</p></body></html>",
                encoding="utf-8",
            )

            res = convert_document(src, root / "out", target_format="MD")
            self.assertEqual(res.status, "Completed")
            md = res.output_path.read_text(encoding="utf-8")
            self.assertIn("# Title", md)
            self.assertIn("**bold**", md)

    def test_markdown_to_docx_and_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "doc.md"
            src.write_text(
                "# Heading\n\nA paragraph with *italic* and **bold** words.\n\n"
                "- first\n- second\n\n1. one\n2. two\n",
                encoding="utf-8",
            )

            docx_res = convert_document(src, root / "out", target_format="DOCX")
            self.assertEqual(docx_res.status, "Completed")
            self.assertEqual(docx_res.output_path.suffix, ".docx")
            self.assertGreater(docx_res.output_path.stat().st_size, 0)

            # Round-trip back to markdown and check the heading survived.
            roundtrip_md = to_markdown(docx_res.output_path)
            self.assertIn("Heading", roundtrip_md)
            self.assertIn("first", roundtrip_md)

    def test_markdown_to_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "doc.md"
            src.write_text("# Report\n\nSome content here.\n", encoding="utf-8")

            res = convert_document(src, root / "out", target_format="PDF")
            self.assertEqual(res.status, "Completed")
            self.assertEqual(res.output_path.suffix, ".pdf")
            self.assertGreater(res.output_path.stat().st_size, 0)
            with res.output_path.open("rb") as f:
                self.assertEqual(f.read(4), b"%PDF")

    def test_markdown_to_txt_strips_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "doc.md"
            src.write_text("# Title\n\nSome **bold** and *italic* text.\n", encoding="utf-8")

            res = convert_document(src, root / "out", target_format="TXT")
            self.assertEqual(res.status, "Completed")
            text = res.output_path.read_text(encoding="utf-8")
            self.assertNotIn("**", text)
            self.assertNotIn("<", text)
            self.assertIn("Title", text)
            self.assertIn("bold", text)

    def test_unsupported_format_fails_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "image.png"
            src.write_bytes(b"not a real doc")

            res = convert_document(src, root / "out", target_format="MD")
            self.assertEqual(res.status, "Failed")
            self.assertIsNotNone(res.error)

    def test_missing_file_fails_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            res = convert_document(root / "does_not_exist.md", root / "out", target_format="TXT")
            self.assertEqual(res.status, "Failed")


if __name__ == "__main__":
    unittest.main()
