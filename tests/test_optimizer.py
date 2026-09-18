from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from optimizer import (
    Candidate,
    block_ssim,
    encode_candidate,
    optimize_for_quality,
    optimize_for_size,
    pareto_frontier,
    profile_image,
    psnr,
    recommend,
    sweep,
)


def _photo(size: int = 256) -> Image.Image:
    base = Image.radial_gradient("L").resize((size, size))
    noise = Image.effect_noise((size, size), 12)
    return Image.merge("RGB", (base, Image.blend(base, noise, 0.3), base.rotate(90)))


class MetricTests(unittest.TestCase):
    def test_ssim_identity_and_monotonic_degradation(self) -> None:
        img = _photo()
        self.assertAlmostEqual(block_ssim(img, img), 1.0, places=4)
        scores = []
        for q in (10, 50, 90):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=q)
            buf.seek(0)
            scores.append(block_ssim(img, Image.open(buf)))
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])
        self.assertLess(block_ssim(img, Image.effect_noise(img.size, 60).convert("RGB")), 0.3)

    def test_psnr_infinite_for_identical(self) -> None:
        img = _photo(64)
        self.assertEqual(psnr(img, img), float("inf"))
        self.assertLess(psnr(img, Image.effect_noise(img.size, 60).convert("RGB")), 20)

    def test_tiny_images_do_not_crash(self) -> None:
        tiny = Image.new("RGB", (3, 5), "red")
        self.assertAlmostEqual(block_ssim(tiny, tiny), 1.0, places=4)


class ProfileTests(unittest.TestCase):
    def test_photo_vs_graphic_and_alpha(self) -> None:
        self.assertEqual(profile_image(_photo()).kind, "photo")
        flat = Image.new("RGB", (200, 200), "blue")
        self.assertEqual(profile_image(flat).kind, "graphic")
        opaque_rgba = Image.new("RGBA", (50, 50), (1, 2, 3, 255))
        self.assertFalse(profile_image(opaque_rgba).has_alpha)
        translucent = Image.new("RGBA", (50, 50), (1, 2, 3, 128))
        self.assertTrue(profile_image(translucent).has_alpha)


class SweepTests(unittest.TestCase):
    def test_sweep_webp_jpeg_and_pareto(self) -> None:
        img = _photo(200)
        cands = sweep(img, codecs=("WEBP", "JPEG"), qualities=(30, 70, 90), max_edge=200)
        self.assertEqual(len(cands), 6)
        self.assertTrue(all(c.estimated_full_bytes == c.size_bytes for c in cands))
        frontier = pareto_frontier(cands)
        self.assertTrue(frontier)
        for earlier, later in zip(frontier, frontier[1:]):
            self.assertLess(earlier.size_bytes, later.size_bytes)
            self.assertLess(earlier.ssim, later.ssim)
        self.assertEqual({c.pareto for c in frontier}, {True})

    def test_size_estimate_scales_with_working_copy(self) -> None:
        big = _photo(400)
        cands = sweep(big, codecs=("JPEG",), qualities=(70,), max_edge=200)
        self.assertEqual(len(cands), 1)
        self.assertGreater(cands[0].estimated_full_bytes, cands[0].size_bytes * 3)

    def test_alpha_image_skips_jpeg(self) -> None:
        img = Image.new("RGBA", (64, 64), (200, 30, 30, 120))
        cands = sweep(img, codecs=("WEBP", "JPEG"), qualities=(60,), max_edge=64)
        self.assertEqual({c.codec for c in cands}, {"WEBP"})

    def test_progress_and_stop(self) -> None:
        seen: list[str] = []
        cands = sweep(_photo(64), codecs=("JPEG",), qualities=(20, 40, 60), max_edge=64,
                      progress=lambda d, t, label: seen.append(label), should_stop=lambda: len(seen) >= 2)
        self.assertEqual(seen, ["JPEG q20", "JPEG q40"])
        self.assertEqual(len(cands), 2)

    def test_unknown_codec_is_none(self) -> None:
        self.assertIsNone(encode_candidate(_photo(32), "BMPX", 50))


