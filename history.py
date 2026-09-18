"""Conversion history: an append-only JSON-lines log of every processed item,
each carrying the recipe-style settings snapshot that produced it so any
past result can be reproduced."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence
import uuid

from converter import ConversionResult
from recipes import coerce_settings
from settings import get_app_data_dir

MAX_ENTRIES = 5000


def history_path() -> Path:
    override = os.environ.get("SHADOW_HISTORY_FILE")
    if override:
        return Path(override)
    return get_app_data_dir() / "history.jsonl"


@dataclass
class HistoryEntry:
    batch_id: str
    timestamp: str
    source: str
    output: str
    status: str
    error: str
    original_size: int | None
    output_size: int | None
    saved: str
    target_format: str
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def when(self) -> datetime:
        try:
            return datetime.fromisoformat(self.timestamp)
        except ValueError:
            return datetime.fromtimestamp(0, timezone.utc)

    @property
    def source_name(self) -> str:
        return Path(self.source).name

    def search_text(self) -> str:
        return " ".join((self.source, self.output, self.status, self.error, self.target_format, self.timestamp[:10])).lower()


def record_batch(
    results: Sequence[ConversionResult],
    settings: dict[str, Any],
    target_format: str,
    path: Path | None = None,
) -> str:
    """Append one line per result; returns the batch id."""
    batch_id = uuid.uuid4().hex[:12]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = coerce_settings(settings)
    target = path or history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for r in results:
            entry = HistoryEntry(
                batch_id=batch_id,
                timestamp=stamp,
                source=str(r.source_path),
                output=str(r.output_path) if r.output_path else "",
                status=r.status,
                error=r.error or "",
                original_size=r.original_size,
                output_size=r.output_size,
                saved=r.saved,
                target_format=target_format,
                settings=snapshot,
            )
            fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    _trim(target)
    return batch_id


def _trim(target: Path) -> None:
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_ENTRIES:
        return
    tmp = target.with_suffix(".tmp")
    tmp.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def load_history(path: Path | None = None, limit: int | None = None) -> list[HistoryEntry]:
    """Newest first. Malformed lines are skipped."""
    target = path or history_path()
    if not target.is_file():
        return []
    entries: list[HistoryEntry] = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            entries.append(HistoryEntry(**{k: data.get(k, "") for k in HistoryEntry.__dataclass_fields__}))
        except (ValueError, TypeError):
            continue
    entries.reverse()
    return entries[:limit] if limit else entries


def search_history(entries: Iterable[HistoryEntry], query: str) -> list[HistoryEntry]:
    words = [w for w in query.lower().split() if w]
    if not words:
        return list(entries)
    return [e for e in entries if all(w in e.search_text() for w in words)]


def clear_history(path: Path | None = None) -> None:
    target = path or history_path()
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def summarize(entries: Sequence[HistoryEntry]) -> dict[str, Any]:
    completed = [e for e in entries if e.status == "Completed"]
    original = sum(e.original_size or 0 for e in completed)
    output = sum(e.output_size or 0 for e in completed)
    return {
        "items": len(entries),
        "completed": len(completed),
        "failed": sum(e.status == "Failed" for e in entries),
        "bytes_saved": max(0, original - output),
        "batches": len({e.batch_id for e in entries}),
    }
