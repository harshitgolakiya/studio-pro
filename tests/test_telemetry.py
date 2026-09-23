from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from telemetry import BatchTelemetry, process_memory_bytes, recommend_workers


class TelemetryTests(unittest.TestCase):
    def test_worker_recommendation_scales_with_input_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.bin"
            path.write_bytes(b"x" * (128 * 1024 * 1024))
            self.assertEqual(recommend_workers([path], cpu_count=8), 3)

    def test_snapshot_reports_progress_and_eta(self) -> None:
        telemetry = BatchTelemetry(total=10, workers=2, gpu="GPU: test")
        time.sleep(0.01)
        snapshot = telemetry.snapshot(2)
        self.assertEqual(snapshot.progress, 0.2)
        self.assertGreater(snapshot.throughput, 0)
        self.assertIsNotNone(snapshot.eta)
        self.assertIn("2/10", snapshot.status_text())
        self.assertIn("GPU: test", snapshot.status_text())

    def test_process_memory_is_non_negative(self) -> None:
        self.assertGreaterEqual(process_memory_bytes(), 0)


if __name__ == "__main__":
    unittest.main()