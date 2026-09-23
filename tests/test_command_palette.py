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

import customtkinter as ctk
from PIL import Image

from command_palette import CommandPalette, PaletteAction, filter_actions


class FilterTests(unittest.TestCase):
    def _actions(self) -> list[PaletteAction]:
        return [
            PaletteAction("Clear all", lambda: None, "Queue", "", "empty remove everything"),
            PaletteAction("Add files", lambda: None, "Queue", "Ctrl+O", "open images"),
            PaletteAction("Convert", lambda: None, "Conversion", "Ctrl+Enter", "start run"),
            PaletteAction("Theme: Dark", lambda: None, "Appearance"),
        ]

    def test_words_must_all_match_and_prefix_ranks_first(self) -> None:
        acts = self._actions()
        self.assertEqual([a.label for a in filter_actions(acts, "")], [a.label for a in acts])
        self.assertEqual([a.label for a in filter_actions(acts, "add")], ["Add files"])
        self.assertEqual([a.label for a in filter_actions(acts, "queue")], ["Add files", "Clear all"])
        self.assertEqual([a.label for a in filter_actions(acts, "dark theme")], ["Theme: Dark"])
        self.assertEqual(filter_actions(acts, "nothing here"), [])
        self.assertEqual([a.label for a in filter_actions(acts, "c")][0], "Clear all")


class PaletteAppTests(unittest.TestCase):
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

    def test_palette_runs_action_and_respects_enabled(self) -> None:
        app = self.app
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "a.png"
            Image.new("RGB", (20, 20), "red").save(img)
            app._ingest_image_paths([img])
            self.assertEqual(len(app.selected_files), 1)

            palette = app._open_command_palette()
            self.assertIsInstance(palette, CommandPalette)
            labels = [a.label for a in palette._actions]
            for expected in ("Add files…", "Convert", "Clear all", "Browse formats…", "Recipes…", "Theme: Dark"):
                self.assertIn(expected, labels)

            palette.query.set("clear all")
            palette.update()
            self.assertEqual(palette._visible[0].label, "Clear all")
            palette.run_cursor()
            app.update()
            self.assertEqual(app.selected_files, [])
            self.assertFalse(palette.winfo_exists())

            palette = app._open_command_palette()
            palette.query.set("preview")
            palette.update()
            self.assertFalse(palette._visible[0].enabled())
            palette.run_cursor()  # disabled: must not run or close
            self.assertTrue(palette.winfo_exists())
            palette.destroy()


if __name__ == "__main__":
    unittest.main()
