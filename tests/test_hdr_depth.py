"""Tests for 10/12/16-bit processing and HDR tone mapping."""

from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image

import tests._headless  # noqa: F401
from converter import (
    DEFAULT_OPERATION_ORDER,
    apply_image_transformations,
    convert_image,
    normalize_operation_order,
)
import hdr_tone_map
from loss_audit import compare_facts, gather_facts
from recipes import Recipe, coerce_settings


class TestHdrMathAndToneMapping(unittest.TestCase):
    """Verify transfer curves, mathematical properties, and tone mapping operators."""

    def test_aces_filmic_curve(self) -> None:
        self.assertAlmostEqual(hdr_tone_map.aces_filmic(0.0), 0.0, places=4)
        mid = hdr_tone_map.aces_filmic(0.18)
        self.assertGreater(mid, 0.15)
        self.assertLess(mid, 0.45)
        one = hdr_tone_map.aces_filmic(1.0)
        self.assertGreater(one, mid)
        self.assertLessEqual(one, 1.0)
        # Highlight roll-off over 1.0
        high = hdr_tone_map.aces_filmic(5.0)
        self.assertGreaterEqual(high, one)
        self.assertLessEqual(high, 1.0)

    def test_reinhard_curve(self) -> None:
        self.assertEqual(hdr_tone_map.reinhard(0.0), 0.0)
        half = hdr_tone_map.reinhard(1.0, white=2.0)
        self.assertGreater(half, 0.5)
        self.assertLessEqual(half, 1.0)
        two = hdr_tone_map.reinhard(2.0, white=2.0)
        self.assertAlmostEqual(two, 1.0, places=4)

    def test_linear_exposure(self) -> None:
        darker = hdr_tone_map.linear_exposure(0.5, ev=-1.0)
        self.assertAlmostEqual(darker, 0.25, places=4)
        brighter = hdr_tone_map.linear_exposure(0.4, ev=1.0)
        self.assertGreater(brighter, 0.4)
        clamped = hdr_tone_map.linear_exposure(0.9, ev=2.0)
        self.assertLessEqual(clamped, 1.0)

    def test_hlg_and_pq_transfer_functions(self) -> None:
        hlg_zero = hdr_tone_map.hlg_to_sdr(0.0)
        self.assertEqual(hlg_zero, 0.0)
        hlg_val = hdr_tone_map.hlg_to_sdr(0.8)
        self.assertGreater(hlg_val, 0.0)
        self.assertLessEqual(hlg_val, 1.0)

        pq_zero = hdr_tone_map.pq_to_sdr(0.0)
        self.assertEqual(pq_zero, 0.0)
        pq_val = hdr_tone_map.pq_to_sdr(0.7)
        self.assertGreater(pq_val, 0.0)
        self.assertLessEqual(pq_val, 1.0)

    def test_apply_tone_mapping_rgb_and_rgba(self) -> None:
        im = Image.new("RGB", (32, 32), (180, 100, 40))
        out = hdr_tone_map.apply_tone_mapping(im, method="aces", exposure=0.0)
        self.assertEqual(out.mode, "RGB")
        self.assertEqual(out.size, (32, 32))
        px = out.getpixel((0, 0))
        self.assertTrue(all(0 <= v <= 255 for v in px))

        im_rgba = Image.new("RGBA", (32, 32), (180, 100, 40, 175))
        out_rgba = hdr_tone_map.apply_tone_mapping(im_rgba, method="reinhard", exposure=0.5)
        self.assertEqual(out_rgba.mode, "RGBA")
        self.assertEqual(out_rgba.getpixel((0, 0))[3], 175)  # Alpha preserved

    def test_apply_tone_mapping_16bit_grayscale(self) -> None:
        im16 = Image.new("I;16", (32, 32), 48000)
        out = hdr_tone_map.apply_tone_mapping(im16, method="aces")
        self.assertEqual(out.mode, "L")
        val = out.getpixel((0, 0))
        self.assertGreater(val, 150)
        self.assertLessEqual(val, 255)


class TestBitDepthResolution(unittest.TestCase):
    """Verify format bit depth rules and resolution logic."""

    def test_supported_bit_depths(self) -> None:
        self.assertEqual(hdr_tone_map.supported_bit_depths("AVIF"), [8, 10, 12])
        self.assertEqual(hdr_tone_map.supported_bit_depths("HEIC"), [8, 10, 12])
        self.assertEqual(hdr_tone_map.supported_bit_depths("TIFF"), [8, 16])
        self.assertEqual(hdr_tone_map.supported_bit_depths("PNG"), [8, 16])
        self.assertEqual(hdr_tone_map.supported_bit_depths("WEBP"), [8])
        self.assertEqual(hdr_tone_map.supported_bit_depths("JPEG"), [8])

    def test_resolve_target_bit_depth(self) -> None:
        # Default auto on 8-bit source -> 8
        im8 = Image.new("RGB", (10, 10))
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(im8, "auto", "AVIF"), 8)

        # Auto on 16-bit source -> highest supported
        im16 = Image.new("I;16", (10, 10))
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(im16, "auto", "AVIF"), 12)
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(im16, "auto", "TIFF"), 16)
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(im16, "auto", "WEBP"), 8)

        # Explicit depth requests
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(None, "10", "AVIF"), 10)
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(None, "12", "AVIF"), 12)
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(None, "16", "AVIF"), 12)  # clamped to max
        self.assertEqual(hdr_tone_map.resolve_target_bit_depth(None, "10", "WEBP"), 8)   # fallback to 8


