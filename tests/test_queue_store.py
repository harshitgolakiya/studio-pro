from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from converter import ConversionResult
from queue_store import (
    QUEUE_STATE_VERSION,
    QueueItem,
    QueueState,
    build_state,
    clear_queue_state,
    load_queue_state,
    save_queue_state,
    synthesize_result,
)


def _png(path: Path, size: int = 40) -> Path:
    Image.new("RGB", (size, size), "blue").save(path)
    # The app stores resolved paths (which expands 8.3 short names on Windows),
    # so compare against the same form.
    return path.resolve()


class QueueStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state_file = self.dir / "queue_state.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_round_trip_keeps_order_and_completed_output(self) -> None:
        a = _png(self.dir / "a.png")
        b = _png(self.dir / "b.png")
        out = _png(self.dir / "a.webp", 10)
        results = {a: ConversionResult(a, out, 100, 50, "50.0%", "Completed")}
        save_queue_state(build_state([b, a], results, str(self.dir)), self.state_file)

        loaded = load_queue_state(self.state_file)
        self.assertIsNotNone(loaded)
        self.assertEqual([i.path for i in loaded.items], [b, a])
        self.assertEqual(loaded.items[0].status, "Ready")
        self.assertEqual(loaded.items[1].status, "Completed")
        self.assertEqual(loaded.items[1].output_path, out)
        self.assertEqual(loaded.output_directory, str(self.dir))
        self.assertEqual(loaded.dropped, 0)

    def test_missing_sources_are_pruned_and_missing_outputs_reset(self) -> None:
        a = _png(self.dir / "a.png")
        ghost = self.dir / "gone.png"
        results = {a: ConversionResult(a, self.dir / "never.webp", 1, 1, "0%", "Completed")}
        save_queue_state(build_state([a, ghost], results, ""), self.state_file)

        loaded = load_queue_state(self.state_file)
        self.assertEqual([i.path for i in loaded.items], [a])
        self.assertEqual(loaded.items[0].status, "Ready")
        self.assertIsNone(loaded.items[0].output_path)
        self.assertEqual(loaded.dropped, 1)

    def test_failed_rows_come_back_as_ready(self) -> None:
        a = _png(self.dir / "a.png")
        results = {a: ConversionResult(a, None, 1, None, "-", "Failed", "boom")}
        save_queue_state(build_state([a], results, ""), self.state_file)
        self.assertEqual(load_queue_state(self.state_file).items[0].status, "Ready")

    def test_empty_corrupt_or_foreign_files_yield_none(self) -> None:
        self.assertIsNone(load_queue_state(self.state_file))
        self.state_file.write_text("{oops", encoding="utf-8")
        self.assertIsNone(load_queue_state(self.state_file))
        self.state_file.write_text(json.dumps({"version": QUEUE_STATE_VERSION + 1, "items": []}), encoding="utf-8")
        self.assertIsNone(load_queue_state(self.state_file))
        save_queue_state(QueueState(items=[]), self.state_file)
        self.assertIsNone(load_queue_state(self.state_file))

    def test_clear_is_idempotent(self) -> None:
        save_queue_state(QueueState(), self.state_file)
        clear_queue_state(self.state_file)
        clear_queue_state(self.state_file)
        self.assertFalse(self.state_file.exists())

    def test_synthesize_result_from_disk(self) -> None:
        a = _png(self.dir / "a.png", 64)
        out = _png(self.dir / "a.webp", 8)
        result = synthesize_result(QueueItem(a, "Completed", out))
        self.assertEqual(result.status, "Completed")
        self.assertEqual(result.original_size, a.stat().st_size)
        self.assertEqual(result.output_size, out.stat().st_size)
        self.assertIsNone(synthesize_result(QueueItem(a, "Ready")))


class QueueRecoveryAppTests(unittest.TestCase):
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
        self.app._clear_all()
        self.app.queue_state_file = self.dir / "queue_state.json"
        self.app._queue_persistence_enabled = True

    def tearDown(self) -> None:
        self.app._queue_persistence_enabled = False
        self.app._clear_all()
        self.tmp.cleanup()

    def test_save_clear_restore_round_trip(self) -> None:
        app = self.app
        a = _png(self.dir / "a.png")
        b = _png(self.dir / "b.png")
        out = _png(self.dir / "a.webp", 8)
        app._ingest_image_paths([a, b])
        app._display_result(ConversionResult(a, out, a.stat().st_size, out.stat().st_size, "80.0%", "Completed"))
        app._save_queue_now()
        self.assertTrue(app.queue_state_file.is_file())

        app._clear_all()
        self.assertEqual(app.selected_files, [])

        app._confirm_queue_restore = lambda count, dropped: True
        app._offer_queue_restore()
        app.update()

        self.assertEqual(app.selected_files, [a, b])
        row_a = app.table.item(app.row_ids[a])["values"]
        self.assertEqual(row_a[-1], "Completed")
        self.assertIn(a, app.row_results)
        row_b = app.table.item(app.row_ids[b])["values"]
        self.assertEqual(row_b[-1], "Ready")

    def test_declining_restore_discards_saved_queue(self) -> None:
        app = self.app
        a = _png(self.dir / "a.png")
        app._ingest_image_paths([a])
        app._save_queue_now()
        app._clear_all()

        app._confirm_queue_restore = lambda count, dropped: False
        app._offer_queue_restore()
        self.assertEqual(app.selected_files, [])
        self.assertFalse(app.queue_state_file.exists())

    def test_clearing_queue_removes_state_file(self) -> None:
        app = self.app
        a = _png(self.dir / "a.png")
        app._ingest_image_paths([a])
        app._save_queue_now()
        app._clear_all()
        app._save_queue_now()
        self.assertFalse(app.queue_state_file.exists())


if __name__ == "__main__":
    unittest.main()
