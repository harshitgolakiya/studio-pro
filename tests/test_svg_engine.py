"""Tests for SVG and SVGZ vector ingestion, inspection, and high-resolution rasterization."""
from __future__ import annotations

import gzip
import io
from pathlib import Path
import shutil
import tempfile
import unittest

from PIL import Image

import tests._headless  # noqa: F401
from converter import convert_image, SUPPORTED_EXTENSIONS
from recipes import Recipe, coerce_settings, save_recipe, load_recipe
from svg_engine import (
    SVG_EXTENSIONS,
    extract_svg_metadata,
    is_svg_file,
    rasterize_svg,
    register_svg_opener,
    _rasterize_fallback,
)

SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <title>Test Icon</title>
  <desc>A sample vector graphic for unit testing</desc>
  <rect x="10" y="10" width="80" height="80" rx="10" fill="#2563eb" stroke="#1e40af" stroke-width="4"/>
  <circle cx="50" cy="50" r="25" fill="#f59e0b"/>
</svg>"""


class TestSvgEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_svg_")
        self.root = Path(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_sample_svg(self, filename: str = "sample.svg", content: str = SAMPLE_SVG) -> Path:
        svg_path = self.root / filename
        svg_path.write_text(content, encoding="utf-8")
        return svg_path

    def _create_sample_svgz(self, filename: str = "sample.svgz", content: str = SAMPLE_SVG) -> Path:
        svgz_path = self.root / filename
        compressed = gzip.compress(content.encode("utf-8"))
        svgz_path.write_bytes(compressed)
        return svgz_path

    def test_is_svg_file(self):
        self.assertTrue(is_svg_file("logo.svg"))
        self.assertTrue(is_svg_file("ICON.SVG"))
        self.assertTrue(is_svg_file("graphic.svgz"))
        self.assertTrue(is_svg_file("VECTOR.SVGZ"))
        self.assertIn(".svg", SUPPORTED_EXTENSIONS)
        self.assertIn(".svgz", SUPPORTED_EXTENSIONS)
        self.assertFalse(is_svg_file("photo.jpg"))
        self.assertFalse(is_svg_file("image.png"))
        self.assertFalse(is_svg_file("photo.cr2"))

    def test_extract_svg_metadata(self):
        svg_path = self._create_sample_svg()
        meta = extract_svg_metadata(svg_path)
        self.assertEqual(meta["width"], 100)
        self.assertEqual(meta["height"], 100)
        self.assertEqual(meta["title"], "Test Icon")
        self.assertEqual(meta["desc"], "A sample vector graphic for unit testing")
        self.assertEqual(meta["viewBox"], (0.0, 0.0, 100.0, 100.0))

    def test_rasterize_svg_default_1x(self):
        svg_path = self._create_sample_svg()
        im = rasterize_svg(svg_path, scale=1.0)
        self.assertIsInstance(im, Image.Image)
        self.assertEqual(im.size, (100, 100))
        self.assertEqual(im.mode, "RGBA")
        # Corner (0,0) outside the 10..90 rect should be transparent
        corner = im.getpixel((0, 0))
        self.assertEqual(corner[3], 0)

    def test_rasterize_svg_scale_multipliers(self):
        svg_path = self._create_sample_svg()
        # 2x Retina render
        im2 = rasterize_svg(svg_path, scale=2.0)
        self.assertEqual(im2.size, (200, 200))
        # 4x Ultra HD render
        im4 = rasterize_svg(svg_path, scale=4.0)
        self.assertEqual(im4.size, (400, 400))

    def test_rasterize_svg_backgrounds(self):
        svg_path = self._create_sample_svg()
        # Solid white background
        im_white = rasterize_svg(svg_path, background="white")
        corner_white = im_white.getpixel((0, 0))
        self.assertEqual(corner_white[:3], (255, 255, 255))
        self.assertEqual(corner_white[3], 255)

        # Solid black background
        im_black = rasterize_svg(svg_path, background="black")
        corner_black = im_black.getpixel((0, 0))
        self.assertEqual(corner_black[:3], (0, 0, 0))
        self.assertEqual(corner_black[3], 255)

        # Custom hex color
        im_hex = rasterize_svg(svg_path, background="#ff0000")
        corner_hex = im_hex.getpixel((0, 0))
        self.assertEqual(corner_hex[:3], (255, 0, 0))

    def test_rasterize_svgz_gzip(self):
        svgz_path = self._create_sample_svgz()
        im = rasterize_svg(svgz_path, scale=1.5)
        self.assertEqual(im.size, (150, 150))
        self.assertEqual(im.mode, "RGBA")

    def test_pillow_svg_opener_registration(self):
        register_svg_opener()
        svg_path = self._create_sample_svg("test_open.svg")
        with Image.open(svg_path) as im:
            self.assertIsNotNone(im)
            self.assertEqual(im.format, "SVG")
            self.assertEqual(im.size, (100, 100))

    def test_convert_image_svg_to_webp_scaled(self):
        svg_path = self._create_sample_svg("vector_logo.svg")
        out_dir = self.root / "out_webp"
        res = convert_image(
            svg_path,
            out_dir,
            target_format="WEBP",
            quality=90,
            svg_scale=2.0,
            svg_background="transparent",
        )
        self.assertEqual(res.status, "Completed")
        self.assertTrue(res.output_path.exists())
        self.assertEqual(res.output_path.suffix.lower(), ".webp")
        with Image.open(res.output_path) as out_im:
            self.assertEqual(out_im.format, "WEBP")
            self.assertEqual(out_im.size, (200, 200))

    def test_convert_image_svg_to_png_white_bg(self):
        svg_path = self._create_sample_svg("graphic.svg")
        out_dir = self.root / "out_png"
        res = convert_image(
            svg_path,
            out_dir,
            target_format="PNG",
            svg_scale=1.0,
            svg_background="white",
        )
        self.assertEqual(res.status, "Completed")
        self.assertTrue(res.output_path.exists())
        with Image.open(res.output_path) as out_im:
            self.assertEqual(out_im.format, "PNG")
            self.assertEqual(out_im.size, (100, 100))
            # Corner should be solid white
            corner = out_im.getpixel((0, 0))
            self.assertEqual(corner[:3], (255, 255, 255))

    def test_convert_image_svgz_to_avif(self):
        svgz_path = self._create_sample_svgz("compressed_vector.svgz")
        out_dir = self.root / "out_avif"
        res = convert_image(
            svgz_path,
            out_dir,
            target_format="AVIF",
            quality=85,
            svg_scale=3.0,
        )
        self.assertEqual(res.status, "Completed")
        self.assertTrue(res.output_path.exists())
        self.assertEqual(res.output_path.suffix.lower(), ".avif")
        with Image.open(res.output_path) as out_im:
            self.assertEqual(out_im.format, "AVIF")
            self.assertEqual(out_im.size, (300, 300))

    def test_recipes_svg_fields_persistence(self):
        raw_settings = {
            "target_format": "PNG",
            "svg_scale": "2.0x (Retina)",
            "svg_background": "White (#FFFFFF)",
        }
        coerced = coerce_settings(raw_settings)
        self.assertEqual(coerced["svg_scale"], 2.0)
        self.assertEqual(coerced["svg_background"], "white")

        recipe = Recipe(name="Vector 2x White", settings=coerced)
        path = save_recipe(recipe, directory=self.root)
        loaded = load_recipe(path)
        self.assertEqual(loaded.settings["svg_scale"], 2.0)
        self.assertEqual(loaded.settings["svg_background"], "white")

    def test_rasterize_svg_pure_python_fallback(self):
        im = _rasterize_fallback(SAMPLE_SVG, scale=1.5, background="#000000")
        self.assertIsInstance(im, Image.Image)
        self.assertEqual(im.size, (150, 150))
        self.assertEqual(im.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
