"""Unit and integration tests for JPEG XL (JXL) image codec engine."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import tests._headless  # noqa: F401 - headless test runner mocks
from converter import convert_image, estimate_image_output_size, IMAGE_OUTPUT_FORMATS, SUPPORTED_EXTENSIONS
import jxl_engine


class TestJxlEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="shadow-jxl-test-")
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_jxl_availability(self) -> None:
        self.assertTrue(jxl_engine.is_jxl_available(), "JPEG XL support should be available via imagecodecs")
        self.assertIn(".jxl", SUPPORTED_EXTENSIONS)
        self.assertIn("JXL", IMAGE_OUTPUT_FORMATS)

    def test_encode_decode_rgb(self) -> None:
        im = Image.new("RGB", (64, 48), (220, 100, 50))
        encoded = jxl_engine.encode_jxl(im, quality=85)
        self.assertIsInstance(encoded, bytes)
        self.assertGreater(len(encoded), 0)

        decoded = jxl_engine.decode_jxl(encoded)
        self.assertEqual(decoded.size, (64, 48))
        self.assertEqual(decoded.mode, "RGB")

    def test_lossless_roundtrip(self) -> None:
        arr = np.random.randint(0, 255, (32, 32, 3), dtype=np.uint8)
        im = Image.fromarray(arr, mode="RGB")

        encoded = jxl_engine.encode_jxl(im, lossless=True)
        decoded = jxl_engine.decode_jxl(encoded)
        dec_arr = np.array(decoded)

        np.testing.assert_array_equal(arr, dec_arr)

    def test_rgba_alpha_preservation(self) -> None:
        im = Image.new("RGBA", (40, 40), (10, 80, 200, 128))
        encoded = jxl_engine.encode_jxl(im, quality=90)
        decoded = jxl_engine.decode_jxl(encoded)

        self.assertEqual(decoded.size, (40, 40))
        self.assertEqual(decoded.mode, "RGBA")
        # Check alpha channel is close to original
        alpha_orig = np.array(im)[:, :, 3]
        alpha_dec = np.array(decoded)[:, :, 3]
        self.assertLessEqual(np.max(np.abs(alpha_orig.astype(int) - alpha_dec.astype(int))), 5)

    def test_pillow_integration(self) -> None:
        im = Image.new("RGB", (50, 50), (30, 140, 220))
        buf = io.BytesIO()
        im.save(buf, format="JXL", quality=80)
        self.assertGreater(buf.tell(), 0)

        buf.seek(0)
        opened = Image.open(buf)
        self.assertEqual(opened.format, "JXL")
        self.assertEqual(opened.size, (50, 50))
        opened.load()
        self.assertEqual(opened.mode, "RGB")

    def test_converter_output_jxl(self) -> None:
        src = self.test_dir / "sample.png"
        Image.new("RGB", (64, 64), (100, 150, 200)).save(src, format="PNG")

        res = convert_image(
            src,
            self.test_dir,
            target_format="JXL",
            quality=85,
            lossless=False,
        )
        self.assertEqual(res.status, "Completed")
        self.assertIsNotNone(res.output_path)
        self.assertTrue(res.output_path.exists())
        self.assertEqual(res.output_path.suffix.lower(), ".jxl")

        # Verify output can be read back
        with Image.open(res.output_path) as verified:
            self.assertEqual(verified.size, (64, 64))

    def test_converter_input_jxl(self) -> None:
        src_jxl = self.test_dir / "input.jxl"
        Image.new("RGB", (48, 48), (20, 180, 90)).save(src_jxl, format="JXL", quality=90)

        res = convert_image(
            src_jxl,
            self.test_dir,
            target_format="PNG",
        )
        self.assertEqual(res.status, "Completed")
        self.assertIsNotNone(res.output_path)
        self.assertTrue(res.output_path.exists())
        self.assertEqual(res.output_path.suffix.lower(), ".png")

        with Image.open(res.output_path) as verified:
            self.assertEqual(verified.size, (48, 48))

    def test_estimate_output_size_jxl(self) -> None:
        src = self.test_dir / "test_estimate.png"
        Image.new("RGB", (80, 80), (50, 120, 180)).save(src, format="PNG")

        est_size = estimate_image_output_size(
            src,
            target_format="JXL",
            quality=80,
            lossless=False,
        )
        self.assertIsInstance(est_size, int)
        self.assertGreater(est_size, 0)


if __name__ == "__main__":
    unittest.main()
