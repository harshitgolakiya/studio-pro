"""Retain model provenance and model cards alongside staged offline assets."""
import json
from pathlib import Path
import sys
import urllib.request

from model_catalog import catalog, is_installed
from studio_runtime import model_directory


def main():
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    folder = model_directory() / "licenses"
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    errors = []
    for entry in catalog():
        if not is_installed(entry):
            continue
        sources = [url for url, _ in entry.files]
        if entry.repo:
            sources.append("https://huggingface.co/" + entry.repo)
            notice_url = f"https://huggingface.co/{entry.repo}/raw/main/README.md"
        elif entry.kind == "voice":
            notice_url = entry.files[0][0].rsplit("/", 1)[0] + "/MODEL_CARD"
        else:
            notice_url = ""
        if entry.archive:
            sources.append(entry.archive[0])
        entries.append({"key": entry.key, "sources": sources})
        if notice_url:
            try:
                request = urllib.request.Request(notice_url, headers={"User-Agent": "Shadow-Studio-Setup"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read()
                (folder / (entry.key + ".md")).write_bytes(data)
            except Exception as exc:
                errors.append({"key": entry.key, "url": notice_url, "error": str(exc)})
    (folder / "catalog.json").write_text(json.dumps({"models": entries, "unavailable_cards": errors}, indent=2), encoding="utf-8")
    print(f"Retained provenance for {len(entries)} models; {len(errors)} remote cards unavailable")


if __name__ == "__main__":
    main()