class RecommendTests(unittest.TestCase):
    def _cands(self) -> list[Candidate]:
        mk = lambda codec, q, size, ssim: Candidate(codec, q, size, ssim, 30.0, 1.0, size)
        return [
            mk("JPEG", 40, 1000, 0.90), mk("JPEG", 80, 3000, 0.97),
            mk("WEBP", 40, 700, 0.92), mk("WEBP", 80, 2200, 0.975),
            mk("AVIF", 40, 500, 0.94), mk("AVIF", 80, 1600, 0.98),
        ]

    def test_web_picks_smallest_above_floor(self) -> None:
        profile = profile_image(_photo(32))
        reco = recommend(self._cands(), profile, "Web (modern browsers)", min_ssim=0.95)
        self.assertEqual((reco.candidate.codec, reco.candidate.quality), ("AVIF", 80))
        self.assertIn("Pareto", reco.reason)

    def test_universal_excludes_avif(self) -> None:
        profile = profile_image(_photo(32))
        reco = recommend(self._cands(), profile, "Universal compatibility", min_ssim=0.95)
        self.assertIn(reco.candidate.codec, ("JPEG", "WEBP"))

    def test_alpha_excludes_jpeg_and_unreachable_floor_falls_back(self) -> None:
        profile = profile_image(Image.new("RGBA", (32, 32), (1, 1, 1, 10)))
        reco = recommend(self._cands(), profile, "Universal compatibility", min_ssim=0.999)
        self.assertEqual(reco.candidate.codec, "WEBP")
        self.assertIn("no candidate reaches", reco.reason)
        self.assertIn("transparency", reco.reason)

    def test_no_pool(self) -> None:
        profile = profile_image(_photo(32))
        reco = recommend([], profile)
        self.assertIsNone(reco.candidate)


class SolverTests(unittest.TestCase):
    def test_optimize_for_size_hits_target(self) -> None:
        img = _photo(256)
        full = io.BytesIO()
        img.save(full, format="WEBP", quality=95, method=4)
        target = full.getbuffer().nbytes // 2
        res = optimize_for_size(img, "WEBP", target, min_ssim=0.5)
        self.assertIsNotNone(res)
        self.assertTrue(res.meets_target)
        self.assertLessEqual(res.size_bytes, target)
        self.assertTrue(res.meets_quality_floor)

    def test_optimize_for_size_rejects_layered_codecs(self) -> None:
        self.assertIsNone(optimize_for_size(_photo(32), "JPEG 2000", 1000))

    def test_optimize_for_quality_finds_low_quality_meeting_target(self) -> None:
        img = _photo(200)
        cand = optimize_for_quality(img, "JPEG", target_ssim=0.95, max_edge=200)
        self.assertIsNotNone(cand)
        self.assertGreaterEqual(cand.ssim, 0.95)
        stricter = optimize_for_quality(img, "JPEG", target_ssim=0.99, max_edge=200)
        self.assertGreaterEqual(stricter.quality, cand.quality)


class OptimizerDialogTests(unittest.TestCase):
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

    def test_dialog_analyzes_and_applies_to_main_window(self) -> None:
        from optimizer_dialog import OptimizerDialog

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "photo.png"
            _photo(160).save(path)
            app = self.app
            app._clear_all()
            app._ingest_image_paths([path])
            app.table.selection_set(app.row_ids[path.resolve()])
            app.update()
            self.assertEqual(app.optimize_button.cget("state"), "normal")

            dialog = OptimizerDialog(app, path, app._apply_optimizer_choice)
            dialog.run_analysis(synchronous=True, codecs=("WEBP", "JPEG"))
            app.update()
            self.assertEqual(len(dialog._candidates), 10)
            self.assertIsNotNone(dialog._recommendation)
            self.assertIsNotNone(dialog._recommendation.candidate)
            pick = dialog._recommendation.candidate

            dialog._apply_recommendation()
            app.update()
            self.assertEqual(app.target_format.get(), pick.codec)
            self.assertEqual(app.quality.get(), pick.quality)
            self.assertEqual(app.quality_text.get(), str(pick.quality))
            self.assertFalse(dialog.winfo_exists())
            app._clear_all()


if __name__ == "__main__":
    unittest.main()
