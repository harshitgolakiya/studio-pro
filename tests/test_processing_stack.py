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

from PIL import Image

from converter import (
    DEFAULT_OPERATION_ORDER,
    apply_image_transformations,
    compute_resize_dims,
    convert_image,
    normalize_operation_order,
)
from recipes import coerce_settings


class OrderNormalizationTests(unittest.TestCase):
    def test_default_and_garbage(self) -> None:
        self.assertEqual(normalize_operation_order(None), DEFAULT_OPERATION_ORDER)
        self.assertEqual(normalize_operation_order(""), DEFAULT_OPERATION_ORDER)
        self.assertEqual(normalize_operation_order("nonsense,,"), DEFAULT_OPERATION_ORDER)

    def test_partial_order_is_completed_and_deduplicated(self) -> None:
        order = normalize_operation_order("resize, CROP ,resize,bogus")
        self.assertEqual(order[:2], ("resize", "crop"))
        self.assertEqual(sorted(order), sorted(DEFAULT_OPERATION_ORDER))
        self.assertEqual(len(order), len(DEFAULT_OPERATION_ORDER))

    def test_recipe_coercion_normalizes_order(self) -> None:
        s = coerce_settings({"operation_order": "watermark,resize,unknown"})
        self.assertTrue(s["operation_order"].startswith("watermark,resize,"))
        self.assertEqual(len(s["operation_order"].split(",")), len(DEFAULT_OPERATION_ORDER))


class ResizeDimsTests(unittest.TestCase):
    def test_compute_resize_dims(self) -> None:
        self.assertEqual(compute_resize_dims((1600, 900), None, 800, 800), (800, 450))
        self.assertEqual(compute_resize_dims((900, 1600), None, 800, 800), (450, 800))
        self.assertEqual(compute_resize_dims((1600, 900), 50, None, None), (800, 450))
        self.assertIsNone(compute_resize_dims((400, 300), None, 800, 800))
        self.assertIsNone(compute_resize_dims((400, 300), None, None, None))


class DistortionRegressionTests(unittest.TestCase):
    """Resize used to be computed from the untouched source and applied after
    crop/rotate, stretching the result back to the source's proportions."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "wide.png"
        Image.new("RGB", (1600, 900), "red").save(self.src)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _size(self, name: str, **opts) -> tuple[int, int]:
        res = convert_image(self.src, self.dir / name, target_format="PNG", **opts)
        self.assertEqual(res.status, "Completed", res.error)
        with Image.open(res.output_path) as im:
            return im.size

    def test_square_crop_stays_square_when_resized(self) -> None:
        self.assertEqual(self._size("a", aspect_ratio="1:1", max_width=500, max_height=500), (500, 500))
        self.assertEqual(self._size("b", aspect_ratio="1:1", max_width=1000, max_height=1000), (900, 900))
        self.assertEqual(self._size("c", aspect_ratio="1:1", scale_percent=50), (450, 450))

    def test_rotation_keeps_portrait_proportions_when_resized(self) -> None:
        self.assertEqual(self._size("d", rotate_angle=90, max_width=800, max_height=800), (450, 800))

    def test_plain_resize_unchanged(self) -> None:
        self.assertEqual(self._size("e", max_width=800, max_height=800), (800, 450))


class OrderSemanticsTests(unittest.TestCase):
    def test_default_order_matches_explicit_default(self) -> None:
        img = Image.radial_gradient("L").resize((300, 200)).convert("RGB")
        kwargs = dict(rotate_angle=90, flip_h=True, aspect_ratio="1:1", corner_radius=20, grayscale=True, resize_spec=(None, 100, 100))
        a = apply_image_transformations(img, **kwargs)
        b = apply_image_transformations(img, order=DEFAULT_OPERATION_ORDER, **kwargs)
        self.assertEqual(a.size, b.size)
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_rounded_before_vs_after_resize_differs(self) -> None:
        img = Image.new("RGB", (400, 400), "white")
        kwargs = dict(corner_radius=40, resize_spec=(None, 100, 100))

        def transparent_pixels(order: str) -> int:
            out = apply_image_transformations(img, order=order, **kwargs)
            self.assertEqual(out.size, (100, 100))
            return sum(1 for v in out.getchannel("A").tobytes() if v == 0)

        rounded_first = transparent_pixels("rounded,resize")   # radius shrinks to ~10 px
        resized_first = transparent_pixels("resize,rounded")   # full 40 px radius on 100 px
        self.assertGreater(resized_first, rounded_first * 3)

    def test_crop_before_vs_after_rotate(self) -> None:
        img = Image.new("RGB", (400, 200), "blue")
        a = apply_image_transformations(img, rotate_angle=90, aspect_ratio="2:1", order="rotate,crop")
        b = apply_image_transformations(img, rotate_angle=90, aspect_ratio="2:1", order="crop,rotate")
        self.assertEqual(a.size, (200, 100))   # rotated to 200x400, then cropped to 2:1
        self.assertEqual(b.size, (200, 400))   # already 2:1, then rotated

    def test_watermark_step_position_in_stack(self) -> None:
        img = Image.new("RGB", (200, 200), "white")
        calls: list[tuple[int, int]] = []

        def mark(im: Image.Image) -> Image.Image:
            calls.append(im.size)
            return im

        apply_image_transformations(img, resize_spec=(50, None, None), watermark_fn=mark, order="watermark,resize")
        apply_image_transformations(img, resize_spec=(50, None, None), watermark_fn=mark, order="resize,watermark")
        self.assertEqual(calls, [(200, 200), (100, 100)])


class StackPanelAppTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.app._reset_operation_order()
        self.app.grayscale.set(False)

    def test_move_reset_and_active_state(self) -> None:
        app = self.app
        self.assertEqual(app._current_operation_order(), DEFAULT_OPERATION_ORDER)
        self.assertEqual(len(app.stack_frame.winfo_children()), len(DEFAULT_OPERATION_ORDER))

        app._move_operation("resize", -1)
        order = app._current_operation_order()
        self.assertEqual(order.index("resize"), DEFAULT_OPERATION_ORDER.index("resize") - 1)
        app._move_operation("rotate", -1)  # already first: no-op
        self.assertEqual(app._current_operation_order()[0], "rotate")

        self.assertFalse(app._operation_active("grayscale"))
        app.grayscale.set(True)
        self.assertTrue(app._operation_active("grayscale"))

        app._reset_operation_order()
        self.assertEqual(app._current_operation_order(), DEFAULT_OPERATION_ORDER)

    def test_order_round_trips_through_recipes(self) -> None:
        app = self.app
        app._move_operation("watermark", -1)
        snapshot = app._collect_recipe_settings()
        moved = snapshot["operation_order"]
        app._reset_operation_order()
        app._apply_recipe_settings(snapshot)
        self.assertEqual(app.operation_order.get(), moved)


if __name__ == "__main__":
    unittest.main()
