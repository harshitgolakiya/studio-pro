from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401

from PIL import Image, ImageCms

import color_manager
from converter import (
    DEFAULT_OPERATION_ORDER,
    apply_image_transformations,
    convert_image,
    normalize_operation_order,
)
from loss_audit import ImageFacts, compare_facts
from recipes import Recipe, coerce_settings


class ColorProfileGenerationTests(unittest.TestCase):
    def test_srgb_profile(self) -> None:
        raw = color_manager.get_srgb_profile_bytes()
        self.assertGreater(len(raw), 100)
        prof = ImageCms.ImageCmsProfile(io.BytesIO(raw))
        desc = color_manager.describe_profile(prof)
        self.assertIn("sRGB", desc)
        self.assertFalse(color_manager.is_wide_gamut(raw))

    def test_display_p3_profile(self) -> None:
        raw = color_manager.get_display_p3_profile_bytes()
        self.assertGreater(len(raw), 500)
        prof = ImageCms.ImageCmsProfile(io.BytesIO(raw))
        desc = color_manager.describe_profile(prof)
        self.assertIn("Display P3", desc)
        self.assertTrue(color_manager.is_wide_gamut(raw))

    def test_adobe_rgb_profile(self) -> None:
        raw = color_manager.get_adobe_rgb_profile_bytes()
        self.assertGreater(len(raw), 300)
        prof = ImageCms.ImageCmsProfile(io.BytesIO(raw))
        desc = color_manager.describe_profile(prof)
        self.assertIn("Adobe RGB", desc)
        self.assertTrue(color_manager.is_wide_gamut(raw))


class ColorConversionTests(unittest.TestCase):
    def test_convert_srgb_to_display_p3(self) -> None:
        im = Image.new("RGB", (20, 20), color=(255, 0, 0))
        out_im, out_bytes, note = color_manager.convert_color_profile(im, "display_p3")
        self.assertEqual(out_im.size, (20, 20))
        self.assertIsNotNone(out_bytes)
        self.assertIn("Display P3", note or "")
        # Pure red in sRGB is less saturated than P3 primary red, so coordinates in P3 are < 255
        pixel = out_im.getpixel((0, 0))
        self.assertLess(pixel[0], 255)
        self.assertGreater(pixel[1], 0)  # slightly shifted into green

    def test_convert_p3_to_srgb(self) -> None:
        p3_bytes = color_manager.get_display_p3_profile_bytes()
        im = Image.new("RGB", (20, 20), color=(234, 51, 35))
        im.info["icc_profile"] = p3_bytes

        out_im, out_bytes, note = color_manager.convert_color_profile(im, "srgb")
        self.assertEqual(out_im.size, (20, 20))
        self.assertIsNotNone(out_bytes)
        pixel = out_im.getpixel((0, 0))
        # (234, 51, 35) in P3 round-trips to ~ (255, 0, 0) in sRGB
        self.assertGreaterEqual(pixel[0], 250)
        self.assertLessEqual(pixel[1], 5)

    def test_convert_rgb_to_cmyk(self) -> None:
        im = Image.new("RGB", (10, 10), color=(0, 120, 250))
        out_im, _, note = color_manager.convert_color_profile(im, "cmyk")
        self.assertEqual(out_im.mode, "CMYK")
        self.assertIn("CMYK", note or "")

    def test_convert_preserves_alpha(self) -> None:
        im = Image.new("RGBA", (10, 10), color=(200, 100, 50, 128))
        out_im, _, _ = color_manager.convert_color_profile(im, "display_p3")
        self.assertEqual(out_im.mode, "RGBA")
        self.assertEqual(out_im.getpixel((0, 0))[3], 128)


class GamutClippingTests(unittest.TestCase):
    def test_untagged_image_zero_clipping(self) -> None:
        # Untagged source is assumed sRGB, so converting to sRGB has 0% clipping
        im = Image.new("RGB", (50, 50), color=(255, 100, 50))
        clip = color_manager.calculate_gamut_clipping(im, "srgb")
        self.assertEqual(clip, 0.0)

    def test_p3_wide_gamut_out_of_gamut_clipping(self) -> None:
        p3_bytes = color_manager.get_display_p3_profile_bytes()
        # Saturated primary red in P3 cannot be represented in sRGB without clipping
        im = Image.new("RGB", (50, 50), color=(255, 0, 0))
        im.info["icc_profile"] = p3_bytes
        clip = color_manager.calculate_gamut_clipping(im, "srgb")
        self.assertGreater(clip, 50.0)


class PipelineColorIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "photo.png"
        Image.new("RGB", (100, 80), color=(180, 90, 40)).save(self.src)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_apply_image_transformations_color_step(self) -> None:
        im = Image.new("RGB", (50, 50), color=(255, 0, 0))
        out = apply_image_transformations(
            im,
            color_profile_mode="display_p3",
        )
        self.assertEqual(out.size, (50, 50))
        self.assertLess(out.getpixel((0, 0))[0], 255)

    def test_convert_image_embeds_target_icc(self) -> None:
        out_dir = self.dir / "out"
        out_dir.mkdir()

        # 1. Convert to WebP with Display P3
        res = convert_image(
            self.src,
            out_dir,
            target_format="webp",
            color_profile_mode="display_p3",
        )
        self.assertEqual(res.status, "Completed")
        self.assertIsNotNone(res.output_path)
        with Image.open(res.output_path) as im:
            self.assertIn("icc_profile", im.info)
            desc = color_manager.describe_profile(im.info["icc_profile"])
            self.assertIn("Display P3", desc)

        # 2. Convert to JPEG with sRGB
        res_jpeg = convert_image(
            self.src,
            out_dir,
            target_format="jpeg",
            color_profile_mode="srgb",
        )
        self.assertEqual(res_jpeg.status, "Completed")
        self.assertIsNotNone(res_jpeg.output_path)
        with Image.open(res_jpeg.output_path) as im:
            self.assertIn("icc_profile", im.info)
            desc = color_manager.describe_profile(im.info["icc_profile"])
            self.assertIn("sRGB", desc)

    def test_convert_image_to_cmyk_jpeg(self) -> None:
        out_dir = self.dir / "out_cmyk"
        out_dir.mkdir()

        res = convert_image(
            self.src,
            out_dir,
            target_format="jpeg",
            color_profile_mode="cmyk",
        )
        self.assertEqual(res.status, "Completed")
        self.assertIsNotNone(res.output_path)
        with Image.open(res.output_path) as im:
            self.assertEqual(im.mode, "CMYK")


class RecipeColorSchemaTests(unittest.TestCase):
    def test_recipe_order_contains_color(self) -> None:
        self.assertIn("color", DEFAULT_OPERATION_ORDER)
        order = normalize_operation_order("rotate,resize")
        self.assertIn("color", order)

    def test_recipe_coercion_defaults(self) -> None:
        coerced = coerce_settings({})
        self.assertEqual(coerced["color_profile_mode"], "preserve")
        self.assertEqual(coerced["color_profile_custom"], "")
        self.assertEqual(coerced["rendering_intent"], "relative_colorimetric")

    def test_recipe_custom_values(self) -> None:
        rec = Recipe(
            name="Color Workflow Recipe",
            settings={
                "target_format": "WEBP",
                "color_profile_mode": "Convert to Display P3 (Wide Gamut)",
                "rendering_intent": "Perceptual",
            },
        )
        self.assertEqual(rec.settings["color_profile_mode"], "display_p3")
        self.assertEqual(rec.settings["rendering_intent"], "perceptual")


class LossAuditColorTests(unittest.TestCase):
    def test_wide_gamut_to_srgb_warning(self) -> None:
        src = ImageFacts(
            width=100, height=100, mode="RGB", frames=1,
            has_transparency=False, has_exif=False, has_gps=False,
            icc_name="Display P3", has_icc=True, size_bytes=1000,
        )
        out = ImageFacts(
            width=100, height=100, mode="RGB", frames=1,
            has_transparency=False, has_exif=False, has_gps=False,
            icc_name="sRGB", has_icc=True, size_bytes=900,
        )
        warnings = compare_facts(src, out)
        warning_titles = [w.title for w in warnings]
        self.assertIn("Wide-gamut converted to sRGB", warning_titles)


if __name__ == "__main__":
    unittest.main()
