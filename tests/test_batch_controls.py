from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image


class BatchControlTests(unittest.TestCase):
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
        self.assertFalse(app.retry_button.winfo_ismapped())

    def test_retry_failed_reruns_only_failed_rows(self) -> None:
        app = self.app
        good = self._pngs(1, 64)[0]
        bad = (self.dir / "broken.png").resolve()
        bad.write_bytes(b"\x89PNG not really")
        app._ingest_image_paths([good, bad])
        app._start_conversion()
        self.assertTrue(self._pump_until(lambda: not app.conversion_running, 30))
        self.assertEqual(app.row_results[good].status, "Completed")
        self.assertEqual(app.row_results[bad].status, "Failed")
        self.assertEqual(app._failed_paths(), [bad])
        self.assertTrue(app.retry_button.winfo_ismapped())

        good_out_mtime = app.row_results[good].output_path.stat().st_mtime
        Image.new("RGB", (32, 32), "green").save(bad)  # user fixes the file
        app._retry_failed()
        self.assertTrue(app.conversion_running)
        self.assertTrue(self._pump_until(lambda: not app.conversion_running, 30))
        self.assertEqual(app.row_results[bad].status, "Completed")
        self.assertEqual(app.row_results[good].output_path.stat().st_mtime, good_out_mtime)
        self.assertEqual(app._failed_paths(), [])
        self.assertFalse(app.retry_button.winfo_ismapped())

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


if __name__ == "__main__":
    unittest.main()
