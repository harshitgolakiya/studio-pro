"""Pre-batch checks: free disk space, and content-duplicate detection."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
from typing import Iterable, Sequence

HEADROOM_BYTES = 50 * 1024 * 1024
# Output-size multipliers versus the input, deliberately pessimistic:
# lossless/raw containers can be several times larger than a compressed source.
_GROWTH = {
    "PNG": 3.0, "TIFF": 3.0, "BMP": 4.0, "PPM": 4.0, "PCX": 3.0, "TGA": 4.0,
    "DDS": 2.0, "QOI": 3.0, "SGI": 4.0, "XBM": 1.0, "ICNS": 2.0, "ICO": 2.0,
    "PDF": 1.5, "WAV": 8.0,
}


@dataclass(frozen=True)
class DiskCheck:
    needed_bytes: int
    free_bytes: int
    destination: Path

    @property
    def ok(self) -> bool:
        return self.free_bytes >= self.needed_bytes


def estimate_needed_bytes(paths: Iterable[Path], target_format: str) -> int:
    key = target_format.upper()
    for name, factor in _GROWTH.items():
        if name in key:
            growth = factor
            break
    else:
        growth = 1.0
    total = 0
    for p in paths:
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return int(total * growth) + HEADROOM_BYTES


def disk_preflight(paths: Sequence[Path], destination: Path, target_format: str) -> DiskCheck:
    probe = destination
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        free = 0
    return DiskCheck(estimate_needed_bytes(paths, target_format), free, destination)


def content_fingerprint(path: Path, chunk: int = 64 * 1024) -> str:
    """Cheap identity: size + hash of the first and last 64 KB."""
    size = path.stat().st_size
    h = hashlib.blake2b(digest_size=16)
    h.update(size.to_bytes(8, "little"))
    with path.open("rb") as fh:
        h.update(fh.read(chunk))
        if size > chunk:
            fh.seek(max(chunk, size - chunk))
            h.update(fh.read(chunk))
    return h.hexdigest()


def find_duplicates(paths: Sequence[Path]) -> dict[Path, Path]:
    """Map each later duplicate to the first path with the same content."""
    seen: dict[str, Path] = {}
    dupes: dict[Path, Path] = {}
    for p in paths:
        try:
            fp = content_fingerprint(p)
        except OSError:
            continue
        if fp in seen and seen[fp] != p:
            dupes[p] = seen[fp]
        else:
            seen.setdefault(fp, p)
    return dupes
