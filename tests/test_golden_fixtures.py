"""Tests for golden-image visual regression fixtures."""
from __future__ import annotations

import tests._headless  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path


class GoldenFixtureTests(unittest.TestCase):
    """Test golden-image generation and verification."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")

    def test_generate_creates_source_and_golden(self):
        from golden_fixtures import GoldenFixtureRunner

        with tempfile.TemporaryDirectory() as td:
            runner = GoldenFixtureRunner(
                fixtures_dir=Path(td),
                source_size=(32, 32),
                quality=75,
            )
            results = runner.generate_all()
            # Should create source.png
            self.assertTrue((Path(td) / "source.png").is_file())
            # Should create manifest
            self.assertTrue((Path(td) / "golden_manifest.json").is_file())
            # Should have at least some golden images
            golden_dir = Path(td) / "golden"
            self.assertTrue(golden_dir.is_dir())
            golden_files = list(golden_dir.glob("golden_*"))
            self.assertGreater(len(golden_files), 0)

    def test_verify_passes_on_identical(self):
        from golden_fixtures import GoldenFixtureRunner

        with tempfile.TemporaryDirectory() as td:
            runner = GoldenFixtureRunner(
                fixtures_dir=Path(td),
                source_size=(32, 32),
                quality=75,
            )
            runner.generate_all()
            results = runner.verify_all()
            # At least some should pass
            passed = [r for r in results if r.passed]
            self.assertGreater(len(passed), 0, "At least some codecs should verify clean")

    def test_verify_no_source_raises(self):
        from golden_fixtures import GoldenFixtureRunner

        with tempfile.TemporaryDirectory() as td:
            runner = GoldenFixtureRunner(fixtures_dir=Path(td))
            with self.assertRaises(FileNotFoundError):
                runner.verify_all()

    def test_golden_result_size_delta(self):
        from golden_fixtures import GoldenResult
        r = GoldenResult("WEBP", True, 0.99, 40.0, 1000, 1100)
        self.assertAlmostEqual(r.size_delta_pct, 10.0, places=1)


class GoldenResultTests(unittest.TestCase):
    def test_zero_golden_size(self):
        from golden_fixtures import GoldenResult
        r = GoldenResult("WEBP", True, 0.99, 40.0, 0, 100)
        self.assertEqual(r.size_delta_pct, 0)


if __name__ == "__main__":
    unittest.main()
