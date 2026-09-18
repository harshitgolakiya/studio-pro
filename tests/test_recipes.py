from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recipes import (
    RECIPE_FIELDS,
    RECIPE_SCHEMA_VERSION,
    Recipe,
    RecipeError,
    coerce_settings,
    delete_recipe,
    duplicate_recipe,
    export_recipe,
    find_recipe,
    import_recipe,
    list_recipes,
    load_recipe,
    parse_recipe,
    save_recipe,
    serialize_recipe,
)


class RecipeModelTests(unittest.TestCase):
    def test_coerce_fills_defaults_and_casts_types(self) -> None:
        s = coerce_settings({"quality": "65", "lossless": "true", "enable_resize": 1, "bogus": 1})
        self.assertEqual(s["quality"], 65)
        self.assertIs(s["lossless"], True)
        self.assertIs(s["enable_resize"], True)
        self.assertNotIn("bogus", s)
        self.assertEqual(set(s), set(RECIPE_FIELDS))

    def test_coerce_clamps_quality_and_survives_garbage(self) -> None:
        self.assertEqual(coerce_settings({"quality": 500})["quality"], 100)
        self.assertEqual(coerce_settings({"quality": "not a number"})["quality"], 80)

    def test_round_trip(self) -> None:
        r = Recipe(name="  Web Hero  ", settings={"target_format": "AVIF", "quality": 70}, description="hero images")
        parsed = parse_recipe(serialize_recipe(r))
        self.assertEqual(parsed.name, "Web Hero")
        self.assertEqual(parsed.settings["target_format"], "AVIF")
        self.assertEqual(parsed.settings["quality"], 70)
        self.assertEqual(parsed.description, "hero images")
        self.assertEqual(parsed.version, RECIPE_SCHEMA_VERSION)

    def test_v1_flat_file_migrates(self) -> None:
        legacy = {"name": "Old", "format": "PNG", "quality": 90, "enable_resize": True, "max_dimension_text": "800"}
        parsed = parse_recipe(legacy)
        self.assertEqual(parsed.name, "Old")
        self.assertEqual(parsed.settings["target_format"], "PNG")
        self.assertEqual(parsed.settings["max_dimension_text"], "800")
        self.assertEqual(parsed.version, RECIPE_SCHEMA_VERSION)

    def test_future_version_is_refused(self) -> None:
        with self.assertRaises(RecipeError):
            parse_recipe({"version": RECIPE_SCHEMA_VERSION + 1, "settings": {}})

    def test_non_object_is_refused(self) -> None:
        with self.assertRaises(RecipeError):
            parse_recipe(["not", "a", "dict"])


class RecipeStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_save_list_find_delete(self) -> None:
        save_recipe(Recipe("Zeta", {"target_format": "PNG"}), self.dir)
        save_recipe(Recipe("alpha", {"target_format": "WEBP"}), self.dir)
        names = [r.name for r in list_recipes(self.dir)]
        self.assertEqual(names, ["alpha", "Zeta"])
        self.assertEqual(find_recipe("Zeta", self.dir).settings["target_format"], "PNG")
        self.assertTrue(delete_recipe("Zeta", self.dir))
        self.assertFalse(delete_recipe("Zeta", self.dir))
        self.assertIsNone(find_recipe("Zeta", self.dir))

    def test_duplicate_and_export_import(self) -> None:
        save_recipe(Recipe("Base", {"quality": 55}), self.dir)
        copy = duplicate_recipe("Base", "Base copy", self.dir)
        self.assertEqual(copy.settings["quality"], 55)
        self.assertEqual(len(list_recipes(self.dir)), 2)

        out = export_recipe("Base copy", self.dir / "exports" / "x.shadow-recipe.json", self.dir)
        self.assertTrue(out.is_file())

        other = Path(self.tmp.name) / "other"
        imported = import_recipe(out, other)
        self.assertEqual(imported.name, "Base copy")
        self.assertEqual(find_recipe("Base copy", other).settings["quality"], 55)

    def test_import_upgrades_legacy_file(self) -> None:
        legacy = self.dir / "old.json"
        legacy.write_text(json.dumps({"format": "JPEG", "quality": "85"}), encoding="utf-8")
        imported = import_recipe(legacy, self.dir)
        self.assertEqual(imported.settings["target_format"], "JPEG")
        stored = json.loads(next(self.dir.glob("*.shadow-recipe.json")).read_text(encoding="utf-8"))
        self.assertEqual(stored["version"], RECIPE_SCHEMA_VERSION)

    def test_unreadable_files_are_skipped_by_list(self) -> None:
        (self.dir / "bad.shadow-recipe.json").write_text("{not json", encoding="utf-8")
        save_recipe(Recipe("Good", {}), self.dir)
        self.assertEqual([r.name for r in list_recipes(self.dir)], ["Good"])
        with self.assertRaises(RecipeError):
            load_recipe(self.dir / "bad.shadow-recipe.json")


class RecipeAppIntegrationTests(unittest.TestCase):
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

    def test_collect_then_apply_round_trips_every_field(self) -> None:
        app = self.app
        app.target_format.set("AVIF")
        app.quality.set(42)
        app.quality_text.set("42")
        app.enable_resize.set(True)
        app.max_dimension_text.set("1234")
        app.watermark_text.set("© test")
        app.filename_suffix.set("-web")

        snapshot = app._collect_recipe_settings()
        self.assertEqual(set(snapshot), set(RECIPE_FIELDS))
        self.assertEqual(snapshot["target_format"], "AVIF")
        self.assertEqual(snapshot["quality"], 42)

        app.target_format.set("PNG")
        app.quality.set(90)
        app.enable_resize.set(False)
        app.filename_suffix.set("")

        app._apply_recipe_settings(snapshot)
        app.update()
        self.assertEqual(app.target_format.get(), "AVIF")
        self.assertEqual(app.quality.get(), 42)
        self.assertEqual(app.quality_text.get(), "42")
        self.assertTrue(app.enable_resize.get())
        self.assertEqual(app.max_dimension_text.get(), "1234")
        self.assertEqual(app.filename_suffix.get(), "-web")
        self.assertEqual(app.preset_profile.get(), "Manual / Custom")
        self.assertEqual(app.convert_button.cget("text"), "Convert to AVIF")


if __name__ == "__main__":
    unittest.main()
