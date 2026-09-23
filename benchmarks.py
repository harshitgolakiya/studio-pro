"""Performance benchmarks and release-to-release regression limits.

Measures conversion throughput, codec encoding speed, and metric
computation time, then compares against stored baselines to detect
performance regressions between releases.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from converter import convert_image, normalize_output_format
from metrics import block_ssim, psnr
from settings import get_app_data_dir

# Regression threshold: a benchmark must not regress more than this
# fraction compared to the stored baseline (e.g. 0.20 = 20% slower).
REGRESSION_THRESHOLD = 0.20


@dataclass
class BenchmarkResult:
    name: str
    duration_ms: float
    throughput: float = 0.0  # items/sec or pixels/sec depending on bench
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0


@dataclass
class RegressionCheck:
    name: str
    current_ms: float
    baseline_ms: float
    delta_pct: float
    passed: bool
    message: str = ""


def _benchmarks_dir() -> Path:
    env = os.environ.get("SHADOW_BENCH_DIR")
    if env:
        return Path(env)
    return get_app_data_dir() / "benchmarks"


def _make_test_image(width: int = 512, height: int = 512) -> Image.Image:
    """Create a deterministic benchmark image."""
    img = Image.new("RGB", (width, height))
    pixels = []
    for y in range(height):
        for x in range(width):
            r = (x * 7 + y * 3) % 256
            g = (x * 3 + y * 7) % 256
            b = (x * 5 + y * 5) % 256
            pixels.append((r, g, b))
    img.putdata(pixels)
    return img


def bench_conversion(fmt: str = "WEBP", quality: int = 80,
                     image_size: tuple[int, int] = (512, 512),
                     iterations: int = 5) -> BenchmarkResult:
    """Benchmark a single format conversion."""
    import tempfile
    img = _make_test_image(*image_size)

    with tempfile.TemporaryDirectory(prefix="shadow_bench_") as td:
        src = Path(td) / "bench_source.png"
        img.save(str(src))

        times: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            convert_image(src, Path(td), target_format=normalize_output_format(fmt), quality=quality)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        avg_ms = sum(times) / len(times)
        pixels = image_size[0] * image_size[1]
        throughput = pixels / (avg_ms / 1000) if avg_ms > 0 else 0

        return BenchmarkResult(
            name=f"convert_{fmt.lower()}_{image_size[0]}x{image_size[1]}",
            duration_ms=avg_ms,
            throughput=throughput,
            metadata={
                "format": fmt,
                "quality": quality,
                "image_size": list(image_size),
                "iterations": iterations,
                "times_ms": times,
                "min_ms": min(times),
                "max_ms": max(times),
            },
        )


def bench_ssim(image_size: tuple[int, int] = (512, 512),
               iterations: int = 10) -> BenchmarkResult:
    """Benchmark SSIM computation."""
    img_a = _make_test_image(*image_size)
    img_b = img_a.copy()
    # Introduce slight difference
    pixels = list(img_b.getdata())
    for i in range(0, len(pixels), 10):
        r, g, b = pixels[i]
        pixels[i] = (min(r + 5, 255), g, b)
    img_b.putdata(pixels)

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        block_ssim(img_a, img_b)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    avg_ms = sum(times) / len(times)
    return BenchmarkResult(
        name=f"ssim_{image_size[0]}x{image_size[1]}",
        duration_ms=avg_ms,
        metadata={"image_size": list(image_size), "iterations": iterations, "times_ms": times},
    )


def bench_psnr(image_size: tuple[int, int] = (512, 512),
               iterations: int = 10) -> BenchmarkResult:
    """Benchmark PSNR computation."""
    img_a = _make_test_image(*image_size)
    img_b = img_a.copy()

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        psnr(img_a, img_b)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    avg_ms = sum(times) / len(times)
    return BenchmarkResult(
        name=f"psnr_{image_size[0]}x{image_size[1]}",
        duration_ms=avg_ms,
        metadata={"image_size": list(image_size), "iterations": iterations, "times_ms": times},
    )


def run_all_benchmarks(image_size: tuple[int, int] = (256, 256),
                       iterations: int = 3) -> list[BenchmarkResult]:
    """Run the full benchmark suite."""
    results: list[BenchmarkResult] = []

    for fmt in ("WEBP", "JPEG", "PNG"):
        try:
            results.append(bench_conversion(fmt, image_size=image_size, iterations=iterations))
        except Exception:
            pass

    results.append(bench_ssim(image_size=image_size, iterations=iterations))
    results.append(bench_psnr(image_size=image_size, iterations=iterations))

    return results


def save_baseline(results: list[BenchmarkResult], label: str = "") -> Path:
    """Save benchmark results as a baseline."""
    bench_dir = _benchmarks_dir()
    bench_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"baseline_{label}_{ts}.json" if label else f"baseline_{ts}.json"
    path = bench_dir / name

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "results": {r.name: {"duration_ms": r.duration_ms, "metadata": r.metadata} for r in results},
    }
    path.write_text(json.dumps(payload, indent=2), "utf-8")

    # Also write/overwrite the "latest" file
    latest = bench_dir / "baseline_latest.json"
    latest.write_text(json.dumps(payload, indent=2), "utf-8")

    return path


def load_baseline(path: Path | None = None) -> dict[str, float]:
    """Load a baseline and return {name: duration_ms} mapping."""
    if path is None:
        path = _benchmarks_dir() / "baseline_latest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
        return {name: info["duration_ms"] for name, info in data.get("results", {}).items()}
    except (json.JSONDecodeError, OSError, KeyError):
        return {}


def check_regressions(current: list[BenchmarkResult],
                      baseline: dict[str, float] | None = None,
                      threshold: float = REGRESSION_THRESHOLD) -> list[RegressionCheck]:
    """Compare current results against baseline and flag regressions."""
    if baseline is None:
        baseline = load_baseline()

    checks: list[RegressionCheck] = []
    for result in current:
        base_ms = baseline.get(result.name)
        if base_ms is None or base_ms <= 0:
            checks.append(RegressionCheck(
                result.name, result.duration_ms, 0.0, 0.0, True,
                "No baseline to compare against",
            ))
            continue

        delta_pct = (result.duration_ms - base_ms) / base_ms
        passed = delta_pct <= threshold

        msg = ""
        if not passed:
            msg = f"REGRESSION: {delta_pct*100:.1f}% slower (limit {threshold*100:.0f}%)"
        elif delta_pct < -0.05:
            msg = f"Improvement: {abs(delta_pct)*100:.1f}% faster"

        checks.append(RegressionCheck(
            result.name, result.duration_ms, base_ms, delta_pct * 100, passed, msg,
        ))

    return checks
