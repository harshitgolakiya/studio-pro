from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from converter import ConversionResult
from history import (
    MAX_ENTRIES,
    clear_history,
    load_history,
    record_batch,
    search_history,
    summarize,
)


class HistoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _results(self) -> list[ConversionResult]:
        a, b = Path("C:/pics/a.jpg"), Path("C:/pics/b.png")
        return [
            ConversionResult(a, Path("C:/out/a.webp"), 1000, 400, "60.0%", "Completed"),
            ConversionResult(b, None, 500, None, "-", "Failed", "cannot identify image"),
        ]

    def test_record_and_load_newest_first_with_settings(self) -> None:
        batch = record_batch(self._results(), {"quality": "72", "enable_resize": True}, "WEBP", self.path)
        entries = load_history(self.path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].source_name, "b.png")  # newest (last written) first
        self.assertEqual({e.batch_id for e in entries}, {batch})
        self.assertEqual(entries[1].settings["quality"], 72)
        self.assertTrue(entries[1].settings["enable_resize"])
        self.assertEqual(entries[1].target_format, "WEBP")
        self.assertEqual(entries[0].error, "cannot identify image")

    def test_search_and_summary(self) -> None:
        record_batch(self._results(), {}, "WEBP", self.path)
        entries = load_history(self.path)
        self.assertEqual([e.source_name for e in search_history(entries, "failed")], ["b.png"])
        self.assertEqual([e.source_name for e in search_history(entries, "a.jpg webp")], ["a.jpg"])
        self.assertEqual(search_history(entries, "zzz"), [])
        s = summarize(entries)
        self.assertEqual((s["items"], s["completed"], s["failed"], s["bytes_saved"], s["batches"]), (2, 1, 1, 600, 1))

    def test_malformed_lines_skipped_and_trim(self) -> None:
        self.path.write_text("{not json}\n\n", encoding="utf-8")
        record_batch(self._results()[:1], {}, "PNG", self.path)
        self.assertEqual(len(load_history(self.path)), 1)
        many = [ConversionResult(Path(f"x{i}.png"), None, 1, 1, "0%", "Completed") for i in range(MAX_ENTRIES + 10)]
        record_batch(many, {}, "PNG", self.path)
        self.assertEqual(len(self.path.read_text(encoding="utf-8").splitlines()), MAX_ENTRIES)
        self.assertEqual(len(load_history(self.path, limit=5)), 5)

    def test_clear(self) -> None:
        record_batch(self._results(), {}, "WEBP", self.path)
        clear_history(self.path)
        clear_history(self.path)
        self.assertEqual(load_history(self.path), [])


class DiagnosticsTests(unittest.TestCase):
    def test_system_report_and_bundle(self) -> None:
        from diagnostics import export_diagnostics, redacted_settings, setup_logging, system_report

        report = system_report()
        for key in ("app_version", "python", "platform", "pillow", "ffmpeg", "pillow_features"):
            self.assertIn(key, report)
        settings = redacted_settings()
        self.assertNotIn("PRO-", str(settings.get("license_key", "")))

        logger = setup_logging()
        logger.info("diagnostics test line")
        self.assertIs(setup_logging(), logger)

        with tempfile.TemporaryDirectory() as tmp:
            out = export_diagnostics(Path(tmp))
            self.assertTrue(out.name.startswith("shadow-diagnostics-"))
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertIn("system.json", names)
                self.assertIn("settings.json", names)
                data = json.loads(zf.read("settings.json"))
                self.assertNotIn("PRO-", str(data.get("license_key", "")))


class HistoryAppTests(unittest.TestCase):
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

    def test_batch_completion_records_history_and_reapply(self) -> None:
        import history as H
        from history_dialog import HistoryDialog

        app = self.app
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / "history.jsonl"
            original = H.history_path
            H.history_path = lambda: hist
            try:
                app.target_format.set("AVIF")
                app.quality.set(61)
                app.quality_text.set("61")
                results = [ConversionResult(Path(tmp) / "a.png", None, 10, 5, "50.0%", "Completed")]
                app.events.put(("complete", (results, False, 0.5)))
                app.conversion_running = True
                app._process_events()
                self.assertFalse(app.conversion_running)
                entries = H.load_history(hist)
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].target_format, "AVIF")
                self.assertEqual(entries[0].settings["quality"], 61)

                app.target_format.set("PNG")
                app.quality.set(90)
                dialog = HistoryDialog(app, app._apply_recipe_settings)
                dialog.update()
                self.assertEqual(len(dialog._visible), 1)
                dialog.table.selection_set("0")
                dialog._reapply()
                app.update()
                self.assertEqual(app.target_format.get(), "AVIF")
                self.assertEqual(app.quality.get(), 61)
            finally:
                H.history_path = original


if __name__ == "__main__":
    unittest.main()
