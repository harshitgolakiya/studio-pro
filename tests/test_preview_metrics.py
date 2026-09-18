from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from preview_modal import calculate_comparison_metrics


class PreviewMetricTests(unittest.TestCase):
    def test_identical_images_have_perfect_metrics(self) -> None:
        image = Image.new("RGBA", (32, 24), (10, 20, 30, 200))

        metrics = calculate_comparison_metrics(image, image.copy())

        self.assertTrue(math.isinf(float(metrics["psnr"])))
        self.assertEqual(metrics["mae"], 0)
        self.assertEqual(metrics["similarity"], 100)
        self.assertFalse(metrics["sampled"])

    def test_opposite_images_have_zero_similarity(self) -> None:
        black = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        white = Image.new("RGBA", (16, 16), (255, 255, 255, 255))

        metrics = calculate_comparison_metrics(black, white)

        self.assertAlmostEqual(float(metrics["psnr"]), 0.0, places=6)
        self.assertAlmostEqual(float(metrics["mae"]), 255.0, places=6)
        self.assertAlmostEqual(float(metrics["similarity"]), 0.0, places=6)

    def test_large_images_are_sampled(self) -> None:
        first = Image.new("RGB", (200, 100), "red")
        second = Image.new("RGB", (200, 100), "blue")

        metrics = calculate_comparison_metrics(first, second, max_pixels=1_000)

        self.assertTrue(metrics["sampled"])
        self.assertGreaterEqual(float(metrics["similarity"]), 0)
        self.assertLessEqual(float(metrics["similarity"]), 100)


if __name__ == "__main__":
    unittest.main()
