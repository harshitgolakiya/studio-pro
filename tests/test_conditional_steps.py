from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401

from PIL import Image

from converter import (
    apply_image_transformations,
    compute_resize_dims,
    convert_image,
)
from recipes import Recipe, coerce_settings


class ConditionalResizeTests(unittest.TestCase):
    def test_always_condition(self) -> None:
        # Normal resize should occur when condition is "always"
        self.assertEqual(
            compute_resize_dims((1920, 1080), None, 1280, 1280, condition="always"),
            (1280, 720),
        )

    def test_only_above_4k(self) -> None:
        # Standard 4K UHD is 3840x2160 (or max dim >= 3840, or >= 8.29 MP)
        dims_4k = compute_resize_dims((3840, 2160), None, 1920, 1920, condition="only_above_4k")
        self.assertEqual(dims_4k, (1920, 1080))

        # Vertical 4K (2160x3840)
        dims_4k_vert = compute_resize_dims((2160, 3840), None, 1080, 1080, condition="only_above_4k")
        self.assertEqual(dims_4k_vert, (608, 1080))

        # Square 4K (3000x3000 = 9 MP > 8.29 MP)
        dims_4k_square = compute_resize_dims((3000, 3000), None, 1500, 1500, condition="only_above_4k")
        self.assertEqual(dims_4k_square, (1500, 1500))

        # 1080p image (1920x1080) should NOT be resized under only_above_4k
        dims_1080p = compute_resize_dims((1920, 1080), None, 1280, 1280, condition="only_above_4k")
        self.assertIsNone(dims_1080p)

        # 1440p image (2560x1440) should NOT be resized under only_above_4k
        dims_1440p = compute_resize_dims((2560, 1440), None, 1280, 1280, condition="only_above_4k")
        self.assertIsNone(dims_1440p)

    def test_only_above_2k(self) -> None:
        # 2K / QHD: max dim >= 2560 or >= 3.68 MP
        dims_2k = compute_resize_dims((2560, 1440), None, 1280, 1280, condition="only_above_2k")
        self.assertEqual(dims_2k, (1280, 720))

        # 1080p image (1920x1080) should NOT be resized under only_above_2k
        dims_1080p = compute_resize_dims((1920, 1080), None, 1280, 1280, condition="only_above_2k")
        self.assertIsNone(dims_1080p)

    def test_only_if_larger(self) -> None:
        # Larger image should be resized down
        dims_larger = compute_resize_dims((1920, 1080), None, 800, 800, condition="only_if_larger")
        self.assertEqual(dims_larger, (800, 450))

        # Smaller image should NOT be resized
        dims_smaller = compute_resize_dims((640, 480), None, 800, 800, condition="only_if_larger")
        self.assertIsNone(dims_smaller)


class ConditionalWatermarkTests(unittest.TestCase):
    def test_watermark_condition_filtering(self) -> None:
        watermarked_flags = []

        def mock_watermark(im: Image.Image) -> Image.Image:
            watermarked_flags.append(im.size)
            return im

        # 1. Always condition
        watermarked_flags.clear()
        img_small = Image.new("RGB", (400, 300), color=(100, 100, 100))
        apply_image_transformations(
            img_small,
            watermark_fn=mock_watermark,
            watermark_condition="always",
        )
        self.assertEqual(len(watermarked_flags), 1)

        # 2. Only if >= 800px
        watermarked_flags.clear()
        apply_image_transformations(
            img_small,  # 400x300 < 800
            watermark_fn=mock_watermark,
            watermark_condition="only_if_>=_800px",
        )
        self.assertEqual(len(watermarked_flags), 0, "Small image should skip watermark")

        img_large = Image.new("RGB", (1200, 900), color=(100, 100, 100))
        apply_image_transformations(
            img_large,  # 1200x900 >= 800
            watermark_fn=mock_watermark,
            watermark_condition="only_if_>=_800px",
        )
        self.assertEqual(len(watermarked_flags), 1, "Large image should receive watermark")

        # 3. Only if >= 1200px
        watermarked_flags.clear()
        img_mid = Image.new("RGB", (1000, 750), color=(100, 100, 100))
        apply_image_transformations(
            img_mid,
            watermark_fn=mock_watermark,
            watermark_condition="only_if_>=_1200px",
        )
        self.assertEqual(len(watermarked_flags), 0, "1000px image should skip >=1200px watermark")

        apply_image_transformations(
            img_large,
            watermark_fn=mock_watermark,
            watermark_condition="only_if_>=_1200px",
        )
        self.assertEqual(len(watermarked_flags), 1, "1200px image should receive >=1200px watermark")


class ConditionalEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src_4k = self.dir / "src_4k.png"
        self.src_1080p = self.dir / "src_1080p.png"

        Image.new("RGB", (3840, 2160), color=(50, 120, 200)).save(self.src_4k)
        Image.new("RGB", (1920, 1080), color=(50, 120, 200)).save(self.src_1080p)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_convert_image_with_4k_condition(self) -> None:
        out_dir = self.dir / "out"
        out_dir.mkdir()

        # Convert 4K image: should be resized down to 1920
        res_4k = convert_image(
            self.src_4k,
            out_dir,
            target_format="webp",
            max_width=1920,
            max_height=1920,
            resize_condition="only_above_4k",
        )
        self.assertEqual(res_4k.status, "Completed")
        with Image.open(res_4k.output_path) as im:
            self.assertEqual(im.size, (1920, 1080))

        # Convert 1080p image with same rule: should remain 1920x1080
        res_1080p = convert_image(
            self.src_1080p,
            out_dir,
            target_format="webp",
            max_width=1280,
            max_height=1280,
            resize_condition="only_above_4k",
        )
        self.assertEqual(res_1080p.status, "Completed")
        with Image.open(res_1080p.output_path) as im:
            self.assertEqual(im.size, (1920, 1080))


class RecipeConditionSchemaTests(unittest.TestCase):
    def test_default_backward_compatibility(self) -> None:
        # Older recipe missing condition keys defaults cleanly to "always"
        old_recipe = {
            "target_format": "WEBP",
            "quality": 80,
            "enable_resize": True,
            "max_dimension_text": "1920",
        }
        coerced = coerce_settings(old_recipe)
        self.assertEqual(coerced["resize_condition"], "always")
        self.assertEqual(coerced["watermark_condition"], "always")

    def test_custom_conditions_coercion(self) -> None:
        settings = {
            "target_format": "WEBP",
            "resize_condition": "Only above 4K",
            "watermark_condition": "Only if ≥ 800px",
        }
        coerced = coerce_settings(settings)
        self.assertEqual(coerced["resize_condition"], "only_above_4k")
        self.assertEqual(coerced["watermark_condition"], "only_if_>=_800px")

    def test_recipe_roundtrip(self) -> None:
        rec = Recipe(
            name="Conditional 4K Recipe",
            settings={
                "target_format": "WEBP",
                "enable_resize": True,
                "resize_condition": "only_above_4k",
                "watermark_condition": "only_if_>=_1200px",
            },
        )
        self.assertEqual(rec.settings["resize_condition"], "only_above_4k")
        self.assertEqual(rec.settings["watermark_condition"], "only_if_>=_1200px")


if __name__ == "__main__":
    unittest.main()
