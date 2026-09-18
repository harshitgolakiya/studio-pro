from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from converter import convert_image
try:
    # Seller-only signing tool (see .gitignore); never distributed, so it's
    # absent in CI and on customer/reviewer checkouts. Tests that need it are
    # skipped rather than failing the whole module on import.
    from keygen_tool import generate_license_key
    _HAS_KEYGEN_TOOL = True
except ImportError:
    generate_license_key = None
    _HAS_KEYGEN_TOOL = False
from licensing import (
    FREE_BATCH_LIMIT,
    activate_license,
    deactivate_license,
    get_active_license_key,
    is_pro_activated,
    is_vip_activated,
    validate_license_key,
)
from media_engine import convert_media_file, get_best_hardware_encoder, get_ffmpeg_path, trim_video_lossless
from settings import load_settings, update_setting
from utils import build_destination_filename, slugify_filename
from watermark import apply_image_watermark, apply_text_watermark
from watch_folder import FolderWatcher


class CommercialFeaturesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_key = get_active_license_key()

    def tearDown(self) -> None:
        if self.original_key:
            activate_license(self.original_key)
        else:
            deactivate_license()

    @unittest.skipUnless(_HAS_KEYGEN_TOOL, "keygen_tool is seller-only and not present in this checkout")
    def test_license_key_cryptographic_verification(self) -> None:
        """Verify license key generator produces keys that pass cryptographic check."""
        test_key = generate_license_key("pro")
        self.assertTrue(test_key.startswith("PRO-"))
        self.assertTrue(validate_license_key(test_key))

        # Tampered or fake keys should fail
        self.assertFalse(validate_license_key("PRO-1234-5678-AAAA-BBBB"))
        self.assertFalse(validate_license_key("INVALID-KEY"))
        self.assertFalse(validate_license_key(""))

        # Flipping the tier prefix on a real signature must not validate
        forged = "VIP-" + test_key.split("-", 1)[1]
        self.assertFalse(validate_license_key(forged))

    @unittest.skipUnless(_HAS_KEYGEN_TOOL, "keygen_tool is seller-only and not present in this checkout")
    def test_vip_license_key_cryptographic_verification(self) -> None:
        """Verify VIP key generation and unlocking."""
        vip_key = generate_license_key("vip")
        self.assertTrue(vip_key.startswith("VIP-"))
        self.assertTrue(validate_license_key(vip_key))

        # Standard key should not be accepted as VIP
        self.assertFalse(vip_key.startswith("PRO-"))

        # Activation test
        ok, msg = activate_license(vip_key)
        self.assertTrue(ok)
        self.assertTrue(is_vip_activated())
        deactivate_license()
        self.assertFalse(is_vip_activated())

    def test_no_hardcoded_master_key_backdoor(self) -> None:
        """Historical master-key backdoor strings must never validate again."""
        self.assertFalse(validate_license_key("shadow1201##"))
        self.assertFalse(validate_license_key("SHADOW1201##"))
        self.assertFalse(validate_license_key("ghk1201##"))

    def test_watermark_application(self) -> None:
        """Verify text watermarking blends correctly onto image."""
        img = Image.new("RGB", (200, 200), (50, 50, 50))
        watermarked = apply_text_watermark(img, "© Commercial Proof", position="bottom-right")
        self.assertEqual(watermarked.size, (200, 200))
        # Ensure image was modified
        self.assertNotEqual(img.tobytes(), watermarked.tobytes())

    def test_image_logo_watermark_application(self) -> None:
        """Verify PNG logo image watermarking blends correctly onto image."""
        with tempfile.TemporaryDirectory() as td:
            logo_path = Path(td) / "logo.png"
            logo_img = Image.new("RGBA", (80, 40), (255, 0, 0, 200))
            logo_img.save(logo_path)

            base_img = Image.new("RGB", (400, 300), (20, 20, 20))
            stamped = apply_image_watermark(base_img, logo_path, position="bottom-right", opacity=0.8)
            self.assertEqual(stamped.size, (400, 300))
            self.assertNotEqual(base_img.tobytes(), stamped.tobytes())

    def test_slugify_filename(self) -> None:
        """Verify SEO clean filename formatting."""
        self.assertEqual(slugify_filename("My Product Image 2026!.png"), "my-product-image-2026.png")
        self.assertEqual(slugify_filename("Hello___World---Test.jpg"), "hello-world-test.jpg")

    def test_settings_persistence(self) -> None:
        """Verify settings can be updated and reloaded."""
        update_setting("test_key_sample", 42)
        cfg = load_settings()
        self.assertEqual(cfg.get("test_key_sample"), 42)

    def test_target_size_solver_in_converter(self) -> None:
        """Verify target size solver creates a file within target KB bound."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "large_photo.png"
            # Create high variance image
            img = Image.new("RGB", (500, 500), "red")
            img.save(src)

            res = convert_image(src, root / "out", target_kb=50)
            self.assertEqual(res.status, "Completed")
            self.assertTrue(res.output_path.exists())
            self.assertLessEqual(res.output_size, 65 * 1024)

    def test_ffmpeg_media_conversion_if_installed(self) -> None:
        """Test video / audio conversion using system FFmpeg."""
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            self.skipTest("FFmpeg not available on PATH")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Create a tiny 1-second synthetic video with ffmpeg
            test_vid = root / "test.mp4"
            import subprocess
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(test_vid)
                ],
                capture_output=True,
                check=True,
            )

            res = convert_media_file(test_vid, root / "out", target_format="webm")
            self.assertEqual(res.status, "Completed")
            self.assertEqual(res.output_path.suffix, ".webm")
            self.assertTrue(res.output_path.exists())

    def test_lossless_video_trimming(self) -> None:
        """Test sub-second lossless video trimming using FFmpeg."""
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            self.skipTest("FFmpeg not available on PATH")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            test_vid = root / "source.mp4"
            out_vid = root / "trimmed.mp4"
            import subprocess
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-f", "lavfi", "-i", "color=c=red:s=160x120:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(test_vid)
                ],
                capture_output=True,
                check=True,
            )

            result_path = trim_video_lossless(test_vid, out_vid, start_time="00:00:01", end_time="00:00:02")
            self.assertTrue(result_path.exists())
            self.assertGreater(result_path.stat().st_size, 0)

    def test_gpu_hardware_acceleration_detection(self) -> None:
        """Test auto-detection of hardware GPU encoder or clean CPU fallback."""
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            self.skipTest("FFmpeg not available on PATH")

        encoder, label = get_best_hardware_encoder()
        self.assertIsInstance(encoder, str)
        self.assertIsInstance(label, str)
        self.assertIn(encoder, ["h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox", "libx264"])

    def test_watch_folder_pipeline(self) -> None:
        """Test auto-watch folder daemon detecting and processing incoming files."""
        import time

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            watch_dir = root / "watch"
            watch_dir.mkdir()
            out_dir = root / "out"

            events: list[str] = []
            watcher = FolderWatcher(
                watch_dir=watch_dir,
                output_dir=out_dir,
                target_format="WEBP",
                quality=75,
                poll_interval=0.1,
                on_event=lambda lvl, msg: events.append(msg),
            )
            watcher.start()
            self.assertTrue(watcher.is_running)

            # Drop an image into watch_dir
            sample_img = watch_dir / "drop.png"
            img = Image.new("RGB", (64, 64), "magenta")
            img.save(sample_img)

            # Wait for watcher to pick up and process (up to 3 seconds)
            expected_out = out_dir / "drop.webp"
            start_wait = time.time()
            while time.time() - start_wait < 3.0:
                if expected_out.exists():
                    break
                time.sleep(0.1)

            watcher.stop()
            self.assertFalse(watcher.is_running)
            self.assertTrue(expected_out.exists())
            self.assertGreater(expected_out.stat().st_size, 0)

    def test_animated_gif_to_animated_webp(self) -> None:
        """Test converting multi-frame animated GIF to multi-frame animated WebP."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gif_path = root / "animated.gif"

            f1 = Image.new("RGBA", (120, 120), (255, 0, 0, 255))
            f2 = Image.new("RGBA", (120, 120), (0, 255, 0, 255))
            f3 = Image.new("RGBA", (120, 120), (0, 0, 255, 255))
            f1.save(
                gif_path,
                format="GIF",
                save_all=True,
                append_images=[f2, f3],
                duration=150,
                loop=0,
            )

            res = convert_image(gif_path, root / "out", quality=80, target_format="WEBP")
            self.assertEqual(res.status, "Completed")
            self.assertTrue(res.output_path.exists())
            self.assertEqual(res.output_path.suffix.lower(), ".webp")

            with Image.open(res.output_path) as out_img:
                self.assertTrue(getattr(out_img, "is_animated", False))
                self.assertEqual(out_img.n_frames, 3)

    def test_build_destination_filename(self) -> None:
        """Verify build_destination_filename correctly handles prefix, suffix, and slugify."""
        # Simple name with prefix and suffix
        name1 = build_destination_filename("banner", ".webp", prefix="hdr_", suffix="_opt")
        self.assertEqual(name1, "hdr_banner_opt.webp")

        # Dirty name with slugify
        name2 = build_destination_filename("My Super Hero #1 Photo!!", ".avif", slugify=True)
        self.assertEqual(name2, "my-super-hero-1-photo.avif")

        # Slugify with prefix and suffix
        name3 = build_destination_filename(
            "E-Commerce Product (Red)", ".jpg", slugify=True, prefix="prod_", suffix="_thumb"
        )
        self.assertEqual(name3, "prod_e-commerce-product-red_thumb.jpg")

    def test_smart_settings_detection(self) -> None:
        """Verify smart settings category classification and format mapping logic."""
        from converter import SUPPORTED_EXTENSIONS
        from media_engine import SUPPORTED_AUDIO_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS

        def detect_category(path: Path) -> str:
            ext = path.suffix.lower()
            if ext == ".gif":
                return "gif"
            elif ext in SUPPORTED_VIDEO_EXTENSIONS:
                return "video"
            elif ext in SUPPORTED_AUDIO_EXTENSIONS:
                return "audio"
            elif ext in SUPPORTED_EXTENSIONS:
                return "image"
            return "image"

        # Video test (like user's TH commercial 1.mp4)
        self.assertEqual(detect_category(Path("TH commercial 1.mp4")), "video")
        self.assertEqual(detect_category(Path("stream_clip.webm")), "video")
        self.assertEqual(detect_category(Path("recording.mov")), "video")

        # Audio test
        self.assertEqual(detect_category(Path("podcast_episode.mp3")), "audio")
        self.assertEqual(detect_category(Path("master_track.wav")), "audio")

        # Animated GIF test
        self.assertEqual(detect_category(Path("reaction.gif")), "gif")

        # Image test
        self.assertEqual(detect_category(Path("product.png")), "image")
        self.assertEqual(detect_category(Path("photo.jpg")), "image")
        self.assertEqual(detect_category(Path("banner.webp")), "image")

    def test_frozen_build_never_shells_out_to_pip_install_itself(self) -> None:
        """Regression test: a packaged .exe must never try to `pip install`
        itself.

        sys.executable inside a frozen PyInstaller build IS the packaged
        .exe. A prior bug listed "pyinstaller" as a required runtime package
        (it's a build-only tool, never bundled) and unconditionally ran
        `sys.executable -m pip install ...` on startup when anything was
        "missing" -- which, in a frozen build, just relaunched the whole GUI
        as a subprocess, which did the same thing again, spawning unbounded
        copies of the app (observed directly: dozens of processes within
        seconds of one launch).
        """
        from unittest.mock import patch

        import app_bootstrap

        with patch("app_bootstrap.sys.frozen", True, create=True), patch(
            "app_bootstrap.subprocess.run"
        ) as mock_run:
            self.assertEqual(app_bootstrap.get_missing_packages(), [])
            self.assertEqual(app_bootstrap.ensure_runtime_dependencies(), [])
            mock_run.assert_not_called()

        self.assertNotIn("pyinstaller", [p.lower() for p in app_bootstrap.REQUIRED_PACKAGES])

    def test_missing_runtime_tools_detection(self) -> None:
        """Verify missing runtime tools are detected for a friendly startup warning."""
        from unittest.mock import patch

        from app_bootstrap import get_missing_runtime_tools

        with patch("media_engine.get_ffmpeg_path", return_value=None), patch(
            "media_engine.get_ffprobe_path", return_value=None
        ):
            missing = get_missing_runtime_tools()
            self.assertIn("ffmpeg", missing)
            self.assertIn("ffprobe", missing)

    def test_bundled_ffmpeg_is_found_without_system_path(self) -> None:
        """Verify the vendored FFmpeg build is discovered even if not on system PATH."""
        from unittest.mock import patch

        from media_engine import get_ffmpeg_path, get_ffprobe_path

        with patch("media_engine.shutil.which", return_value=None):
            self.assertTrue(get_ffmpeg_path())
            self.assertTrue(get_ffprobe_path())

    def test_url_downloader_members_only_detection(self) -> None:
        """Verify URL downloader raises MembersOnlyError for members-only streams."""
        from url_downloader import MembersOnlyError, download_media_from_url
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(MembersOnlyError):
                # The user's provided YouTube members-only video URL
                download_media_from_url(
                    url="https://youtu.be/fzyL44FH2fI",
                    output_dir=Path(tmpdir),
                    cookies_source="none",
                )


if __name__ == "__main__":
    unittest.main()


