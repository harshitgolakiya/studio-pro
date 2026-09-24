from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any


def get_app_data_dir() -> Path:
    """Return %APPDATA%/Shadow on Windows, ~/Library/Application Support/Shadow
    on macOS, or ~/.config/Shadow elsewhere."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    target = base / "Shadow"
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        # One-time migration from legacy MediaCompressorStudio
        legacy = base / "MediaCompressorStudio"
        if legacy.is_dir():
            legacy_cfg = legacy / "settings.json"
            target_cfg = target / "settings.json"
            if legacy_cfg.is_file() and not target_cfg.exists():
                try:
                    import shutil
                    shutil.copy2(legacy_cfg, target_cfg)
                except Exception:
                    pass
            legacy_key = legacy / "license.key"
            target_key = target / "license.key"
            if legacy_key.is_file() and not target_key.exists():
                try:
                    import shutil
                    shutil.copy2(legacy_key, target_key)
                except Exception:
                    pass
    return target


SETTINGS_FILE = get_app_data_dir() / "settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "System",
    "last_output_directory": "",
    "save_in_source_folder": False,
    "replace_source_files": False,
    "default_format": "WEBP",
    "default_quality": 80,
    "play_sound": True,
    "enable_resize": False,
    "max_dimension": "1920",
    "scale_percent": "75",
    "strip_metadata": False,
    "video_resolution": "Original",
    "video_fps": "Original FPS",
    "enable_watermark": False,
    "watermark_type": "text",
    "watermark_text": "",
    "watermark_logo_path": "",
    "watermark_position": "bottom-right",
    "watermark_opacity": 0.7,
    "license_key": "",
    "license_activated": False,
    "stream_cookie_source": "Auto-Detect Browser (Edge / Chrome)",
    "stream_cookie_file": "",
}


def load_settings() -> dict[str, Any]:
    """Load settings from JSON file or return defaults."""
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        merged.pop("density", None)
        return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict[str, Any]) -> None:
    """Save user settings to JSON file."""
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def update_setting(key: str, value: Any) -> None:
    """Update a single configuration key."""
    current = load_settings()
    current[key] = value
    save_settings(current)
