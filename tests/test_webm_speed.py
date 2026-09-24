from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401

from media_engine import convert_media_file, get_ffmpeg_path


class TestWebMSpeedAndQuality(unittest.TestCase):
    def test_webm_conversion_speed_flags(self) -> None:
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            self.skipTest("FFmpeg not installed")

        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_mp4 = root / "input.mp4"
            out_dir = root / "output"

            # Create a 2-second test video
            cmd = [
                ffmpeg,
                "-y",
                "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
                "-f", "lavfi", "-i", "sine=duration=2:frequency=440",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                str(src_mp4),
            ]
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            subprocess.run(cmd, capture_output=True, check=True, creationflags=flags)
            self.assertTrue(src_mp4.exists())

            # Convert to WebM using the optimized engine
            res = convert_media_file(
                src_mp4,
                out_dir,
                target_format="webm",
                video_quality="medium",
            )

            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertTrue(res.output_path.exists())
            self.assertEqual(res.output_path.suffix.lower(), ".webm")
            self.assertGreater(res.output_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
