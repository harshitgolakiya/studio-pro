from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

from PIL import Image

from headless_cli import convert_path, load_watch_router, main
from recipes import Recipe, save_recipe


class HeadlessCliTests(unittest.TestCase):
    def test_watch_rules_route_by_extension_and_skip_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe_path = save_recipe(Recipe("png", {"target_format": "PNG"}), root)
            rules_path = root / "rules.json"
            rules_path.write_text(
                '{"rules": [{"extensions": [".png"], "recipe": "png.shadow-recipe.json", "output": "png-out"}], "default": null}',
                encoding="utf-8",
            )
            router = load_watch_router(rules_path, root / "incoming", root / "fallback", Recipe("default").settings)
            png = root / "photo.png"
            png.write_bytes(b"png")
            self.assertEqual(router(png)[0], root / "incoming" / "png-out")
            self.assertEqual(router(root / "photo.jpg"), None)

    def test_convert_path_uses_recipe_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.png"
            Image.new("RGBA", (16, 12), (20, 120, 80, 255)).save(source)
            result = convert_path(source, root / "out", Recipe("test", {"target_format": "WEBP", "quality": 65}).settings)
            self.assertEqual(result.status, "Completed")
            self.assertTrue(result.output_path and result.output_path.is_file())

    def test_cli_converts_recipe_and_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.png"
            Image.new("RGB", (8, 8), "red").save(source)
            recipe_path = save_recipe(Recipe("web", {"target_format": "WEBP", "quality": 70}), root)
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main([str(source), "--output", str(root / "out"), "--recipe", str(recipe_path), "--json"])
            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "out" / "sample.webp").is_file())
            events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
            self.assertEqual(events, ["started", "progress", "result", "finished"])


if __name__ == "__main__":
    unittest.main()