from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
_REG = Path(tempfile.gettempdir()) / "shadow-test-temp-registry.json"
os.environ.setdefault("SHADOW_TEMP_REGISTRY", str(_REG))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401 -- stubs modal dialogs so the suite can never hang

from PIL import Image

import temp_tracker
from preflight import HEADROOM_BYTES, content_fingerprint, disk_preflight, estimate_needed_bytes, find_duplicates


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _file(self, name: str, payload: bytes) -> Path:
        p = self.dir / name
        p.write_bytes(payload)
        return p

    def test_needed_bytes_scales_with_lossless_targets(self) -> None:
        a = self._file("a.bin", b"x" * 1000)
        self.assertEqual(estimate_needed_bytes([a], "WEBP"), 1000 + HEADROOM_BYTES)
        self.assertEqual(estimate_needed_bytes([a], "PNG"), 3000 + HEADROOM_BYTES)
        self.assertEqual(estimate_needed_bytes([a, self.dir / "missing"], "BMP"), 4000 + HEADROOM_BYTES)

    def test_disk_preflight_walks_to_existing_parent(self) -> None:
        a = self._file("a.bin", b"x" * 10)
        check = disk_preflight([a], self.dir / "not" / "yet" / "created", "WEBP")
        self.assertGreater(check.free_bytes, 0)
        self.assertTrue(check.ok)
        self.assertEqual(check.destination, self.dir / "not" / "yet" / "created")

    def test_fingerprint_and_duplicates(self) -> None:
        payload = os.urandom(200_000)
        a = self._file("a.jpg", payload)
        b = self._file("copy of a.jpg", payload)
        c = self._file("c.jpg", payload[:-1] + b"\x00")
        d = self._file("d.jpg", payload[:1000])
        self.assertEqual(content_fingerprint(a), content_fingerprint(b))
        self.assertNotEqual(content_fingerprint(a), content_fingerprint(c))
        dupes = find_duplicates([a, b, c, d, a])
        self.assertEqual(dupes, {b: a})


class TempTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_tracker.cleanup_stale()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        temp_tracker.cleanup_stale()
        self.tmp.cleanup()

    def test_register_unregister_and_cleanup(self) -> None:
        leftover = self.dir / "tmpabc.tmp.webp"
        leftover.write_bytes(b"partial")
        done = self.dir / "tmpdef.tmp.webp"
        done.write_bytes(b"partial")
        temp_tracker.register(leftover)
        temp_tracker.register(done)
        temp_tracker.unregister(done)
        removed = temp_tracker.cleanup_stale()
        self.assertEqual(removed, [leftover])
        self.assertFalse(leftover.exists())
        self.assertTrue(done.exists())
        self.assertEqual(temp_tracker.cleanup_stale(), [])

    def test_registry_only_deletes_temp_named_files(self) -> None:
        precious = self.dir / "photo.jpg"
        precious.write_bytes(b"keep me")
        temp_tracker.register(precious)
        self.assertEqual(temp_tracker.cleanup_stale(), [])
        self.assertTrue(precious.exists())

    def test_converter_registers_and_clears_its_temp_file(self) -> None:
        from converter import convert_image

        src = self.dir / "s.png"
        Image.new("RGB", (16, 16), "red").save(src)
        res = convert_image(src, self.dir / "out", quality=80, target_format="WEBP")
        self.assertEqual(res.status, "Completed")
        self.assertFalse(_REG.exists(), "registry should be empty after a clean conversion")
        self.assertEqual([p.name for p in (self.dir / "out").iterdir()], ["s.webp"])


class QueueDuplicateAppTests(unittest.TestCase):
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

    def test_duplicates_are_flagged_and_removable(self) -> None:
        app = self.app
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            img = Image.effect_noise((64, 64), 30).convert("RGB")
            a, b, c = d / "a.png", d / "a (copy).png", d / "c.png"
            img.save(a)
            b.write_bytes(a.read_bytes())
            Image.new("RGB", (64, 64), "blue").save(c)
            app._clear_all()
            app._ingest_image_paths([a, b, c])
            rows = {p.name: app.table.item(r)["values"][-1] for p, r in app.row_ids.items()}
            self.assertEqual(rows["a.png"], "Ready")
            self.assertEqual(rows["c.png"], "Ready")
            self.assertEqual(rows["a (copy).png"], "Duplicate of a.png")
            self.assertEqual(len(app._duplicate_paths()), 1)

            app._remove_duplicates()
            self.assertEqual(sorted(p.name for p in app.selected_files), ["a.png", "c.png"])
            self.assertEqual(app._duplicate_paths(), [])
            app._clear_all()

    def test_low_disk_prompt_can_abort_batch(self) -> None:
        app = self.app
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            p = d / "x.png"
            Image.new("RGB", (8, 8), "red").save(p)
            app._clear_all()
            app._ingest_image_paths([p])
            app.output_directory.set(str(d))
            app.save_in_source_folder.set(False)
            app.quality_text.set("80")
            asked: list[tuple[int, int]] = []

            def fake_check(paths, dest, fmt):
                from preflight import DiskCheck

                return DiskCheck(needed_bytes=10**15, free_bytes=1, destination=dest)

            import main as M

            original = M.disk_preflight
            M.disk_preflight = fake_check
            app._confirm_low_disk = lambda check: asked.append((check.needed_bytes, check.free_bytes)) or False
            try:
                app._start_conversion()
                self.assertFalse(app.conversion_running)
                self.assertEqual(asked, [(10**15, 1)])
                self.assertIn("free", app.status_text.get().lower())
            finally:
                M.disk_preflight = original
                app._clear_all()


if __name__ == "__main__":
    unittest.main()
