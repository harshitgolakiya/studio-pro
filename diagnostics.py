"""Structured logging to a rotating file, and a one-click diagnostics bundle."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any
import zipfile

from settings import get_app_data_dir, load_settings

APP_VERSION = "2.0.0"
LOG_NAME = "shadow.log"
_REDACT_KEYS = ("license_key", "stream_cookie_file")


def log_path() -> Path:
    return get_app_data_dir() / LOG_NAME


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Idempotent: attach one rotating file handler (1 MB x 3) to the root logger."""
    root = logging.getLogger()
    if any(getattr(h, "_shadow_handler", False) for h in root.handlers):
        return logging.getLogger("shadow")
    try:
        handler = RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        return logging.getLogger("shadow")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler._shadow_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    return logging.getLogger("shadow")


def _ffmpeg_version() -> str:
    try:
        from media_engine import get_ffmpeg_path

        path = get_ffmpeg_path()
        if not path:
            return "not found"
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5, creationflags=flags)
        first = (out.stdout or out.stderr).splitlines()[0] if (out.stdout or out.stderr) else ""
        return f"{first} ({path})"
    except Exception as exc:
        return f"error: {exc}"


def system_report() -> dict[str, Any]:
    from PIL import __version__ as pillow_version, features

    report: dict[str, Any] = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": APP_VERSION,
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "pillow": pillow_version,
        "pillow_features": {name: bool(features.check(name)) for name in ("webp", "avif", "jpg", "jpg_2000", "zlib")},
        "ffmpeg": _ffmpeg_version(),
        "app_data_dir": str(get_app_data_dir()),
    }
    try:
        import pillow_heif

        report["pillow_heif"] = getattr(pillow_heif, "__version__", "present")
    except Exception:
        report["pillow_heif"] = "missing"
    try:
        import customtkinter

        report["customtkinter"] = customtkinter.__version__
    except Exception:
        report["customtkinter"] = "unknown"
    return report


def redacted_settings() -> dict[str, Any]:
    data = dict(load_settings())
    for key in _REDACT_KEYS:
        if data.get(key):
            data[key] = "<redacted>"
    return data


def export_diagnostics(destination: Path, history_lines: int = 500) -> Path:
    """Zip: system report, redacted settings, recent history, queue state, logs."""
    destination = Path(destination)
    if destination.is_dir() or not destination.suffix:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = destination / f"shadow-diagnostics-{stamp}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    data_dir = get_app_data_dir()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system.json", json.dumps(system_report(), indent=2))
        zf.writestr("settings.json", json.dumps(redacted_settings(), indent=2))
        history = data_dir / "history.jsonl"
        if history.is_file():
            try:
                lines = history.read_text(encoding="utf-8").splitlines()[-history_lines:]
                zf.writestr("history.jsonl", "\n".join(lines) + "\n")
            except OSError:
                pass
        queue_state = data_dir / "queue_state.json"
        if queue_state.is_file():
            zf.write(queue_state, "queue_state.json")
        recipes_dir = data_dir / "recipes"
        if recipes_dir.is_dir():
            zf.writestr("recipes.txt", "\n".join(sorted(p.name for p in recipes_dir.glob("*.json"))) + "\n")
        for log in sorted(data_dir.glob(f"{LOG_NAME}*")):
            try:
                zf.write(log, f"logs/{log.name}")
            except OSError:
                pass
    return destination
