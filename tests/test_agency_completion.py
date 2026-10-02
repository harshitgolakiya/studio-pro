from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from http.client import HTTPConnection

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless

from studio_actions import run_action
from studio_workflows import coerce_options


class AgencyWorkflowTests(unittest.TestCase):
    def test_pdf_password_redaction_forms_repair_and_signature_routes(self):
        from reportlab.pdfgen import canvas
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "proposal.pdf"
            pdf = canvas.Canvas(str(source))
            pdf.drawString(60, 700, "Confidential Acme invoice")
            pdf.acroForm.textfield(name="Client", x=60, y=600, width=200, height=20)
            pdf.showPage()
            pdf.save()
            protected = run_action("pdf-protect", [source], root, options={"open_password": "secret"}).outputs[0]
            unlocked = run_action("pdf-unlock", [protected], root, options={"password": "secret"}).outputs[0]
            self.assertIn("Acme", PdfReader(unlocked).pages[0].extract_text())
            redacted = run_action("pdf-redact", [source], root, options={"terms": ["Acme"]}).outputs[0]
            self.assertNotIn("Acme", PdfReader(redacted).pages[0].extract_text())
            fields = run_action("pdf-fields", [source], root)
            self.assertEqual(fields.details["items"][0]["name"], "Client")
            filled = run_action("pdf-fill", [source], root, options={"values": {"Client": "Acme"}}).outputs[0]
            self.assertEqual(str(PdfReader(filled).get_fields()["Client"]["/V"]), "Acme")
            repaired = run_action("pdf-repair", [source], root)
            self.assertEqual(repaired.details["pages_recovered"], 1)
            identity = run_action("pdf-identity", [], root, options={"name": "Reviewer", "passphrase": "secure-pass"}).outputs[0]
            signed = run_action("pdf-sign", [source], root, options={"identity": str(identity), "passphrase": "secure-pass"}).outputs[0]
            signatures = run_action("pdf-signatures", [signed], root)
            self.assertTrue(signatures.ok)
            self.assertFalse(signatures.details["items"][0]["trusted"])

    def test_office_properties_and_replacement(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "proposal.docx"
            document = Document()
            document.add_paragraph("Client Acme")
            document.save(source)
            replaced = run_action("office-replace", [source], root, options={"replacements": {"Acme": "Zed"}})
            self.assertEqual(replaced.details["replacements"], 1)
            properties = run_action("office-set-properties", replaced.outputs, root, options={"properties": {"title": "Launch"}})
            self.assertEqual(run_action("office-properties", properties.outputs, root).details["title"], "Launch")

    def test_schema_and_subtitle_routes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / "rows.csv"
            data.write_text("name,budget\nAcme,50\n", encoding="utf-8")
            schema = run_action("data-schema", [data], root).outputs[0]
            self.assertTrue(run_action("data-validate", [data], root, options={"schema": str(schema)}).ok)
            schema.write_text('{"type":"object","required":["missing"]}', encoding="utf-8")
            self.assertFalse(run_action("data-validate", [data], root, options={"schema": str(schema)}).ok)
            subtitles = root / "meeting.srt"
            subtitles.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello Acme\n", encoding="utf-8")
            result = run_action("subtitle-edit", [subtitles], root, options={"format": "VTT", "shift": 2, "replacements": {"Acme": "Zed"}})
            text = result.outputs[0].read_text()
            self.assertIn("00:00:03.000", text)
            self.assertIn("Zed", text)

    def test_project_delivery_naming_profile_and_branding(self):
        from PIL import Image
        from agency_projects import save_profile, load_profile, run_project, delivery_name, validate_profile
        from archive_tools import verify_package
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "banner.png"
            Image.new("RGB", (1200, 800), "blue").save(source)
            profile = {"client": "Acme", "project": "Launch", "colors": ["#123456"], "fonts": ["Inter"],
                       "naming": "{client}-{project}-{stem}-{index}", "preset": "Social square"}
            path = save_profile(profile, root / "profiles")
            loaded = load_profile(path)
            result = run_project(loaded, [source], root / "out")
            self.assertTrue(result.ok)
            self.assertEqual(result.outputs[0].name, "Acme-Launch-banner-001.jpg")
            with Image.open(result.outputs[0]) as output:
                self.assertEqual(output.size, (1080, 1080))
            self.assertTrue(verify_package(result.outputs[-1])["ok"])
            self.assertTrue(source.exists())
            with self.assertRaises(ValueError):
                validate_profile({**profile, "naming": "{stem.__class__}"})

    def test_preflight_font_inspection_eps_and_cmyk(self):
        from reportlab.pdfgen import canvas
        from print_tools import ghostscript_path
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "print.pdf"
            pdf = canvas.Canvas(str(source))
            pdf.drawString(50, 700, "Print text")
            pdf.save()
            fonts = run_action("print-fonts", [source], root)
            self.assertTrue(fonts.details["fonts"])
            preflight = run_action("print-preflight", [source], root)
            self.assertFalse(preflight.ok, "The default Helvetica font is not embedded")
            if not ghostscript_path():
                return
            eps = root / "drawing.eps"
            eps.write_text("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 100\n1 0 0 setrgbcolor\n0 0 100 100 rectfill\nshowpage\n")
            imported = run_action("print-import", [eps], root).outputs[0]
            from pypdf import PdfReader
            self.assertEqual(len(PdfReader(imported).pages), 1)
            image = root / "image.png"
            Image.new("RGB", (100, 100), "red").save(image)
            from studio_runtime import model_directory
            if not (model_directory() / "color" / "default_cmyk.icc").is_file():
                return
            for input_file in (image, source):
                output = run_action("print-cmyk", [input_file], root).outputs[0]
                self.assertTrue(output.is_file())
                if output.suffix == ".tif":
                    with Image.open(output) as result:
                        self.assertEqual(result.mode, "CMYK")
                        self.assertIn("icc_profile", result.info)

    def test_hook_callbacks_and_loopback_api_action(self):
        from plugin_sdk import get_registry
        from headless_cli import convert_path
        from automation_api import AutomationServer
        from PIL import Image
        calls = []
        registry = get_registry()
        old_hooks = dict(registry._hooks)
        registry.add_hook("after_convert", lambda source, result: calls.append(result.status))
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                image = root / "source.png"
                Image.new("RGB", (10, 10), "red").save(image)
                convert_path(image, root / "out", {"target_format": "WEBP"})
                self.assertEqual(calls, ["Completed"])
                data = root / "rows.csv"
                data.write_text("name\nAcme\n")
                server = AutomationServer(port=0)
                server.start()
                try:
                    connection = HTTPConnection("127.0.0.1", server.port, timeout=20)
                    connection.request("POST", "/studio/run", json.dumps({"action": "data-schema", "sources": [str(data)], "output_dir": str(root)}), {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())["ok"])
                    connection.close()
                finally:
                    server.stop()
                with self.assertRaises(ValueError):
                    AutomationServer(host="0.0.0.0", port=0).start()
        finally:
            registry._hooks = old_hooks

    def test_options_reject_unknown_keys_and_wrong_shapes(self):
        with self.assertRaises(ValueError):
            coerce_options("pdf-fill", {"values": "[]"})
        with self.assertRaises(ValueError):
            coerce_options("pdf-protect", {"allow_printing": "false"})
        with self.assertRaises(ValueError):
            coerce_options("print-preflight", {"unknown": 1})


if __name__ == "__main__":
    unittest.main()
