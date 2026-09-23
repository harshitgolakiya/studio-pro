"""Tests for performance benchmarks."""
from __future__ import annotations

import tests._headless  # noqa: F401

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path


class BenchmarkTests(unittest.TestCase):
    """Test benchmark functions."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")

    def test_bench_ssim(self):
        from benchmarks import bench_ssim
        result = bench_ssim(image_size=(64, 64), iterations=2)
        self.assertIn("ssim", result.name)
        self.assertGreater(result.duration_ms, 0)

    def test_bench_psnr(self):
        from benchmarks import bench_psnr
        result = bench_psnr(image_size=(64, 64), iterations=2)
        self.assertIn("psnr", result.name)
        self.assertGreater(result.duration_ms, 0)

    def test_bench_conversion(self):
        from benchmarks import bench_conversion
        result = bench_conversion("WEBP", image_size=(64, 64), iterations=2)
        self.assertIn("webp", result.name)
        self.assertGreater(result.duration_ms, 0)
        self.assertGreater(result.throughput, 0)

    def test_save_and_load_baseline(self):
        from benchmarks import BenchmarkResult, save_baseline, load_baseline
        with tempfile.TemporaryDirectory() as td:
            results = [
                BenchmarkResult("test_a", 100.0),
                BenchmarkResult("test_b", 200.0),
            ]
            with unittest.mock.patch("benchmarks._benchmarks_dir", return_value=Path(td)):
                path = save_baseline(results, "unit_test")
                self.assertTrue(path.is_file())
                baseline = load_baseline()
                self.assertEqual(baseline["test_a"], 100.0)
                self.assertEqual(baseline["test_b"], 200.0)

    def test_check_regressions_pass(self):
        from benchmarks import BenchmarkResult, check_regressions
        current = [BenchmarkResult("a", 100.0), BenchmarkResult("b", 210.0)]
        baseline = {"a": 100.0, "b": 200.0}
        checks = check_regressions(current, baseline, threshold=0.20)
        for c in checks:
            self.assertTrue(c.passed, c.message)

    def test_check_regressions_fail(self):
        from benchmarks import BenchmarkResult, check_regressions
        current = [BenchmarkResult("slow", 300.0)]
        baseline = {"slow": 100.0}
        checks = check_regressions(current, baseline, threshold=0.20)
        self.assertFalse(checks[0].passed)
        self.assertIn("REGRESSION", checks[0].message)

    def test_check_regressions_no_baseline(self):
        from benchmarks import BenchmarkResult, check_regressions
        current = [BenchmarkResult("new", 100.0)]
        checks = check_regressions(current, {})
        self.assertTrue(checks[0].passed)
        self.assertIn("No baseline", checks[0].message)


if __name__ == "__main__":
    unittest.main()