class TestRecipeBitDepthAndHdr(unittest.TestCase):
    """Verify recipe serialization and coercion for bit depth and HDR fields."""

    def test_recipe_fields_defaults_and_coercion(self) -> None:
        s = coerce_settings({})
        self.assertEqual(s["bit_depth"], "auto")
        self.assertEqual(s["hdr_tone_mapping"], "none")
        self.assertEqual(s["hdr_exposure"], 0.0)

        s2 = coerce_settings({
            "bit_depth": "10-bit (HDR / AVIF & HEIC)",
            "hdr_tone_mapping": "ACES Filmic (Cinematic)",
            "hdr_exposure": "1.5",
        })
        self.assertEqual(s2["bit_depth"], "10")
        self.assertEqual(s2["hdr_tone_mapping"], "aces")
        self.assertEqual(s2["hdr_exposure"], 1.5)

    def test_recipe_round_trip(self) -> None:
        r = Recipe(
            name="Cinematic HDR AVIF",
            settings={
                "target_format": "AVIF",
                "bit_depth": "10",
                "hdr_tone_mapping": "aces",
                "hdr_exposure": 0.5,
            },
        )
        self.assertEqual(r.settings["bit_depth"], "10")
        self.assertEqual(r.settings["hdr_tone_mapping"], "aces")
        self.assertEqual(r.settings["hdr_exposure"], 0.5)


class TestConverterHdrAndBitDepthIntegration(unittest.TestCase):
    """Verify image conversion with bit depth selection and HDR tone mapping."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_avif_10bit_and_12bit_conversion(self) -> None:
        src = self.dir_path / "sample.png"
        Image.new("RGB", (64, 64), (120, 80, 200)).save(src)

        res10 = convert_image(src, self.dir_path / "out10", target_format="AVIF", bit_depth="10")
        self.assertEqual(res10.status, "Completed")
        self.assertTrue(res10.output_path.exists())

        res12 = convert_image(src, self.dir_path / "out12", target_format="AVIF", bit_depth="12")
        self.assertEqual(res12.status, "Completed")
        self.assertTrue(res12.output_path.exists())

    def test_heic_10bit_conversion(self) -> None:
        src = self.dir_path / "sample.png"
        Image.new("RGB", (64, 64), (120, 80, 200)).save(src)

        res = convert_image(src, self.dir_path / "out_heic", target_format="HEIC", bit_depth="10")
        self.assertEqual(res.status, "Completed")
        self.assertTrue(res.output_path.exists())

    def test_16bit_source_tone_mapped_to_webp(self) -> None:
        # Create a 16-bit grayscale image
        src16 = self.dir_path / "sample_16.png"
        Image.new("I;16", (64, 64), 50000).save(src16)

        res = convert_image(
            src16,
            self.dir_path / "out_webp",
            target_format="WEBP",
            hdr_tone_mapping="aces",
            hdr_exposure=0.0,
        )
        self.assertEqual(res.status, "Completed")
        self.assertTrue(res.output_path.exists())
        with Image.open(res.output_path) as out_im:
            self.assertEqual(out_im.format, "WEBP")
            self.assertEqual(out_im.mode, "RGB")
            # Pixel should not be clipped to solid white or black
            val = out_im.getpixel((0, 0))[0]
            self.assertGreater(val, 100)
            self.assertLess(val, 255)

    def test_operation_stack_includes_tone_map(self) -> None:
        self.assertIn("tone_map", DEFAULT_OPERATION_ORDER)
        normalized = normalize_operation_order(["tone_map", "resize"])
        self.assertEqual(normalized[0], "tone_map")
        self.assertEqual(normalized[1], "resize")

    def test_loss_audit_warns_on_bit_depth_reduction(self) -> None:
        src16 = self.dir_path / "audit_16.png"
        Image.new("I;16", (64, 64), 40000).save(src16)

        res = convert_image(src16, self.dir_path / "audit_out", target_format="WEBP")
        warnings = compare_facts(gather_facts(src16), gather_facts(res.output_path))
        depth_warnings = [w for w in warnings if "Bit depth reduced" in w.title]
        self.assertTrue(len(depth_warnings) > 0)


if __name__ == "__main__":
    unittest.main()
