"""Workflow hooks — before/after events for each conversion job.

This module provides a simple, file-based hook system that lets users
run custom actions before or after conversions.  Hooks can be:

  1. **Python scripts** in ``<app-data>/hooks/`` named by event
     (e.g., ``before_convert.py``, ``after_convert.py``).
  2. **Programmatic callbacks** registered via the plugin SDK's
     ``registry.add_hook(event, fn)`` mechanism.

Supported lifecycle events:
  - ``before_convert``  – runs before each file conversion
  - ``after_convert``   – runs after each file conversion
  - ``before_batch``    – runs before a batch starts
  - ``after_batch``     – runs after a batch completes
  - ``on_error``        – runs when a conversion fails

Script hooks receive a JSON string on stdin with event context.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from settings import get_app_data_dir

log = logging.getLogger(__name__)

HOOK_EVENTS = (
    "before_convert",
    "after_convert",
    "before_batch",
    "after_batch",
    "on_error",
)


def _hooks_dir() -> Path:
    """Return the hooks directory under app data."""
    return get_app_data_dir() / "hooks"


def _find_script_hooks(event: str) -> list[Path]:
    """Find all script hooks for the given event."""
    hooks_dir = _hooks_dir()
    if not hooks_dir.is_dir():
        return []
    matches: list[Path] = []
    for ext in (".py", ".ps1", ".bat", ".sh"):
        candidate = hooks_dir / f"{event}{ext}"
        if candidate.is_file():
            matches.append(candidate)
    # Also accept numbered variants: before_convert_01.py, etc.
    for entry in sorted(hooks_dir.iterdir()):
        if entry.stem.startswith(event) and entry != hooks_dir / f"{event}{entry.suffix}":
            if entry.suffix in (".py", ".ps1", ".bat", ".sh"):
                matches.append(entry)
    return matches


def _run_script_hook(script: Path, context: dict[str, Any]) -> dict[str, Any]:
    """Run a script hook and return its result."""
    context_json = json.dumps(context, default=str)
    try:
        if script.suffix == ".py":
            cmd = [sys.executable, str(script)]
        elif script.suffix == ".ps1":
            cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        elif script.suffix == ".bat":
            cmd = ["cmd", "/c", str(script)]
        else:
            cmd = [str(script)]

        result = subprocess.run(
            cmd,
            input=context_json,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(script.parent),
        )
        return {
            "script": str(script),
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        log.warning("Hook script timed out: %s", script)
        return {"script": str(script), "returncode": -1, "error": "timeout"}
    except Exception as e:
        log.error("Hook script failed: %s – %s", script, e)
        return {"script": str(script), "returncode": -1, "error": str(e)}


@dataclass
class HookManager:
    """Manages workflow hook execution for the conversion pipeline."""

    _callbacks: dict[str, list[Callable[..., Any]]] = field(default_factory=dict)
    enabled: bool = True

    def register(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a programmatic callback for an event."""
        if event not in HOOK_EVENTS:
            raise ValueError(f"Unknown hook event: {event}. Valid: {HOOK_EVENTS}")
        self._callbacks.setdefault(event, []).append(callback)

    def unregister(self, event: str, callback: Callable[..., Any]) -> None:
        """Remove a previously registered callback."""
        cbs = self._callbacks.get(event, [])
        if callback in cbs:
            cbs.remove(callback)

    def fire(self, event: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Fire all hooks (scripts + callbacks) for the event.

        Returns a list of result dicts from each hook executed.
        """
        if not self.enabled:
            return []

        ctx = context or {}
        ctx["event"] = event
        results: list[dict[str, Any]] = []

        # Run script hooks
        for script in _find_script_hooks(event):
            result = _run_script_hook(script, ctx)
            results.append(result)
            log.debug("Script hook %s → returncode %s", script.name, result.get("returncode"))

        # Run programmatic callbacks
        for cb in self._callbacks.get(event, []):
            try:
                rv = cb(ctx)
                results.append({
                    "callback": cb.__name__,
                    "result": rv,
                })
            except Exception as e:
                log.warning("Callback %s raised: %s", cb.__name__, e)
                results.append({
                    "callback": cb.__name__,
                    "error": str(e),
                })

        return results

    def fire_before_convert(self, source_path: Path, settings: dict[str, Any]) -> list[dict[str, Any]]:
        return self.fire("before_convert", {
            "source": str(source_path),
            "settings": settings,
        })

    def fire_after_convert(self, source_path: Path, output_path: Path | None,
                           status: str, size_info: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.fire("after_convert", {
            "source": str(source_path),
            "output": str(output_path) if output_path else None,
            "status": status,
            **(size_info or {}),
        })

    def fire_before_batch(self, files: list[str], settings: dict[str, Any]) -> list[dict[str, Any]]:
        return self.fire("before_batch", {
            "files": files,
            "total": len(files),
            "settings": settings,
        })

    def fire_after_batch(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        completed = sum(1 for r in results if r.get("status") == "Completed")
        failed = sum(1 for r in results if r.get("status") == "Failed")
        return self.fire("after_batch", {
            "results": results,
            "total": len(results),
            "completed": completed,
            "failed": failed,
        })

    def fire_on_error(self, source_path: Path, error: Exception) -> list[dict[str, Any]]:
        return self.fire("on_error", {
            "source": str(source_path),
            "error": str(error),
            "error_type": type(error).__name__,
        })


# Global singleton
_hook_manager: HookManager | None = None


def get_hook_manager() -> HookManager:
    global _hook_manager
    if _hook_manager is None:
        _hook_manager = HookManager()
    return _hook_manager
