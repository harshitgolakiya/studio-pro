"""Run through the frozen app to prove optional models work outside its bundle."""
import json
from pathlib import Path
import sys
from model_catalog import find_entry, install, is_installed, remove
from studio_runtime import model_directory, resource_root
from ocr_engine import _engine

assert sys.platform == "darwin" and getattr(sys, "frozen", False)
root = model_directory().resolve()
assert resource_root().resolve() not in root.parents
assert root == (Path.home() / "Library/Application Support/Shadow/models").resolve()
entry = find_entry("ocr-el_PP-OCRv5_rec_mobile")
install(entry)
assert is_installed(entry)
_engine("Greek")
remove(entry)
assert not is_installed(entry)
report = Path("studio-verification/model-download.json")
report.parent.mkdir(parents=True, exist_ok=True)
report.write_text(json.dumps({"passed": True, "model": entry.key, "model_directory": str(root), "api_key_required": False}, indent=2), encoding="utf-8")
