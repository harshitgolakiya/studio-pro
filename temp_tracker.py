"""Registry of in-progress temp files so a crash mid-batch can't leave litter.

Converters write output to ``tmp*.tmp.<ext>`` beside the destination and
atomically rename on success; their ``finally`` blocks clean up on error.
What they can't cover is the process dying. Registering every temp path
here (a tiny JSON file in app data) lets the next launch delete exactly
the files we created and nothing else.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from settings import get_app_data_dir

_lock = threading.Lock()


def registry_path() -> Path:
    override = os.environ.get("SHADOW_TEMP_REGISTRY")
    return Path(override) if override else get_app_data_dir() / "temp_files.json"


def _load() -> list[str]:
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
        return [str(p) for p in data] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(entries: list[str]) -> None:
    try:
        target = registry_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if entries:
            target.write_text(json.dumps(entries), encoding="utf-8")
        elif target.exists():
            target.unlink()
    except OSError:
        pass


def register(path: Path) -> None:
    with _lock:
        entries = _load()
        key = str(path)
        if key not in entries:
            entries.append(key)
            _save(entries)


def unregister(path: Path) -> None:
    with _lock:
        entries = _load()
        key = str(path)
        if key in entries:
            entries.remove(key)
            _save(entries)


def cleanup_stale() -> list[Path]:
    """Delete every registered temp file that still exists; returns what was removed."""
    removed: list[Path] = []
    with _lock:
        for entry in _load():
            p = Path(entry)
            try:
                if p.is_file() and ".tmp" in p.name:
                    p.unlink()
                    removed.append(p)
            except OSError:
                continue
        _save([])
    return removed
