from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401 -- stubs modal dialogs so the suite can never hang

from PIL import Image, ImageCms

from converter import convert_image
from loss_audit import (
    ImageFacts,
    audit_conversion,
    compare_facts,
    display_to_source,
    format_probe,
    gather_facts,
    pixel_probe,
)


def _facts(**over) -> ImageFacts:
    base = dict(width=100, height=100, mode="RGB", frames=1, has_transparency=False,
                has_exif=False, has_gps=False, icc_name="", has_icc=False, size_bytes=1000)
    base.update(over)
    return ImageFacts(**base)


def _titles(warnings) -> list[str]:
    return [w.title for w in warnings]


class CompareFactsTests(unittest.TestCase):
    def test_identical_facts_have_no_warnings(self) -> None:
        self.assertEqual(compare_facts(_facts(), _facts()), [])

    def test_alpha_animation_depth_and_palette(self) -> None:
        src = _facts(mode="RGBA", has_transparency=True, frames=12)
        out = _facts(mode="RGB")
        titles = _titles(compare_facts(src, out))
        self.assertIn("Transparency lost", titles)
        self.assertIn("Animation lost", titles)
        self.assertIn("Bit depth reduced", _titles(compare_facts(_facts(mode="I;16"), _facts(mode="L"))))
        self.assertIn("Reduced to a 256-colour palette", _titles(compare_facts(_facts(mode="RGB"), _facts(mode="P"))))
        self.assertNotIn("Reduced to a 256-colour palette", _titles(compare_facts(_facts(mode="P"), _facts(mode="P"))))

    def test_wide_gamut_profile_loss_is_high_severity(self) -> None:
        p3 = compare_facts(_facts(has_icc=True, icc_name="Display P3"), _facts())
        self.assertEqual((p3[0].severity, p3[0].title), ("high", "Wide-gamut colour profile removed"))
        srgb = compare_facts(_facts(has_icc=True, icc_name="sRGB IEC61966-2.1"), _facts())
        self.assertEqual((srgb[0].severity, srgb[0].title), ("info", "Colour profile removed"))
        kept = compare_facts(_facts(has_icc=True, icc_name="Display P3"), _facts(has_icc=True, icc_name="Display P3"))
        self.assertEqual(kept, [])

    def test_metadata_gps_size_and_ordering(self) -> None:
        src = _facts(has_exif=True, has_gps=True, size_bytes=1000)
        out = _facts(has_exif=True, has_gps=True, size_bytes=1500, width=50, height=50)
        warnings = compare_facts(src, out)
        titles = _titles(warnings)
        self.assertIn("GPS location retained", titles)
        self.assertIn("Output is larger than the source", titles)
        self.assertIn("Resolution changed", titles)
        severities = [w.severity for w in warnings]
        self.assertEqual(severities, sorted(severities, key=["high", "medium", "info"].index))
        self.assertIn("EXIF metadata removed", _titles(compare_facts(_facts(has_exif=True), _facts())))


class RealFileAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_transparent_png_to_jpeg_reports_alpha_loss(self) -> None:
        src = self.dir / "logo.png"
        Image.new("RGBA", (64, 64), (255, 0, 0, 90)).save(src)
        self.assertTrue(gather_facts(src).has_transparency)
        res = convert_image(src, self.dir / "out", target_format="JPEG")
        self.assertIn("Transparency lost", _titles(audit_conversion(src, res.output_path)))

        keep = convert_image(src, self.dir / "out2", target_format="WEBP")
        self.assertNotIn("Transparency lost", _titles(audit_conversion(src, keep.output_path)))

    def test_opaque_rgba_is_not_flagged(self) -> None:
        src = self.dir / "opaque.png"
        Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(src)
        self.assertFalse(gather_facts(src).has_transparency)

    def test_animated_gif_to_png_reports_animation_loss(self) -> None:
        src = self.dir / "anim.gif"
        frames = [Image.new("RGB", (32, 32), c) for c in ("red", "green", "blue")]
        frames[0].save(src, save_all=True, append_images=frames[1:], duration=80, loop=0)
        self.assertEqual(gather_facts(src).frames, 3)
        res = convert_image(src, self.dir / "out", target_format="PNG")
        self.assertIn("Animation lost", _titles(audit_conversion(src, res.output_path)))

    def test_icc_profile_detection_and_preservation(self) -> None:
        src = self.dir / "tagged.jpg"
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        Image.new("RGB", (48, 48), "orange").save(src, icc_profile=icc)
        facts = gather_facts(src)
        self.assertTrue(facts.has_icc)
        self.assertFalse(facts.wide_gamut)

        dropped = convert_image(src, self.dir / "a", target_format="WEBP")
        self.assertIn("Colour profile removed", _titles(audit_conversion(src, dropped.output_path)))
        kept = convert_image(src, self.dir / "b", target_format="WEBP", preserve_metadata=True)
        self.assertNotIn("Colour profile removed", _titles(audit_conversion(src, kept.output_path)))

    def test_missing_output_is_silent(self) -> None:
        src = self.dir / "x.png"
        Image.new("RGB", (8, 8)).save(src)
        self.assertEqual(audit_conversion(src, None), [])
        self.assertEqual(audit_conversion(src, self.dir / "nope.webp"), [])


class PixelProbeTests(unittest.TestCase):
    def test_display_mapping(self) -> None:
        self.assertEqual(display_to_source(0, 0, (100, 50), (1000, 500)), (0, 0))
        self.assertEqual(display_to_source(99, 49, (100, 50), (1000, 500)), (990, 490))
        self.assertIsNone(display_to_source(100, 10, (100, 50), (1000, 500)))
        self.assertIsNone(display_to_source(-1, 10, (100, 50), (1000, 500)))

    def test_probe_values_and_delta(self) -> None:
        a = Image.new("RGBA", (10, 10), (100, 150, 200, 255))
        b = Image.new("RGBA", (10, 10), (110, 145, 200, 255))
        probe = pixel_probe(a, b, 3, 4)
        self.assertEqual(probe["original"], (100, 150, 200, 255))
        self.assertEqual(probe["converted"], (110, 145, 200, 255))
        self.assertEqual(probe["delta"], (10, -5, 0, 0))
        self.assertEqual(probe["max_delta"], 10)
        self.assertIsNone(pixel_probe(a, b, 10, 0))
        text = format_probe(probe)
        self.assertIn("(3, 4)", text)
        self.assertIn("#6496C8", text)
        self.assertIn("+10,-5,+0,+0", text)
        self.assertIn("Move the pointer", format_probe(None))

    def test_probe_maps_into_resized_output(self) -> None:
        a = Image.new("RGB", (100, 100), "white")
        b = Image.new("RGB", (50, 50), "black")
        probe = pixel_probe(a, b, 99, 99)
        self.assertEqual(probe["converted"][:3], (0, 0, 0))


class PreviewDialogIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import customtkinter as ctk

        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_dialog_shows_warnings_and_probe(self) -> None:
        from preview_modal import ImagePreviewDialog

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            src = d / "logo.png"
            Image.new("RGBA", (120, 80), (255, 0, 0, 90)).save(src)
            res = convert_image(src, d / "out", target_format="JPEG")
            dialog = ImagePreviewDialog(self.root, src, res)
            dialog.update()
            self.assertIn("Transparency lost", [w.title for w in dialog.loss_warnings])

            class _Evt:
                x, y = 5, 5

            dialog._on_probe_motion(_Evt())
            self.assertIn("original RGBA 255,0,0,90", dialog.probe_lbl.cget("text"))
            self.assertIn("output", dialog.probe_lbl.cget("text"))
            dialog.destroy()


if __name__ == "__main__":
    unittest.main()
