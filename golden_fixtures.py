"""Golden-image visual regression fixtures.

Generates reference images (golden images) for every supported codec
and compares future outputs against them.  This catches silent quality
regressions introduced by Pillow upgrades, encoder changes, or
pipeline bugs.

Usage in tests::

    from golden_fixtures import GoldenFixtureRunner
    runner = GoldenFixtureRunner()
    runner.generate_all()           # once, to create baselines
    results = runner.verify_all()   # in CI, to check for regressions
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from converter import convert_image, normalize_output_format, IMAGE_OUTPUT_FORMATS
from metrics import block_ssim, psnr as block_psnr
from settings import get_app_data_dir

# Minimum SSIM for a golden comparison to pass (very high — regressions
# should be caught by tiny drifts)
GOLDEN_SSIM_THRESHOLD = 0.98
GOLDEN_PSNR_THRESHOLD = 30.0  # dB


@dataclass
class GoldenResult:
    codec: str
    passed: bool
    ssim: float
    psnr: float
    golden_size: int
    current_size: int
    message: str = ""

    @property
    def size_delta_pct(self) -> float:
        if self.golden_size == 0:
            return 0
        return ((self.current_size - self.golden_size) / self.golden_size) * 100


@dataclass
class GoldenFixtureRunner:
    """Generate and verify golden-image fixtures."""

    fixtures_dir: Path = field(default_factory=lambda: _default_fixtures_dir())
    source_size: tuple[int, int] = (256, 256)
    quality: int = 80

    def _test_image(self) -> Image.Image:
        """Create a deterministic test image with gradients and patterns."""
        import struct
        w, h = self.source_size
        img = Image.new("RGBA", (w, h))
        pixels = []
        for y in range(h):
            for x in range(w):
                r = int(255 * x / w)
                g = int(255 * y / h)
                b = int(255 * ((x + y) % w) / w)
                a = 255 if (x + y) % 8 != 0 else 200
                pixels.append((r, g, b, a))
        img.putdata(pixels)
        return img

    def _codecs_to_test(self) -> list[tuple[str, str]]:
        """Return (format_key, extension) pairs for all testable codecs."""
        codecs = []
        for fmt_key, info in IMAGE_OUTPUT_FORMATS.items():
            ext = info[0] if isinstance(info, (list, tuple)) else f".{fmt_key.lower()}"
            # Skip codecs that need external libs if not installed
            codecs.append((fmt_key, ext))
        return codecs

    def generate_all(self) -> dict[str, Path]:
        """Generate golden reference images for all codecs."""
        self.fixtures_dir.mkdir(parents=True, exist_ok=True)
        source_img = self._test_image()
        source_path = self.fixtures_dir / "source.png"
        source_img.save(str(source_path))

        manifest: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_size": list(self.source_size),
            "quality": self.quality,
            "codecs": {},
        }

        results: dict[str, Path] = {}
        for fmt_key, ext in self._codecs_to_test():
            golden_dir = self.fixtures_dir / "golden"
            golden_dir.mkdir(exist_ok=True)
            try:
                result = convert_image(
                    source_path,
                    golden_dir,
                    target_format=normalize_output_format(fmt_key),
                    quality=self.quality,
                )
                if result.output_path and result.output_path.is_file():
                    # Rename to a stable golden name
                    golden_path = golden_dir / f"golden_{fmt_key.lower()}{ext}"
                    if golden_path != result.output_path:
                        if golden_path.exists():
                            golden_path.unlink()
                        result.output_path.rename(golden_path)
                    results[fmt_key] = golden_path
                    manifest["codecs"][fmt_key] = {
                        "file": golden_path.name,
                        "size": golden_path.stat().st_size,
                        "hash": _file_hash(golden_path),
                    }
            except Exception as e:
                manifest["codecs"][fmt_key] = {"error": str(e)}

        manifest_path = self.fixtures_dir / "golden_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), "utf-8")
        return results

    def verify_all(self) -> list[GoldenResult]:
        """Re-convert and compare against golden images."""
        source_path = self.fixtures_dir / "source.png"
        if not source_path.is_file():
            raise FileNotFoundError(
                f"No source image at {source_path}. Run generate_all() first."
            )

        manifest_path = self.fixtures_dir / "golden_manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text("utf-8"))

        verify_dir = self.fixtures_dir / "verify"
        verify_dir.mkdir(exist_ok=True)

        results: list[GoldenResult] = []
        for fmt_key, ext in self._codecs_to_test():
            golden_path = self.fixtures_dir / "golden" / f"golden_{fmt_key.lower()}{ext}"
            if not golden_path.is_file():
                results.append(GoldenResult(
                    fmt_key, False, 0.0, 0.0, 0, 0,
                    f"No golden image found for {fmt_key}",
                ))
                continue

            try:
                result = convert_image(
                    source_path,
                    verify_dir,
                    target_format=normalize_output_format(fmt_key),
                    quality=self.quality,
                )
                if not result.output_path or not result.output_path.is_file():
                    results.append(GoldenResult(
                        fmt_key, False, 0.0, 0.0,
                        golden_path.stat().st_size, 0,
                        f"Conversion failed for {fmt_key}",
                    ))
                    continue

                # Compare
                with Image.open(golden_path) as opened_golden:
                    golden_img = opened_golden.convert("RGB")
                with Image.open(result.output_path) as opened_current:
                    current_img = opened_current.convert("RGB")
                if golden_img.size != current_img.size:
                    current_img = current_img.resize(golden_img.size, Image.LANCZOS)

                ssim = block_ssim(golden_img, current_img)
                psnr = block_psnr(golden_img, current_img)
                golden_size = golden_path.stat().st_size
                current_size = result.output_path.stat().st_size
                passed = ssim >= GOLDEN_SSIM_THRESHOLD and psnr >= GOLDEN_PSNR_THRESHOLD

                msg = ""
                if not passed:
                    reasons = []
                    if ssim < GOLDEN_SSIM_THRESHOLD:
                        reasons.append(f"SSIM {ssim:.4f} < {GOLDEN_SSIM_THRESHOLD}")
                    if psnr < GOLDEN_PSNR_THRESHOLD:
                        reasons.append(f"PSNR {psnr:.1f} < {GOLDEN_PSNR_THRESHOLD}")
                    msg = f"REGRESSION: {'; '.join(reasons)}"

                results.append(GoldenResult(
                    fmt_key, passed, ssim, psnr,
                    golden_size, current_size, msg,
                ))

            except Exception as e:
                results.append(GoldenResult(
                    fmt_key, False, 0.0, 0.0,
                    golden_path.stat().st_size if golden_path.is_file() else 0,
                    0, f"Error: {e}",
                ))

        return results


def _default_fixtures_dir() -> Path:
    env = os.environ.get("SHADOW_GOLDEN_DIR")
    if env:
        return Path(env)
    return get_app_data_dir() / "golden_fixtures"


def _file_hash(path: Path) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(path.read_bytes())
    return h.hexdigest()
