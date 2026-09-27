"""Batch telemetry and resource-aware worker tuning helpers."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Sequence


_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".mpeg", ".mpg"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".ogg", ".m4a", ".opus", ".flac", ".wma"}
_IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".heic", ".heif", ".ico", ".jfif", ".jp2",
    ".jpeg", ".jpg", ".jxl", ".png", ".tif", ".tiff", ".webp",
}


@dataclass(frozen=True)
class TelemetrySnapshot:
    completed: int
    total: int
    elapsed: float
    throughput: float
    eta: float | None
    memory_bytes: int
    workers: int
    gpu: str

    @property
    def progress(self) -> float:
        return self.completed / self.total if self.total else 1.0

    def status_text(self) -> str:
        rate = f"{self.throughput:.1f}/s" if self.throughput else "--/s"
        eta = "done" if self.eta is None else f"ETA {self.eta:.1f}s"
        memory = f"{self.memory_bytes / (1024 * 1024):.0f} MB"
        return f"{self.completed}/{self.total} | {rate} | {eta} | {memory} | {self.gpu} | {self.workers} workers"


def process_memory_bytes() -> int:
    """Return current process RSS without adding a third-party dependency."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("page_fault_count", wintypes.DWORD),
                        ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
                        ("quota_peak_paged", ctypes.c_size_t), ("quota_paged", ctypes.c_size_t),
                        ("quota_peak_nonpaged", ctypes.c_size_t), ("quota_nonpaged", ctypes.c_size_t),
                        ("pagefile_usage", ctypes.c_size_t), ("peak_pagefile_usage", ctypes.c_size_t)]
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return int(counters.working_set)
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value * (1024 if os.name != "nt" else 1))
    except (ImportError, AttributeError, OSError):
        return 0


def available_memory_bytes() -> int:
    """Return currently available physical memory, or zero if unavailable."""
    if os.name == "nt":
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.available_physical)
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        return int(page_size * available_pages)
    except (AttributeError, OSError, ValueError):
        return 0


def estimate_image_peak_bytes(path: Path) -> int:
    """Estimate peak RAM for decoding and transforming one image.

    File size is intentionally ignored: highly compressed photos and animated
    images can expand by orders of magnitude in memory.  The multiplier covers
    Pillow's source, RGBA, transform, and encoder buffers. Animated conversion
    currently retains processed frames until the destination is committed.
    """
    if path.suffix.lower() not in _IMAGE_EXTENSIONS or not path.is_file():
        return 0
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            frames = max(1, int(getattr(image, "n_frames", 1)))
    except (OSError, ValueError, TypeError):
        return 0
    decoded_frame = max(1, width) * max(1, height) * 4
    if frames > 1:
        return decoded_frame * frames * 2
    return decoded_frame * 6


def estimate_batch_peak_bytes(paths: Sequence[Path]) -> int:
    """Return the largest estimated per-job working set in a batch."""
    return max((estimate_image_peak_bytes(path) for path in paths), default=0)


def memory_risk_is_high(estimated: int, available: int) -> bool:
    """Whether one job could consume an unsafe share of currently free RAM."""
    return bool(
        available > 0
        and estimated > max(512 * 1024**2, int(available * 0.70))
    )


def recommend_workers(
    paths: Sequence[Path],
    cpu_count: int | None = None,
    available_memory: int | None = None,
) -> int:
    """Choose a conservative worker count from CPU, RAM, media, and input size."""
    cpu = max(1, cpu_count or (os.cpu_count() or 1))
    suffixes = {path.suffix.lower() for path in paths}
    total_bytes = 0
    for path in paths:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    workers = min(cpu, 4)
    if suffixes & _VIDEO_EXTENSIONS:
        # One video at a time avoids exhausting low-end GPU memory and the
        # encoder-session limits found on older consumer cards.
        workers = 1
    elif suffixes and suffixes <= _AUDIO_EXTENSIONS:
        workers = min(workers, 2)
    elif total_bytes >= 512 * 1024 * 1024:
        workers = min(workers, 2)
    elif total_bytes >= 128 * 1024 * 1024:
        workers = min(workers, 3)

    memory = available_memory_bytes() if available_memory is None else max(0, available_memory)
    if memory:
        if memory < 2 * 1024**3:
            workers = 1
        elif memory < 4 * 1024**3:
            workers = min(workers, 2)
        elif memory < 8 * 1024**3:
            workers = min(workers, 3)

        image_peak = estimate_batch_peak_bytes(paths)
        if image_peak:
            # Keep half of currently available RAM free for the application,
            # OS, codec libraries, and short-lived allocations.
            memory_workers = max(1, int((memory * 0.5) // image_peak))
            workers = min(workers, memory_workers)

    override = os.environ.get("SHADOW_MAX_WORKERS", "").strip()
    if override:
        try:
            workers = min(workers, max(1, int(override)))
        except ValueError:
            pass
    return max(1, workers)


class BatchTelemetry:
    def __init__(self, total: int, workers: int, gpu: str = "GPU: unavailable") -> None:
        self.total = total
        self.workers = workers
        self.gpu = gpu
        self.started = time.perf_counter()

    def snapshot(self, completed: int) -> TelemetrySnapshot:
        elapsed = max(0.0, time.perf_counter() - self.started)
        throughput = completed / elapsed if elapsed > 0 else 0.0
        remaining = max(0, self.total - completed)
        eta = remaining / throughput if throughput > 0 and remaining else None
        return TelemetrySnapshot(
            completed, self.total, elapsed, throughput, eta,
            process_memory_bytes(), self.workers, self.gpu,
        )
