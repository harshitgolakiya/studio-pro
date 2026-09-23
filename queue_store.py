"""Persist the conversion queue so it survives a restart or crash.

The file is rewritten (debounced) on every queue change and flushed on a
clean close, so after a crash it reflects the last state within ~0.5 s.
Restoring re-validates each source file: anything that no longer exists
is dropped, and "Completed" rows are only re-synthesised when their output
file is still present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable

from converter import ConversionResult
from settings import get_app_data_dir
from utils import format_saved_percentage

QUEUE_STATE_VERSION = 2
_DISABLE_ENV = "SHADOW_NO_QUEUE_RESTORE"


def persistence_enabled() -> bool:
    """Off under the test suite (and for anyone who sets the env var) so
    tests never prompt or touch the real queue file."""
    return not os.environ.get(_DISABLE_ENV)


def queue_state_path() -> Path:
    return get_app_data_dir() / "queue_state.json"


@dataclass
class QueueItem:
    path: Path
    status: str = "Ready"
    output_path: Path | None = None
    overrides: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = higher priority; 0 is default
    paused: bool = False  # Per-item pause; worker skips paused items
    depends_on: list[str] = field(default_factory=list)  # Paths of items that must complete first

    @property
    def is_runnable(self) -> bool:
        """True if this item can be picked up by a worker right now."""
        return self.status == "Ready" and not self.paused


@dataclass
class QueueState:
    items: list[QueueItem] = field(default_factory=list)
    output_directory: str = ""
    saved: str = ""
    dropped: int = 0  # entries pruned on load because their file vanished


def build_state(
    files: Iterable[Path],
    results: dict[Path, ConversionResult],
    output_directory: str,
    overrides: dict[Path, dict[str, Any]] | None = None,
) -> QueueState:
    items: list[QueueItem] = []
    for path in files:
        result = results.get(path)
        status = result.status if result is not None else "Ready"
        out = result.output_path if result is not None and status == "Completed" else None
        items.append(QueueItem(Path(path), status, out, dict((overrides or {}).get(path, {}))))
    return QueueState(items, output_directory, datetime.now(timezone.utc).isoformat(timespec="seconds"))


def save_queue_state(state: QueueState, path: Path | None = None) -> Path:
    target = path or queue_state_path()
    payload: dict[str, Any] = {
        "version": QUEUE_STATE_VERSION,
        "saved": state.saved or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "output_directory": state.output_directory,
        "items": [
            {
                "path": str(item.path),
                "status": item.status,
                "output_path": str(item.output_path) if item.output_path else None,
                "overrides": item.overrides,
                "priority": item.priority,
                "paused": item.paused,
                "depends_on": item.depends_on,
            }
            for item in state.items
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_queue_state(path: Path | None = None) -> QueueState | None:
    """Return the saved state with vanished files pruned, or None if there
    is nothing usable to restore."""
    source = path or queue_state_path()
    if not source.is_file():
        return None
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") not in (1, QUEUE_STATE_VERSION):
        return None

    state = QueueState(output_directory=str(data.get("output_directory") or ""), saved=str(data.get("saved") or ""))
    for raw in data.get("items") or []:
        if not isinstance(raw, dict) or not raw.get("path"):
            continue
        src = Path(str(raw["path"]))
        if not src.is_file():
            state.dropped += 1
            continue
        out_raw = raw.get("output_path")
        out = Path(str(out_raw)) if out_raw else None
        status = str(raw.get("status") or "Ready")
        if status == "Completed" and (out is None or not out.is_file()):
            status, out = "Ready", None
        elif status != "Completed":
            status, out = "Ready", None
        raw_overrides = raw.get("overrides")
        overrides = dict(raw_overrides) if isinstance(raw_overrides, dict) else {}
        priority = int(raw.get("priority") or 0)
        paused = bool(raw.get("paused", False))
        raw_deps = raw.get("depends_on")
        depends_on = list(raw_deps) if isinstance(raw_deps, list) else []
        state.items.append(QueueItem(src, status, out, overrides, priority, paused, depends_on))
    return state if state.items else None


def clear_queue_state(path: Path | None = None) -> None:
    target = path or queue_state_path()
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def synthesize_result(item: QueueItem) -> ConversionResult | None:
    """Rebuild a Completed row's result from the files on disk."""
    if item.status != "Completed" or item.output_path is None:
        return None
    try:
        original = item.path.stat().st_size
        output = item.output_path.stat().st_size
    except OSError:
        return None
    return ConversionResult(
        item.path,
        item.output_path,
        original,
        output,
        format_saved_percentage(original, output),
        "Completed",
    )
