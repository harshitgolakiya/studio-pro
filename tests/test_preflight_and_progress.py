import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_engine import convert_media_file, get_ffmpeg_path


class RealTimeProgressAndPreflightTests(unittest.TestCase):
    def test_convert_media_file_progress_callback(self) -> None:
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            self.skipTest("FFmpeg not available")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "clip.mp4"
            import subprocess
            subprocess.run([
                ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)
            ], check=True, capture_output=True)

            progress_calls = []
            def on_progress(pct: float, msg: str) -> None:
                progress_calls.append((pct, msg))

            res = convert_media_file(
                src,
                root / "out",
                target_format="webm",
                progress_callback=on_progress,
            )
            self.assertEqual(res.status, "Completed")
            self.assertTrue(res.output_path and res.output_path.exists())
            self.assertGreater(len(progress_calls), 0)
            self.assertIn("Encoding", progress_calls[0][1])

    def test_convert_media_file_cancellation(self) -> None:
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            self.skipTest("FFmpeg not available")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "clip2.mp4"
            import subprocess
            subprocess.run([
                ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=green:s=160x120:d=5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)
            ], check=True, capture_output=True)

            res = convert_media_file(
                src,
                root / "out",
                target_format="webm",
                cancel_check=lambda: True,
            )
            self.assertEqual(res.status, "Cancelled")


if __name__ == "__main__":
    unittest.main()
