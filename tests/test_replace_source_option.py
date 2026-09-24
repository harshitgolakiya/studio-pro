from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401

from PIL import Image

from converter import convert_image
from settings import DEFAULT_SETTINGS


class TestReplaceSourceOption(unittest.TestCase):
    def test_settings_has_replace_source_default(self) -> None:
        self.assertIn("replace_source_files", DEFAULT_SETTINGS)
        self.assertFalse(DEFAULT_SETTINGS["replace_source_files"])

    def test_convert_image_replaces_source_png_with_webp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_png = root / "photo.png"
            Image.new("RGB", (64, 64), color="blue").save(src_png, format="PNG")
            self.assertTrue(src_png.exists())

            res = convert_image(
                src_png,
                root,
                quality=80,
                target_format="WEBP",
                replace_source=True,
            )

            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertTrue(res.output_path.exists())
            self.assertEqual(res.output_path.name, "photo.webp")
            self.assertGreater(res.output_path.stat().st_size, 0)
            # Original source image must be deleted/replaced
            self.assertFalse(src_png.exists())
            self.assertIn("Replaced original", res.note or "")

    def test_convert_image_in_place_webp_preserves_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_webp = root / "image.webp"
            Image.new("RGB", (64, 64), color="red").save(src_webp, format="WEBP")
            self.assertTrue(src_webp.exists())

            res = convert_image(
                src_webp,
                root,
                quality=50,
                target_format="WEBP",
                replace_source=True,
            )

            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertTrue(res.output_path.exists())
            self.assertEqual(res.output_path.name, "image.webp")
            self.assertIn("Replaced in-place", res.note or "")

    def test_convert_image_failure_preserves_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_file = root / "broken.jpg"
            # Write invalid/corrupt content
            src_file.write_bytes(b"corrupt-non-image-data-test")
            self.assertTrue(src_file.exists())

            res = convert_image(
                src_file,
                root,
                quality=80,
                target_format="WEBP",
                replace_source=True,
            )

            self.assertEqual(res.status, "Failed")
            # CRITICAL: Source file MUST NOT be deleted if conversion failed
            self.assertTrue(src_file.exists())

    def test_ui_checkboxes_and_sync(self) -> None:
        import os
        os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
        import main as M

        app = M.WebPCompressorApp()
        try:
            self.assertTrue(hasattr(app, "replace_source_files"))
            self.assertTrue(hasattr(app, "replace_source_checkbox"))
            self.assertFalse(app.replace_source_files.get())

            # Enabling replace_source should automatically enable save_in_source_folder
            app.replace_source_files.set(True)
            app._replace_source_files_toggled()
            self.assertTrue(app.save_in_source_folder.get())

            # Disabling save_in_source_folder should automatically disable replace_source_files
            app.save_in_source_folder.set(False)
            app._save_in_source_folder_toggled()
            self.assertFalse(app.replace_source_files.get())
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
