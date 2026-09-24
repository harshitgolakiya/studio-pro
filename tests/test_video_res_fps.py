from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401

from media_engine import convert_media_file, get_ffmpeg_path


class TestVideoResAndFPS(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffmpeg = get_ffmpeg_path()
        if not cls.ffmpeg:
            raise unittest.SkipTest("FFmpeg not installed")

    def _get_video_info(self, file_path: Path) -> dict:
        ffprobe = Path(self.ffmpeg).parent / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if not ffprobe.exists():
            return {}
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        cmd = [
            str(ffprobe),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate",
            "-of", "json",
            str(file_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=flags)
        data = json.loads(r.stdout)
        streams = data.get("streams", [])
        return streams[0] if streams else {}

    def test_resolution_and_fps_downscaling(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_mp4 = root / "input_1080p.mp4"
            out_dir = root / "output"

            # Create 1-second 1280x720 30fps video
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            cmd = [
                self.ffmpeg,
                "-y",
                "-f", "lavfi", "-i", "testsrc=duration=1:size=1280x720:rate=30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(src_mp4),
            ]
            subprocess.run(cmd, capture_output=True, check=True, creationflags=flags)
            self.assertTrue(src_mp4.exists())

            # Convert to MP4 with 360p resolution and 15 fps
            res = convert_media_file(
                src_mp4,
                out_dir,
                target_format="mp4",
                video_resolution="360p",
                video_fps="15 fps",
            )
            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertTrue(res.output_path.exists())

            info = self._get_video_info(res.output_path)
            if info:
                # 1280x720 scaled to 360p (max width 640) -> 640x360
                self.assertEqual(info.get("width"), 640)
                self.assertEqual(info.get("height"), 360)
                r_fps = info.get("r_frame_rate", "15/1")
                num, den = map(int, r_fps.split("/"))
                self.assertAlmostEqual(num / den, 15.0, places=1)

    def test_lossless_remux_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_mp4 = root / "input.mp4"
            out_dir = root / "output"

            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            cmd = [
                self.ffmpeg,
                "-y",
                "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(src_mp4),
            ]
            subprocess.run(cmd, capture_output=True, check=True, creationflags=flags)

            res = convert_media_file(
                src_mp4,
                out_dir,
                target_format="mp4",
                video_quality="copy",
            )
            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertTrue(res.output_path.exists())

    def test_scale_percent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_mp4 = root / "input.mp4"
            out_dir = root / "output"

            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            cmd = [
                self.ffmpeg,
                "-y",
                "-f", "lavfi", "-i", "testsrc=duration=1:size=640x480:rate=24",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(src_mp4),
            ]
            subprocess.run(cmd, capture_output=True, check=True, creationflags=flags)

            res = convert_media_file(
                src_mp4,
                out_dir,
                target_format="mp4",
                scale_percent=50.0,
            )
            self.assertEqual(res.status, "Completed")
            self.assertIsNotNone(res.output_path)
            self.assertTrue(res.output_path.exists())

            info = self._get_video_info(res.output_path)
            if info:
                self.assertEqual(info.get("width"), 320)
                self.assertEqual(info.get("height"), 240)


if __name__ == "__main__":
    unittest.main()
