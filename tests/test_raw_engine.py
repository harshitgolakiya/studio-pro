"""Tests for camera RAW engine, LibRaw postprocessing, preview fallback, and integration."""
from __future__ import annotations

import io
from pathlib import Path
import shutil
import tempfile
import unittest

from PIL import Image

import tests._headless  # noqa: F401
from converter import convert_image, SUPPORTED_EXTENSIONS
from loss_audit import gather_facts
from raw_engine import (
    RAW_EXTENSIONS,
    develop_raw,
    extract_embedded_preview,
    extract_raw_metadata,
    is_raw_file,
    register_raw_opener,
)
from recipes import Recipe, coerce_settings, save_recipe, load_recipe


class TestRawEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_raw_")
        self.root = Path(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_synthetic_raw_with_embedded_jpeg(self, filename: str) -> Path:
        """Create a synthetic RAW file with a header, padding, and embedded JPEG."""
        raw_path = self.root / filename
        jpeg_buf = io.BytesIO()
        test_img = Image.new("RGB", (64, 64), color=(200, 100, 50))
        test_img.save(jpeg_buf, format="JPEG", quality=85)
        jpeg_bytes = jpeg_buf.getvalue()

        with open(raw_path, "wb") as f:
            f.write(b"RAW_HEADER_DATA_1234567890\x00\x01\x02\x03")
            f.write(b"\x00" * 256)
            f.write(jpeg_bytes)
            f.write(b"\x00" * 64)
        return raw_path

    def _create_synthetic_16bit_dng(self, filename: str) -> Path:
        """Create a 16-bit uncompressed TIFF structure with a .dng extension."""
        dng_path = self.root / filename
        import numpy as np
        data = (np.ones((32, 32), dtype=np.uint16) * 32768)
        img16 = Image.fromarray(data)
        img16.save(dng_path, format="TIFF")
        return dng_path

    def test_is_raw_image(self):
        for ext in (".cr2", ".cr3", ".nef", ".nrw", ".arw", ".raf", ".orf", ".rw2", ".pef", ".dng"):
            self.assertTrue(is_raw_file(f"photo{ext}"))
            self.assertTrue(is_raw_file(f"PHOTO{ext.upper()}"))
            self.assertIn(ext, SUPPORTED_EXTENSIONS)
        self.assertFalse(is_raw_file("photo.jpg"))
        self.assertFalse(is_raw_file("photo.png"))
        self.assertFalse(is_raw_file("video.mp4"))

    def test_extract_embedded_preview_valid(self):
        raw_path = self._create_synthetic_raw_with_embedded_jpeg("sample.cr2")
        extracted = extract_embedded_preview(raw_path)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.size, (64, 64))

    def test_extract_embedded_preview_missing(self):
        empty_raw = self.root / "empty.nef"
        empty_raw.write_bytes(b"RANDOM_NO_JPEG_BYTES_00000000000000000000000000")
        extracted = extract_embedded_preview(empty_raw)
        self.assertIsNone(extracted)

    def test_raw_metadata_fallback(self):
        raw_path = self._create_synthetic_raw_with_embedded_jpeg("sample.arw")
        meta = extract_raw_metadata(raw_path)
        self.assertIsInstance(meta, dict)
        for key in ("camera_make", "camera_model", "iso", "exposure_time", "f_number", "focal_length", "datetime"):
            self.assertIn(key, meta)

    def test_pillow_raw_opener_registration(self):
        register_raw_opener()
        raw_path = self._create_synthetic_raw_with_embedded_jpeg("test_open.nef")
        with Image.open(raw_path) as im:
            self.assertIsNotNone(im)
            self.assertEqual(im.size, (64, 64))

    def test_develop_raw_preview_fallback(self):
        raw_path = self._create_synthetic_raw_with_embedded_jpeg("sample.raf")
        developed = develop_raw(
            raw_path,
            wb="daylight",
            exposure=1.0,
            demosaic="auto",
            output_bps=8,
        )
        self.assertIsInstance(developed, Image.Image)
        self.assertEqual(developed.size, (64, 64))

    def test_develop_raw_16bit_dng(self):
        dng_path = self._create_synthetic_16bit_dng("sample.dng")
        developed = develop_raw(dng_path, output_bps=16)
        self.assertIsInstance(developed, Image.Image)
        self.assertEqual(developed.size, (32, 32))

    def test_convert_image_raw_to_webp(self):
        raw_path = self._create_synthetic_raw_with_embedded_jpeg("camera.cr2")
        out_dir = self.root / "out_webp"
        res = convert_image(
            raw_path,
            out_dir,
            target_format="WEBP",
            quality=85,
            raw_white_balance="daylight",
            raw_exposure=0.5,
            raw_demosaic="auto",
        )
        self.assertEqual(res.status, "Completed")
        self.assertIsNotNone(res.output_path)
        self.assertTrue(res.output_path.exists())
        self.assertEqual(res.output_path.suffix.lower(), ".webp")
        with Image.open(res.output_path) as out_img:
            self.assertEqual(out_img.format, "WEBP")
            self.assertEqual(out_img.size, (64, 64))

    def test_convert_image_raw_to_avif(self):
        raw_path = self._create_synthetic_raw_with_embedded_jpeg("camera.nef")
        out_dir = self.root / "out_avif"
        res = convert_image(
            raw_path,
            out_dir,
            target_format="AVIF",
            quality=80,
            raw_white_balance="auto",
        )
        self.assertEqual(res.status, "Completed")
        self.assertTrue(res.output_path.exists())
        self.assertEqual(res.output_path.suffix.lower(), ".avif")

    def test_convert_image_raw_to_tiff_16bit(self):
        dng_path = self._create_synthetic_16bit_dng("master.dng")
        out_dir = self.root / "out_tiff"
        res = convert_image(
            dng_path,
            out_dir,
            target_format="TIFF",
            bit_depth="16",
        )
        self.assertEqual(res.status, "Completed")
        self.assertTrue(res.output_path.exists())
        with Image.open(res.output_path) as out_im:
            self.assertEqual(out_im.format, "TIFF")

    def test_recipes_raw_fields_persistence(self):
        raw_settings = {
            "target_format": "AVIF",
            "quality": 88,
            "raw_white_balance": "Daylight (5500K)",
            "raw_exposure": 1.5,
            "raw_demosaic": "AHD (Adaptive Homogeneity)",
        }
        coerced = coerce_settings(raw_settings)
        self.assertEqual(coerced["raw_white_balance"], "daylight")
        self.assertEqual(coerced["raw_exposure"], 1.5)
        self.assertEqual(coerced["raw_demosaic"], "ahd")

        recipe = Recipe(name="Raw Studio", settings=coerced)
        recipe_path = save_recipe(recipe, directory=self.root)
        loaded = load_recipe(recipe_path)
        self.assertEqual(loaded.settings["raw_white_balance"], "daylight")
        self.assertEqual(loaded.settings["raw_exposure"], 1.5)
        self.assertEqual(loaded.settings["raw_demosaic"], "ahd")

    def test_loss_audit_raw_facts(self):
        raw_path = self._create_synthetic_raw_with_embedded_jpeg("audit_raw.cr2")
        facts = gather_facts(raw_path)
        self.assertEqual(facts.width, 64)
        self.assertEqual(facts.height, 64)
        self.assertGreaterEqual(facts.bit_depth, 14)


if __name__ == "__main__":
    unittest.main()
