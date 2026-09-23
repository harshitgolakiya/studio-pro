"""Small dependency-free batch telemetry and worker tuning helpers."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Sequence


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


def recommend_workers(paths: Sequence[Path], cpu_count: int | None = None) -> int:
    """Choose a conservative worker count from CPU and input-size pressure."""
    cpu = max(1, cpu_count or (os.cpu_count() or 1))
    total_bytes = 0
    for path in paths:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    if total_bytes >= 512 * 1024 * 1024:
        return max(1, min(cpu, 2))
    if total_bytes >= 128 * 1024 * 1024:
        return max(1, min(cpu, 3))
    return max(1, min(cpu, 4))


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
