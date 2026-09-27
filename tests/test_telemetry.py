from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from telemetry import (
    BatchTelemetry,
    available_memory_bytes,
    estimate_batch_peak_bytes,
    estimate_image_peak_bytes,
    memory_risk_is_high,
    process_memory_bytes,
    recommend_workers,
)


class TelemetryTests(unittest.TestCase):
    def test_worker_recommendation_scales_with_input_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.bin"
            path.write_bytes(b"x" * (128 * 1024 * 1024))
            self.assertEqual(
                recommend_workers([path], cpu_count=8, available_memory=16 * 1024**3),
                3,
            )

    def test_worker_recommendation_protects_low_memory_and_video_systems(self) -> None:
        self.assertEqual(
            recommend_workers([Path("clip.mp4")], cpu_count=16, available_memory=32 * 1024**3),
            1,
        )
        self.assertEqual(
            recommend_workers([Path("photo.png")], cpu_count=16, available_memory=1 * 1024**3),
            1,
        )
        self.assertEqual(
            recommend_workers([Path("song.wav")], cpu_count=16, available_memory=32 * 1024**3),
            2,
        )

    def test_available_memory_is_non_negative(self) -> None:
        self.assertGreaterEqual(available_memory_bytes(), 0)

    def test_worker_recommendation_accounts_for_decoded_image_memory(self) -> None:
        with mock.patch("telemetry.estimate_batch_peak_bytes", return_value=2 * 1024**3):
            self.assertEqual(
                recommend_workers([Path("compressed.avif")], cpu_count=16, available_memory=8 * 1024**3),
                2,
            )
        with mock.patch("telemetry.estimate_batch_peak_bytes", return_value=5 * 1024**3):
            self.assertEqual(
                recommend_workers([Path("huge.png")], cpu_count=16, available_memory=8 * 1024**3),
                1,
            )

    def test_image_peak_estimate_uses_pixels_and_animation_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            still = Path(tmp) / "still.png"
            animated = Path(tmp) / "animated.gif"
            Image.new("RGB", (20, 10)).save(still)
            frames = [Image.new("RGB", (20, 10), (i * 40, 0, 0)) for i in range(3)]
            frames[0].save(animated, save_all=True, append_images=frames[1:], duration=20)

            self.assertEqual(estimate_image_peak_bytes(still), 20 * 10 * 4 * 6)
            self.assertEqual(estimate_image_peak_bytes(animated), 20 * 10 * 4 * 3 * 2)
            self.assertEqual(
                estimate_batch_peak_bytes([still, animated]),
                estimate_image_peak_bytes(animated),
            )

    def test_memory_risk_requires_large_absolute_and_relative_usage(self) -> None:
        gib = 1024**3
        self.assertFalse(memory_risk_is_high(0, 4 * gib))
        self.assertFalse(memory_risk_is_high(400 * 1024**2, 512 * 1024**2))
        self.assertFalse(memory_risk_is_high(2 * gib, 4 * gib))
        self.assertTrue(memory_risk_is_high(3 * gib, 4 * gib))

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
