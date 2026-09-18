from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from converter import convert_image, solve_quality_for_ssim
from metrics import block_ssim, psnr, ssim_downscaled


def _photo(size: int = 256) -> Image.Image:
    base = Image.radial_gradient("L").resize((size, size))
    noise = Image.effect_noise((size, size), 12)
    return Image.merge("RGB", (base, Image.blend(base, noise, 0.3), base.rotate(90)))


class MetricsModuleTests(unittest.TestCase):
    def test_metrics_are_shared_with_optimizer(self) -> None:
        import optimizer

        self.assertIs(optimizer.block_ssim, block_ssim)
        self.assertIs(optimizer.psnr, psnr)

    def test_downscaled_ssim_matches_identity(self) -> None:
        img = _photo(1400)
        self.assertAlmostEqual(ssim_downscaled(img, img, max_edge=512), 1.0, places=4)


class SolverTests(unittest.TestCase):
    def test_solve_quality_for_ssim_monotonic(self) -> None:
        img = _photo(200)
        q_loose, s_loose = solve_quality_for_ssim(img, 0.90, "JPEG")
        q_tight, s_tight = solve_quality_for_ssim(img, 0.99, "JPEG")
        self.assertGreaterEqual(s_loose, 0.90)
        self.assertGreaterEqual(q_tight, q_loose)
        self.assertGreaterEqual(s_tight, s_loose)


class ConvertImageQualityTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "photo.png"
        _photo(300).save(self.src)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_target_ssim_overrides_slider_quality(self) -> None:
        out = self.dir / "out"
        hi = convert_image(self.src, out / "hi", quality=95, target_format="WEBP", target_ssim=0.99)
        lo = convert_image(self.src, out / "lo", quality=95, target_format="WEBP", target_ssim=0.90)
        self.assertEqual(hi.status, "Completed")
        self.assertEqual(lo.status, "Completed")
        self.assertIn("SSIM", hi.note)
        self.assertLess(lo.output_size, hi.output_size)

    def test_min_ssim_raises_quality_when_size_target_is_too_aggressive(self) -> None:
        out = self.dir / "out"
        unprotected = convert_image(self.src, out / "a", quality=80, target_format="JPEG", target_kb=2)
        protected = convert_image(self.src, out / "b", quality=80, target_format="JPEG", target_kb=2, min_ssim=0.97)
        self.assertEqual(unprotected.status, "Completed")
        self.assertEqual(protected.status, "Completed")
        self.assertIsNone(unprotected.note)
        self.assertIsNotNone(protected.note)
        self.assertIn("over target", protected.note)
        self.assertGreater(protected.output_size, unprotected.output_size)
        with Image.open(self.src) as original, Image.open(protected.output_path) as result:
            self.assertGreaterEqual(block_ssim(original.convert("RGB"), result.convert("RGB")), 0.965)

    def test_min_ssim_is_silent_when_target_already_meets_floor(self) -> None:
        out = self.dir / "out"
        res = convert_image(self.src, out, quality=80, target_format="WEBP", target_kb=5000, min_ssim=0.5)
        self.assertEqual(res.status, "Completed")
        self.assertIsNone(res.note)

    def test_lossless_ignores_quality_targets(self) -> None:
        res = convert_image(self.src, self.dir / "out", quality=80, target_format="WEBP", lossless=True, target_ssim=0.9)
        self.assertEqual(res.status, "Completed")
        self.assertIsNone(res.note)


class QualityTargetAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from main import WebPCompressorApp

        cls.app = WebPCompressorApp()
        cls.app.update()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.app.destroy()
        except Exception:
            pass

    def test_parse_and_recipe_round_trip(self) -> None:
        app = self.app
        app.protect_quality.set(True)
        app.min_ssim_text.set("0.93")
        app.enable_quality_target.set(False)
        self.assertEqual(app._quality_targets(), (0.93, None))
        app.enable_quality_target.set(True)
        app.target_ssim_text.set("0.97")
        self.assertEqual(app._quality_targets(), (0.93, 0.97))
        app.min_ssim_text.set("1.5")
        with self.assertRaises(ValueError):
            app._quality_targets()
        app.min_ssim_text.set("0.93")

        snapshot = app._collect_recipe_settings()
        self.assertTrue(snapshot["protect_quality"])
        self.assertEqual(snapshot["target_ssim_text"], "0.97")
        app.protect_quality.set(False)
        app._apply_recipe_settings(snapshot)
        self.assertTrue(app.protect_quality.get())
        app.protect_quality.set(False)
        app.enable_quality_target.set(False)

    def test_completed_note_is_shown_in_table(self) -> None:
        from converter import ConversionResult

        app = self.app
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.png"
            Image.new("RGB", (8, 8), "red").save(p)
            app._clear_all()
            app._ingest_image_paths([p])
            res = ConversionResult(p.resolve(), p, 10, 5, "50.0%", "Completed", note="over target: quality raised to 70")
            app._display_result(res)
            values = app.table.item(app.row_ids[p.resolve()])["values"]
            self.assertTrue(str(values[-1]).startswith("Completed · over target"))
            app._clear_all()


if __name__ == "__main__":
    unittest.main()
