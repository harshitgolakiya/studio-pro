from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import drag_drop
from main import WebPCompressorApp


class DragDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = WebPCompressorApp()
        cls.app.update()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.app.destroy()
        except Exception:
            pass

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        # Create sample files
        self.img1 = self.tmp_path / "test1.png"
        Image.new("RGB", (50, 50), color="blue").save(self.img1)

        self.img2 = self.tmp_path / "test2.jpg"
        Image.new("RGB", (50, 50), color="red").save(self.img2)

        # .txt is a supported document format now (converts to/from Markdown),
        # so use a genuinely unsupported extension for the "should be ignored" case.
        self.unsupported_file = self.tmp_path / "archive.zip"
        self.unsupported_file.write_text("not a supported format")

        self.sub_dir = self.tmp_path / "nested"
        self.sub_dir.mkdir()
        self.img3 = self.sub_dir / "test3.png"
        Image.new("RGB", (20, 20), color="green").save(self.img3)

    def tearDown(self) -> None:
        self.app.selected_files.clear()
        self.app.row_ids.clear()
        self.tmp_dir.cleanup()

    def test_drag_drop_hook_active(self) -> None:
        """Verify drag_drop hook is active on the application window."""
        if sys.platform == "win32":
            child_hwnd = int(self.app.winfo_id())
            top_hwnd = ctypes.windll.user32.GetAncestor(child_hwnd, 2) or child_hwnd
            self.assertTrue(top_hwnd in drag_drop._HOOKED_WINDOWS or child_hwnd in drag_drop._HOOKED_WINDOWS)

    def test_on_drop_files_ingests_valid_media_and_ignores_invalid(self) -> None:
        """Verify _on_drop_files handles files, ignores non-media files, and traverses folders."""
        dropped_items = [
            str(self.img1),
            str(self.unsupported_file),  # should be ignored
            str(self.sub_dir),   # should recursively ingest img3
        ]
        self.app._on_drop_files(dropped_items)

        selected_filenames = [p.name for p in self.app.selected_files]
        self.assertIn("test1.png", selected_filenames)
        self.assertIn("test3.png", selected_filenames)
        self.assertNotIn("archive.zip", selected_filenames)
        self.assertEqual(len(self.app.selected_files), 2)

    def test_simulated_wm_dropfiles_message(self) -> None:
        """Verify simulated WM_DROPFILES message processes without access violation."""
        if sys.platform != "win32":
            return

        received: list[list[str]] = []
        # Rehook with custom callback for test
        drag_drop.hook_dropfiles(self.app, lambda files: received.append(files))

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = wintypes.LPARAM

        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        target = f"{self.img1}\x00\x00".encode("utf-16le")
        df = DROPFILES()
        df.pFiles = ctypes.sizeof(DROPFILES)
        df.fWide = True

        total_size = ctypes.sizeof(DROPFILES) + len(target)
        h_mem = kernel32.GlobalAlloc(0x0042, total_size)
        ptr = kernel32.GlobalLock(h_mem)
        ctypes.memmove(ptr, ctypes.byref(df), ctypes.sizeof(DROPFILES))
        ctypes.memmove(ptr + ctypes.sizeof(DROPFILES), target, len(target))
        kernel32.GlobalUnlock(h_mem)

        child_hwnd = self.app.winfo_id()
        top_hwnd = user32.GetAncestor(child_hwnd, 2) or child_hwnd

        user32.SendMessageW(top_hwnd, 0x0233, h_mem, 0)
        self.app.update()

        self.assertEqual(len(received), 1)
        self.assertEqual(Path(received[0][0]), self.img1)

        # Restore original hook
        drag_drop.hook_dropfiles(self.app, self.app._on_drop_files)


if __name__ == "__main__":
    unittest.main()
