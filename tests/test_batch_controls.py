from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
# Real conversions run here; keep their history out of the user's real log.
os.environ.setdefault("SHADOW_HISTORY_FILE", str(Path(tempfile.gettempdir()) / "shadow-test-history.jsonl"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401 -- stubs modal dialogs so the suite can never hang

from PIL import Image


class BatchControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import main as M

        # These tests exercise queue mechanics, not licensing. Without this a
        # machine with no licence (every CI runner) caps batches at the free
        # limit and prompts to upgrade, so results would depend on the host.
        cls._main = M
        cls._orig_is_pro = M.is_pro_activated
        M.is_pro_activated = lambda: True
        cls.app = M.WebPCompressorApp()
        cls.app.update()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._main.is_pro_activated = cls._orig_is_pro
        try:
            cls.app.destroy()
        except Exception:
            pass

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "out"
        self.out.mkdir()
        app = self.app
        app._clear_all()
        app.output_directory.set(str(self.out))
        app.save_in_source_folder.set(False)
        app.target_format.set("WEBP")
        app._format_changed("WEBP")
        app.quality.set(80)
        app.quality_text.set("80")
        app.enable_target_size.set(False)
        app.enable_resize.set(False)
        app.enable_watermark.set(False)
        app.play_sound.set(False)

    def tearDown(self) -> None:
        self.app.cancel_event.set()
        self._pump_until(lambda: not self.app.conversion_running, 10)
        self.app._clear_all()
        self.tmp.cleanup()

    def _pump_until(self, cond, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.update()
            if cond():
                return True
            time.sleep(0.02)
        return cond()

    def _pngs(self, n: int, size: int = 320) -> list[Path]:
        paths = []
        for i in range(n):
            p = self.dir / f"img{i}.png"
            Image.effect_noise((size, size), 40).convert("RGB").save(p)
            paths.append(p.resolve())
        return paths

    def test_pause_holds_queue_then_resume_completes(self) -> None:
        app = self.app
        paths = self._pngs(5)
        app._ingest_image_paths(paths)
        app.pause_event.set()  # pause before anything starts
        app._start_conversion()
        self.assertTrue(app.conversion_running)
        self.assertEqual(app.pause_button.cget("text"), "Pause")  # start resets the toggle
        # _start_conversion clears the pause; re-pause immediately so workers block.
        app._toggle_pause()
        self.assertEqual(app.pause_button.cget("text"), "Resume")
        self.assertTrue(app.pause_event.is_set())

        self._pump_until(lambda: False, 0.6)
        started = len(app.row_results)
        self.assertLess(started, 5, "paused queue must not finish everything")

        app._toggle_pause()
        self.assertFalse(app.pause_event.is_set())
        self.assertTrue(self._pump_until(lambda: not app.conversion_running, 60))
        self.assertEqual(sum(r.status == "Completed" for r in app.row_results.values()), 5)
        self.assertEqual(app.retry_button.winfo_manager(), "")

    def test_retry_failed_reruns_only_failed_rows(self) -> None:
        app = self.app
        good = self._pngs(1, 64)[0]
        bad = (self.dir / "broken.png").resolve()
        bad.write_bytes(b"\x89PNG not really")
        app._ingest_image_paths([good, bad])
        with patch.object(self._main, "get_best_hardware_encoder") as gpu_probe:
            app._start_conversion()
            self.assertTrue(self._pump_until(lambda: not app.conversion_running, 30))
        gpu_probe.assert_not_called()
        self.assertEqual(app.row_results[good].status, "Completed")
        self.assertEqual(app.row_results[bad].status, "Failed")
        self.assertEqual(app._failed_paths(), [bad])
        # winfo_manager reflects grid() immediately; winfo_ismapped waits for Tk's geometry pass.
        self.assertEqual(app.retry_button.winfo_manager(), "grid")

        good_out_mtime = app.row_results[good].output_path.stat().st_mtime
        Image.new("RGB", (32, 32), "green").save(bad)  # user fixes the file
        app._retry_failed()
        self.assertTrue(app.conversion_running)
        self.assertTrue(self._pump_until(lambda: not app.conversion_running, 30))
        self.assertEqual(app.row_results[bad].status, "Completed")
        self.assertEqual(app.row_results[good].output_path.stat().st_mtime, good_out_mtime)
        self.assertEqual(app._failed_paths(), [])
        self.assertEqual(app.retry_button.winfo_manager(), "")

    def test_cancel_while_paused_unblocks_workers(self) -> None:
        app = self.app
        app._ingest_image_paths(self._pngs(6))
        app._start_conversion()
        app._toggle_pause()
        self._pump_until(lambda: False, 0.3)
        app._cancel_conversion()
        self.assertTrue(self._pump_until(lambda: not app.conversion_running, 30))
        statuses = {r.status for r in app.row_results.values()}
        self.assertTrue(statuses <= {"Completed", "Cancelled"})
        self.assertIn("Cancelled", statuses)

    def test_close_during_conversion_requires_confirmation_and_signals_cancel(self) -> None:
        app = self.app
        app.conversion_running = True
        app.cancel_event.clear()
        with (
            patch("main.messagebox.askyesno", return_value=False),
            patch.object(app, "destroy") as destroy,
        ):
            app._on_app_close()
            destroy.assert_not_called()
            self.assertFalse(app.cancel_event.is_set())

        with (
            patch("main.messagebox.askyesno", return_value=True),
            patch.object(app, "destroy") as destroy,
        ):
            app._on_app_close()
            destroy.assert_called_once()
            self.assertTrue(app.cancel_event.is_set())
        app.conversion_running = False
        app.cancel_event.clear()

    def test_high_memory_confirmation_is_owned_by_main_window(self) -> None:
        with patch("main.messagebox.askyesno", return_value=False) as ask:
            self.assertFalse(self.app._confirm_high_memory(3 * 1024**3, 4 * 1024**3))
        self.assertIs(ask.call_args.kwargs["parent"], self.app)
        self.assertIn("3.0 GB", ask.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
