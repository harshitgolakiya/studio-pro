from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless

from headless_cli import main
from studio_actions import run_action
from studio_runtime import StudioCancelled


class StudioActionTests(unittest.TestCase):
    def test_cli_data_cleanup_preserves_source_and_avoids_collisions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "leads.csv"
            original = "Name,Value\n Ann ,1\n Ann ,1\n"
            source.write_text(original, encoding="utf-8")
            arguments = [str(source), "--output", str(root), "--studio-action", "data-clean",
                         "--format", "JSON", "--drop-duplicates", "--json"]
            outputs = []
            for _ in range(2):
                capture = io.StringIO()
                with contextlib.redirect_stdout(capture):
                    self.assertEqual(main(arguments), 0)
                events = [json.loads(line) for line in capture.getvalue().splitlines()]
                self.assertEqual([e["event"] for e in events], ["started", "result", "finished"])
                result = events[1]
                self.assertEqual(result["details"]["duplicate_rows_removed"], 1)
                output = Path(result["outputs"][0])
                self.assertEqual(json.loads(output.read_text()), [{"Name": "Ann", "Value": "1"}])
                outputs.append(output)
            self.assertNotEqual(*outputs)
            self.assertEqual(source.read_text(), original)

    def test_package_creation_extraction_and_failed_verification_exit_code(self):
        from archive_tools import create_archive
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "deliverable.txt"
            source.write_text("Approved", encoding="utf-8")
            package = run_action("delivery-create", [source], root / "out", client="Acme", project="Launch").outputs[0]
            self.assertTrue(run_action("delivery-verify", [package], root).ok)
            folder = run_action("archive-extract", [package], root / "extracted").outputs[0]
            (folder / "deliverable.txt").write_text("Changed", encoding="utf-8")
            bad = create_archive(list(folder.iterdir()), root / "bad.zip")
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                code = main([str(bad), "--output", str(root), "--studio-action", "delivery-verify", "--json"])
            self.assertEqual(code, 1)
            events = [json.loads(line) for line in capture.getvalue().splitlines()]
            self.assertEqual(events[1]["details"]["changed"], ["deliverable.txt"])

    def test_cli_invalid_input_is_structured_failure(self):
        with tempfile.TemporaryDirectory() as td:
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                code = main([str(Path(td) / "missing.csv"), "--output", td,
                             "--studio-action", "data-convert", "--json"])
            self.assertEqual(code, 1)
            events = [json.loads(line) for line in capture.getvalue().splitlines()]
            self.assertEqual(events[1]["status"], "Failed")

    def test_cancel_before_creation_and_ambiguous_multiple_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "a.csv"
            source.write_text("a\n1\n")
            output = Path(td) / "out"
            with self.assertRaises(StudioCancelled):
                run_action("data-convert", [source], output, cancel_check=lambda: True)
            with self.assertRaisesRegex(ValueError, "one input"):
                run_action("data-convert", [source, source], output)
            self.assertFalse(output.exists())

    def test_ocr_cli_passes_page_and_language_options(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "scan.pdf"
            source.write_bytes(b"placeholder")
            with patch("ocr_engine.ocr_document", return_value=Path(td) / "scan-ocr.txt") as recognize:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main([str(source), "--output", td, "--studio-action", "ocr",
                                 "--ocr-language", "Arabic", "--pages", "2-3", "--dpi", "300", "--force-ocr"])
            self.assertEqual(code, 0)
            self.assertEqual(recognize.call_args.args[2:7], ("TXT", "Arabic", "2-3", 300, True))

    def test_dialog_builds_expansion_panels(self):
        import customtkinter as ctk
        import tkinter as tk
        from studio_dialog import StudioToolsDialog
        root = ctk.CTk()
        root.withdraw()
        root.output_directory = tk.StringVar(master=root, value=tempfile.gettempdir())
        dialog = None
        try:
            dialog = StudioToolsDialog(root)
            root.update()
            self.assertGreater(len(dialog._actions), 20)
        finally:
            if dialog:
                dialog.destroy()
            from ui_dispatch import cancel_widget_callbacks
            cancel_widget_callbacks(root)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
