from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import settings


class SettingsReliabilityTests(unittest.TestCase):
    def test_save_is_atomic_and_round_trips_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Shadow" / "settings.json"
            with patch("settings.SETTINGS_FILE", path):
                self.assertTrue(settings.save_settings({"theme": "Light", "label": "✓"}))
                self.assertEqual(settings.load_settings()["label"], "✓")
                self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_non_object_or_corrupt_settings_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            with patch("settings.SETTINGS_FILE", path):
                path.write_text("[]", encoding="utf-8")
                self.assertEqual(settings.load_settings()["theme"], "System")
                path.write_text("{broken", encoding="utf-8")
                self.assertEqual(settings.load_settings()["default_format"], "WEBP")

    def test_failed_save_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "directory-instead-of-file"
            directory.mkdir()
            with patch("settings.SETTINGS_FILE", directory):
                self.assertFalse(settings.save_settings({"theme": "Dark"}))


if __name__ == "__main__":
    unittest.main()
