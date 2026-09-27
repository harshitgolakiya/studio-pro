from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import media_engine


class GPUCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_cache = media_engine._GPU_ENCODER_CACHE
        self.old_failures = set(media_engine._GPU_ENCODER_FAILURES)
        media_engine._GPU_ENCODER_CACHE = None
        media_engine._GPU_ENCODER_FAILURES.clear()

    def tearDown(self) -> None:
        media_engine._GPU_ENCODER_CACHE = self.old_cache
        media_engine._GPU_ENCODER_FAILURES.clear()
        media_engine._GPU_ENCODER_FAILURES.update(self.old_failures)

    @patch.dict("os.environ", {"SHADOW_DISABLE_GPU": "1"})
    def test_gpu_can_be_disabled_for_maximum_compatibility(self) -> None:
        encoder, label = media_engine.get_best_hardware_encoder()
        self.assertEqual(encoder, "libx264")
        self.assertIn("disabled", label.lower())

    @patch("media_engine.get_ffmpeg_path", return_value="ffmpeg")
    @patch("media_engine.subprocess.run")
    def test_probe_skips_unusable_gpu_and_uses_integrated_gpu(
        self, run: MagicMock, _ffmpeg: MagicMock
    ) -> None:
        advertised = MagicMock(returncode=0, stdout="h264_nvenc h264_qsv", stderr="")
        nvenc_failure = MagicMock(returncode=1, stdout="", stderr="old driver")
        qsv_success = MagicMock(returncode=0, stdout="", stderr="")
        run.side_effect = [advertised, nvenc_failure, qsv_success]

        encoder, label = media_engine.get_best_hardware_encoder()

        self.assertEqual(encoder, "h264_qsv")
        self.assertIn("Intel", label)
        probe_command = run.call_args_list[-1].args[0]
        self.assertTrue(
            any(value.startswith("color=c=black:s=1280x720") for value in probe_command)
        )
        self.assertIn("yuv420p", probe_command)

    def test_real_conversion_retries_on_cpu_after_gpu_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.mp4"
            source.write_bytes(b"source")
            output = root / "output"
            calls: list[list[str]] = []
            progress: list[str] = []

            def run_attempt(args, *_args, **_kwargs):
                calls.append(list(args))
                if len(calls) == 1:
                    return 1, "NVENC rejected this source", False, False
                Path(args[-1]).write_bytes(b"encoded")
                return 0, "", False, False

            with (
                patch("media_engine.get_ffmpeg_path", return_value="ffmpeg"),
                patch("media_engine.get_media_duration", return_value=1.0),
                patch(
                    "media_engine.get_best_hardware_encoder",
                    return_value=("h264_nvenc", "GPU: NVIDIA NVENC"),
                ),
                patch("media_engine._run_ffmpeg_process", side_effect=run_attempt),
            ):
                result = media_engine.convert_media_file(
                    source,
                    output,
                    target_format="mp4",
                    progress_callback=lambda _fraction, message: progress.append(message),
                )

            self.assertEqual(result.status, "Completed")
            self.assertEqual(len(calls), 2)
            self.assertIn("h264_nvenc", calls[0])
            self.assertIn("libx264", calls[1])
            self.assertIn("h264_nvenc", media_engine._GPU_ENCODER_FAILURES)
            self.assertTrue(any("retrying safely on CPU" in message for message in progress))

    def test_cancelled_gpu_job_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.mp4"
            source.write_bytes(b"source")
            with (
                patch("media_engine.get_ffmpeg_path", return_value="ffmpeg"),
                patch("media_engine.get_media_duration", return_value=1.0),
                patch(
                    "media_engine.get_best_hardware_encoder",
                    return_value=("h264_amf", "GPU: AMD AMF"),
                ),
                patch(
                    "media_engine._run_ffmpeg_process",
                    return_value=(-1, "", True, False),
                ) as runner,
            ):
                result = media_engine.convert_media_file(source, root / "out")

            self.assertEqual(result.status, "Cancelled")
            runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
