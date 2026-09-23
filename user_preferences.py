"""Offline, privacy-first per-user preference learning.

Learns user codec and quality preferences locally without sending any media,
metadata, or telemetry over the network. Stored in local JSON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import threading
from typing import Any

from settings import get_app_data_dir


def _default_prefs_path() -> Path:
    override = os.environ.get("SHADOW_USER_PREFS_FILE")
    if override:
        return Path(override)
    return get_app_data_dir() / "user_preferences.json"


@dataclass
class PreferenceEntry:
    counts: dict[str, int] = field(default_factory=dict)
    average_qualities: dict[str, float] = field(default_factory=dict)

    def record(self, codec: str, quality: int | None = None) -> None:
        c = codec.upper().strip()
        self.counts[c] = self.counts.get(c, 0) + 1
        if quality is not None and 1 <= quality <= 100:
            current_avg = self.average_qualities.get(c, float(quality))
            total_n = self.counts[c]
            # Incremental moving average
            self.average_qualities[c] = round(current_avg + (quality - current_avg) / total_n, 1)

    def preferred_codec(self) -> str | None:
        if not self.counts:
            return None
        return max(self.counts.items(), key=lambda item: item[1])[0]


class UserPreferenceStore:
    """Local storage and learning of user format and quality choices."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_prefs_path()
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self.load()

    def _make_key(self, content_kind: str, destination: str) -> str:
        return f"{content_kind.strip().lower()}:{destination.strip().lower()}"

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._data = {}
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2)
                os.replace(tmp, self.path)
            except Exception:
                pass

    def record_choice(
        self,
        content_kind: str,
        destination: str,
        codec: str,
        quality: int | None = None,
    ) -> None:
        """Record an accepted or selected conversion recipe choice."""
        key = self._make_key(content_kind, destination)
        with self._lock:
            entry_dict = self._data.get(key, {"counts": {}, "average_qualities": {}})
            entry = PreferenceEntry(
                counts=entry_dict.get("counts", {}),
                average_qualities=entry_dict.get("average_qualities", {}),
            )
            entry.record(codec, quality)
            self._data[key] = asdict(entry)
        self.save()

    def get_preferred_codec(self, content_kind: str, destination: str) -> str | None:
        """Return the most frequently chosen codec for the specified content kind and destination."""
        key = self._make_key(content_kind, destination)
        with self._lock:
            entry_dict = self._data.get(key)
            if not entry_dict:
                return None
            entry = PreferenceEntry(
                counts=entry_dict.get("counts", {}),
                average_qualities=entry_dict.get("average_qualities", {}),
            )
            return entry.preferred_codec()

    def get_preferred_quality(self, content_kind: str, destination: str, codec: str) -> int | None:
        """Return the user's average chosen quality for this codec."""
        key = self._make_key(content_kind, destination)
        c = codec.upper().strip()
        with self._lock:
            entry_dict = self._data.get(key)
            if not entry_dict:
                return None
            avg = entry_dict.get("average_qualities", {}).get(c)
            return int(round(avg)) if avg is not None else None

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            if self.path.exists():
                try:
                    self.path.unlink()
                except Exception:
                    pass


# Singleton instance
_PREFERENCE_STORE: UserPreferenceStore | None = None


def get_preference_store() -> UserPreferenceStore:
    global _PREFERENCE_STORE
    if _PREFERENCE_STORE is None:
        _PREFERENCE_STORE = UserPreferenceStore()
    return _PREFERENCE_STORE
