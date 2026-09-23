from __future__ import annotations

import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401 -- stubs modal dialogs so tests never hang

import customtkinter as ctk
from PIL import Image

from preview_modal import (
    VARIANT_PRESETS,
    ImagePreviewDialog,
    VariantResult,
    generate_variant,
)


class MultiVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.root = ctk.CTk()
            cls.root.withdraw()
        except Exception:
            cls.root = None

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.root:
            try:
                cls.root.destroy()
            except Exception:
                pass

    def test_generate_variant_webp_and_jpeg(self) -> None:
        img = Image.new("RGB", (100, 100), color=(120, 80, 200))
        res_webp = generate_variant(img, "WEBP", 80)
        self.assertIsNone(res_webp.error)
        self.assertEqual(res_webp.codec, "WEBP")
        self.assertEqual(res_webp.quality, 80)
        self.assertGreater(res_webp.size_bytes, 0)
        self.assertGreater(res_webp.ssim, 0.90)
        self.assertGreater(res_webp.psnr, 20.0)
        self.assertIsNotNone(res_webp.image)

        res_jpeg = generate_variant(img, "JPEG", 75)
        self.assertIsNone(res_jpeg.error)
        self.assertEqual(res_jpeg.codec, "JPEG")
        self.assertGreater(res_jpeg.size_bytes, 0)
        self.assertGreater(res_jpeg.ssim, 0.85)

    def test_generate_variant_alpha_flattening_for_jpeg(self) -> None:
        # RGBA image with transparency
        rgba_img = Image.new("RGBA", (80, 80), color=(255, 0, 0, 128))
        res = generate_variant(rgba_img, "JPEG", 80)
        self.assertIsNone(res.error)
        self.assertEqual(res.codec, "JPEG")
        self.assertGreater(res.size_bytes, 0)

    def test_generate_variant_invalid_codec_graceful_error(self) -> None:
        img = Image.new("RGB", (50, 50), color="blue")
        res = generate_variant(img, "NONEXISTENT_CODEC", 50)
        self.assertIsNotNone(res.error)
        self.assertEqual(res.size_bytes, 0)

    def test_presets_structure(self) -> None:
        self.assertIn("Modern Web", VARIANT_PRESETS)
        self.assertIn("Next-Gen Codecs", VARIANT_PRESETS)
        self.assertIn("WebP Quality Ladder", VARIANT_PRESETS)
        self.assertIn("High Fidelity", VARIANT_PRESETS)
        self.assertIn("Aggressive Compression", VARIANT_PRESETS)

        for name, slots in VARIANT_PRESETS.items():
            if name != "Custom":
                self.assertGreaterEqual(len(slots), 2)
                for codec, quality in slots:
                    self.assertIsInstance(codec, str)
                    self.assertIsInstance(quality, int)
                    self.assertGreaterEqual(quality, 1)
                    self.assertLessEqual(quality, 100)

    def test_dialog_multi_variant_mode_unconverted_file(self) -> None:
        if self.root is None:
            self.skipTest("No Tk root available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "test_photo.png"
            Image.new("RGB", (120, 90), color=(40, 140, 240)).save(tmp_path)

            on_apply_mock = MagicMock()
            dialog = ImagePreviewDialog(self.root, tmp_path, result=None, on_apply=on_apply_mock)
            dialog.update()

            # Unconverted file defaults to Multi-Variant
            self.assertEqual(dialog.view_mode.get(), "Multi-Variant")
            modes = dialog.mode_selector.cget("values")
            self.assertIn("Multi-Variant", modes)

            # Check preset selection
            dialog._on_preset_selected("Next-Gen Codecs")
            self.assertEqual(len(dialog._variant_slots), len(VARIANT_PRESETS["Next-Gen Codecs"]))

            # Check slot count changed
            dialog._on_slot_count_changed("2")
            self.assertEqual(len(dialog._variant_slots), 2)
            self.assertEqual(dialog._variant_preset.get(), "Custom")

            # Check slot config changed
            dialog._on_slot_codec_changed(0, "JPEG")
            self.assertEqual(dialog._variant_slots[0][0], "JPEG")
            dialog._on_slot_quality_changed(0, "92")
            self.assertEqual(dialog._variant_slots[0][1], 92)

            # Wait for/simulate variants generated
            mock_res = generate_variant(dialog.orig_pil, "WEBP", 80)
            dialog._on_variants_generated(dialog._variant_generation_id, {0: mock_res})
            self.assertIn(0, dialog._variant_results)

            # Test applying variant to app
            dialog._apply_variant_to_app("WEBP", 80)
            on_apply_mock.assert_called_once_with("WEBP", 80)

            # Test comparing variant in split slider
            dialog._compare_variant_in_slider(mock_res, "WEBP", 80)
            self.assertEqual(dialog.view_mode.get(), "Split Slider")
            self.assertIn("Split Slider", dialog.mode_selector.cget("values"))
            self.assertIsNotNone(dialog.conv_pil)
            self.assertEqual(dialog._active_variant_label, "WEBP q80")

            dialog.destroy()


if __name__ == "__main__":
    unittest.main()
