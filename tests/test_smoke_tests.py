"""Tests for smoke tests and crash reporting."""
from __future__ import annotations

import tests._headless  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path


class SmokeTestRunnerTests(unittest.TestCase):
    """Test that smoke test functions work correctly."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")

    def test_smoke_test_import(self):
        from smoke_tests import smoke_test_import
        result = smoke_test_import()
        self.assertTrue(result.passed, result.message)
        self.assertIn("import", result.test_name)

    def test_smoke_test_conversion(self):
        from smoke_tests import smoke_test_conversion
        with tempfile.TemporaryDirectory() as td:
            result = smoke_test_conversion(Path(td))
            self.assertTrue(result.passed, result.message)

    def test_smoke_test_metrics(self):
        from smoke_tests import smoke_test_metrics
        result = smoke_test_metrics()
        self.assertTrue(result.passed, result.message)

    def test_run_all_smoke_tests(self):
        from smoke_tests import run_all_smoke_tests
        with tempfile.TemporaryDirectory() as td:
            results = run_all_smoke_tests(Path(td))
            self.assertGreaterEqual(len(results), 3)
            for r in results:
                self.assertTrue(r.passed, f"{r.test_name}: {r.message}")

    def test_platform_info(self):
        from smoke_tests import get_platform_info
        info = get_platform_info()
        self.assertIn("os", info)
        self.assertIn("arch", info)
        self.assertIn("python", info)


class CrashReporterTests(unittest.TestCase):
    """Test crash reporter."""

    def test_disabled_reporter_returns_none(self):
        from smoke_tests import CrashReporter
        reporter = CrashReporter(enabled=False)
        result = reporter.report(ValueError("test"))
        self.assertIsNone(result)

    def test_enabled_reporter_saves_report(self):
        from smoke_tests import CrashReporter
        with tempfile.TemporaryDirectory() as td:
            reporter = CrashReporter(enabled=True)
            reporter._reports_dir = Path(td) / "crashes"
            result = reporter.report(ValueError("test error"), {"context": "testing"})
            self.assertIsNotNone(result)
            self.assertEqual(result.error_type, "ValueError")
            self.assertEqual(result.message, "test error")
            # Check file was saved
            reports = list((Path(td) / "crashes").glob("crash_*.json"))
            self.assertEqual(len(reports), 1)

    def test_list_and_clear_reports(self):
        from smoke_tests import CrashReporter
        with tempfile.TemporaryDirectory() as td:
            reporter = CrashReporter(enabled=True)
            reporter._reports_dir = Path(td) / "crashes"
            reporter.report(RuntimeError("err1"))
            reporter.report(RuntimeError("err2"))
            reports = reporter.list_reports()
            self.assertEqual(len(reports), 2)
            cleared = reporter.clear_reports()
            self.assertEqual(cleared, 2)
            self.assertEqual(len(reporter.list_reports()), 0)

    def test_prune_old_reports(self):
        from smoke_tests import CrashReporter
        with tempfile.TemporaryDirectory() as td:
            reporter = CrashReporter(enabled=True, max_reports=2)
            reporter._reports_dir = Path(td) / "crashes"
            for i in range(5):
                reporter.report(RuntimeError(f"err{i}"))
            reports = reporter.list_reports()
            self.assertLessEqual(len(reports), 2)


class UpdateCheckTests(unittest.TestCase):
    def test_check_for_updates_stub(self):
        from smoke_tests import check_for_updates
        info = check_for_updates("1.0.0")
        self.assertFalse(info.update_available)
        self.assertEqual(info.current_version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
