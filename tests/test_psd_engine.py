"""Unit and integration tests for PSD layer selection and compositing engine."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import tests._headless  # noqa: F401 - headless test runner mocks
from converter import convert_image, estimate_image_output_size
import psd_engine
from recipes import Recipe, coerce_settings

try:
    from psd_tools import PSDImage
    _HAS_PSD = True
except ImportError:
    _HAS_PSD = False


class TestPsdEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="shadow-psd-test-")
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_sample_psd(self, filename: str = "test.psd") -> Path:
        """Create a PSD file for testing using psd-tools or fallback."""
        path = self.test_dir / filename
        im = Image.new("RGBA", (64, 64), (200, 50, 80, 255))
        if _HAS_PSD:
            psd = PSDImage.frompil(im)
            psd.save(str(path))
        else:
            im.save(path, format="PSD")
        return path

    def test_psd_availability(self) -> None:
        self.assertTrue(psd_engine.is_psd_available())

    def test_psd_metadata(self) -> None:
        path = self._create_sample_psd("meta.psd")
        meta = psd_engine.get_psd_metadata(path)
        self.assertEqual(meta["width"], 64)
        self.assertEqual(meta["height"], 64)
        self.assertIn("depth", meta)

    def test_psd_layer_info(self) -> None:
        path = self._create_sample_psd("layers.psd")
        layers = psd_engine.get_psd_layer_info(path)
        self.assertIsInstance(layers, list)

    def test_composite_merged(self) -> None:
        path = self._create_sample_psd("merged.psd")
        comp = psd_engine.composite_psd(path, composite_mode="merged")
        self.assertIsInstance(comp, Image.Image)
        self.assertEqual(comp.size, (64, 64))

    def test_composite_visible(self) -> None:
        path = self._create_sample_psd("visible.psd")
        comp = psd_engine.composite_psd(path, composite_mode="visible")
        self.assertIsInstance(comp, Image.Image)
        self.assertEqual(comp.size, (64, 64))

    def test_composite_all(self) -> None:
        path = self._create_sample_psd("all.psd")
        comp = psd_engine.composite_psd(path, composite_mode="all")
        self.assertIsInstance(comp, Image.Image)
        self.assertEqual(comp.size, (64, 64))

    def test_recipe_psd_settings(self) -> None:
        settings = coerce_settings({
            "psd_composite_mode": "visible",
            "psd_layer_index": 0,
        })
        self.assertEqual(settings["psd_composite_mode"], "visible")
        self.assertEqual(settings["psd_layer_index"], 0)

        recipe = Recipe(name="PSD Test", settings=settings)
        self.assertEqual(recipe.settings["psd_composite_mode"], "visible")

    def test_convert_psd_to_webp(self) -> None:
        src = self._create_sample_psd("convert.psd")
        res = convert_image(
            src,
            self.test_dir,
            target_format="WEBP",
            psd_composite_mode="merged",
        )
        self.assertEqual(res.status, "Completed")
        self.assertIsNotNone(res.output_path)
        self.assertTrue(res.output_path.exists())
        self.assertEqual(res.output_path.suffix.lower(), ".webp")

        with Image.open(res.output_path) as im:
            self.assertEqual(im.size, (64, 64))

    def test_estimate_output_size_psd(self) -> None:
        src = self._create_sample_psd("estimate.psd")
        est = estimate_image_output_size(
            src,
            target_format="PNG",
            psd_composite_mode="merged",
        )
        self.assertIsInstance(est, int)
        self.assertGreater(est, 0)


if __name__ == "__main__":
    unittest.main()
