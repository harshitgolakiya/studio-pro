"""Tests for the local automation API."""
from __future__ import annotations

import tests._headless  # noqa: F401 – must be first

import io
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch, MagicMock

from PIL import Image


class AutomationAPITests(unittest.TestCase):
    """Test the automation HTTP API server."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")

    def test_server_start_stop(self):
        from automation_api import AutomationServer
        server = AutomationServer(port=0)
        # Port 0 would fail in HTTPServer, use a fixed high port
        server = AutomationServer(port=17395)
        server.start()
        self.assertTrue(server.is_running)
        server.stop()
        self.assertFalse(server.is_running)

    def test_status_endpoint(self):
        from automation_api import AutomationServer
        server = AutomationServer(port=17396)
        server.start()
        try:
            conn = HTTPConnection("127.0.0.1", 17396, timeout=5)
            conn.request("GET", "/status")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read())
            self.assertEqual(data["status"], "ok")
            conn.close()
        finally:
            server.stop()

    def test_formats_endpoint(self):
        from automation_api import AutomationServer
        server = AutomationServer(port=17397)
        server.start()
        try:
            conn = HTTPConnection("127.0.0.1", 17397, timeout=5)
            conn.request("GET", "/formats")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read())
            self.assertIn("input_extensions", data)
            self.assertIn("output_formats", data)
            self.assertIsInstance(data["input_extensions"], list)
            conn.close()
        finally:
            server.stop()

    def test_convert_endpoint(self):
        from automation_api import AutomationServer
        server = AutomationServer(port=17398)
        server.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                # Create a test image
                img = Image.new("RGB", (32, 32), (100, 100, 100))
                src = Path(td) / "test.png"
                img.save(str(src))

                body = json.dumps({
                    "source": str(src),
                    "output_dir": td,
                    "format": "WEBP",
                    "quality": 80,
                }).encode()

                conn = HTTPConnection("127.0.0.1", 17398, timeout=10)
                conn.request("POST", "/convert",
                             body=body,
                             headers={"Content-Type": "application/json",
                                      "Content-Length": str(len(body))})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read())
                self.assertEqual(data["status"], "Completed")
                conn.close()
        finally:
            server.stop()

    def test_unknown_endpoint_404(self):
        from automation_api import AutomationServer
        server = AutomationServer(port=17399)
        server.start()
        try:
            conn = HTTPConnection("127.0.0.1", 17399, timeout=5)
            conn.request("GET", "/nonexistent")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 404)
            conn.close()
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
