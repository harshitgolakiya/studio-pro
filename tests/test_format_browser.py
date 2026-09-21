from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401 -- stubs modal dialogs so the suite can never hang

import customtkinter as ctk

from converter import IMAGE_FORMAT_CAPABILITIES
from format_browser import (
    MEDIA_FORMAT_CAPABILITIES,
    FormatBrowserDialog,
    badge_style,
    build_catalog,
    describe_format,
    filter_catalog,
    group_by_category,
)
from main import IMAGE_FORMAT_OPTIONS


class FormatCatalogTests(unittest.TestCase):
    def test_every_image_option_is_described(self) -> None:
        for label in IMAGE_FORMAT_OPTIONS:
            entry = describe_format(label)
            self.assertNotEqual(entry.category, "Other", label)
            self.assertTrue(entry.badges, label)

    def test_pdf_combined_alias_maps_to_pdf_capabilities(self) -> None:
        entry = describe_format("PDF (Combined)")
        self.assertEqual(entry.category, IMAGE_FORMAT_CAPABILITIES["PDF"]["category"])
        self.assertEqual(entry.label, "PDF (Combined)")

    def test_media_options_are_described(self) -> None:
        for label in MEDIA_FORMAT_CAPABILITIES:
            entry = describe_format(label)
            self.assertIn(entry.category, {"Video", "Audio", "Document"}, label)

    def test_unknown_label_degrades_gracefully(self) -> None:
        entry = describe_format("Something New")
        self.assertEqual(entry.category, "Other")
        self.assertEqual(entry.badges, ())

    def test_filter_matches_label_category_and_badges(self) -> None:
        catalog = build_catalog([*IMAGE_FORMAT_OPTIONS, "Video: MP4", "Audio: Opus"])
        self.assertEqual([e.label for e in filter_catalog(catalog, "mp4")], ["Video: MP4"])
        alpha = {e.label for e in filter_catalog(catalog, "alpha")}
        self.assertIn("PNG", alpha)
        self.assertNotIn("JPEG", alpha)
        self.assertEqual([e.label for e in filter_catalog(catalog, "audio opus")], ["Audio: Opus"])
        self.assertEqual(filter_catalog(catalog, "no-such-thing"), [])
        self.assertEqual(len(filter_catalog(catalog, "   ")), len(catalog))

    def test_grouping_preserves_order(self) -> None:
        catalog = build_catalog(["WEBP", "Video: MP4", "AVIF", "Audio: MP3"])
        groups = group_by_category(catalog)
        self.assertEqual([name for name, _ in groups], ["Modern web", "Video", "Audio"])
        self.assertEqual([e.label for e in groups[0][1]], ["WEBP", "AVIF"])

    def test_every_badge_has_a_style(self) -> None:
        seen: set[str] = set()
        for cap in IMAGE_FORMAT_CAPABILITIES.values():
            seen.update(str(b) for b in cap["badges"])
        for cap in MEDIA_FORMAT_CAPABILITIES.values():
            seen.update(cap["badges"])
        for badge in seen:
            fill, text = badge_style(badge)
            self.assertEqual(len(fill), 2, badge)
            self.assertEqual(len(text), 2, badge)


class FormatBrowserDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_search_and_keyboard_selection(self) -> None:
        chosen: list[str] = []
        options = [*IMAGE_FORMAT_OPTIONS, "Video: MP4", "Video: WebM"]
        dialog = FormatBrowserDialog(self.root, options, "WEBP", chosen.append)
        dialog.update()

        self.assertEqual(len(dialog._visible), len(options))
        self.assertEqual(dialog._visible[dialog._cursor].label, "WEBP")

        dialog.query.set("video")
        dialog.update()
        self.assertEqual([e.label for e in dialog._visible], ["Video: MP4", "Video: WebM"])
        self.assertEqual(dialog._cursor, 0)

        dialog._move(1)
        dialog._choose_cursor()
        self.assertEqual(chosen, ["Video: WebM"])
        self.assertFalse(dialog.winfo_exists())

    def test_no_match_renders_empty_state(self) -> None:
        dialog = FormatBrowserDialog(self.root, ["WEBP", "PNG"], "PNG", lambda _l: None)
        dialog.query.set("zzz")
        dialog.update()
        self.assertEqual(dialog._visible, [])
        dialog._choose_cursor()  # must be a no-op, not an IndexError
        self.assertTrue(dialog.winfo_exists())
        dialog.destroy()


class FormatBrowserIntegrationTests(unittest.TestCase):
    """Drive the real main window through the Browse button."""

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

    def test_browse_button_selection_updates_format_and_cta(self) -> None:
        app = self.app
        app.target_format.set("WEBP")
        app._format_changed("WEBP")
        app.update()

        app.format_browse_button.invoke()
        app.update()
        dialog = next(
            w for w in app.winfo_children() if isinstance(w, FormatBrowserDialog)
        )
        self.assertEqual(
            [e.label for e in dialog._visible], list(app.format_menu.cget("values"))
        )

        dialog.query.set("png")
        dialog.update()
        self.assertEqual(dialog._visible[0].label, "PNG")
        dialog._choose_cursor()
        app.update()

        self.assertEqual(app.target_format.get(), "PNG")
        self.assertEqual(app.convert_button.cget("text"), "Convert to PNG")
        badges = [
            child.cget("text")
            for child in app.format_capability_frame.winfo_children()
        ]
        self.assertIn("Lossless", badges)
        self.assertIn("Alpha", badges)


if __name__ == "__main__":
    unittest.main()
