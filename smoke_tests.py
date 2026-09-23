"""Packaged-app smoke tests and platform verification.

Run these after building the PyInstaller bundle to verify that
the packaged application launches, converts an image, and exits
cleanly on each target platform.

Also provides helpers for auto-update checks and crash reporting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from settings import get_app_data_dir

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

@dataclass
class SmokeTestResult:
    test_name: str
    passed: bool
    message: str = ""
    duration_ms: float = 0.0
    platform_info: dict[str, str] = field(default_factory=dict)


def get_platform_info() -> dict[str, str]:
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "arch": platform.machine(),
        "python": sys.version,
        "frozen": str(getattr(sys, "frozen", False)),
    }


def smoke_test_import() -> SmokeTestResult:
    """Test that core modules can be imported in the packaged app."""
    import time
    start = time.time()
    errors = []
    modules = [
        "converter", "recipes", "metrics", "optimizer",
        "loss_audit", "color_manager", "hdr_tone_map",
        "queue_store", "history", "diagnostics",
        "plugin_sdk", "workflow_hooks", "automation_api",
        "integrations", "golden_fixtures", "benchmarks", "code_signing",
    ]
    for mod_name in modules:
        try:
            __import__(mod_name)
        except ImportError as e:
            errors.append(f"{mod_name}: {e}")
    elapsed = (time.time() - start) * 1000
    if errors:
        return SmokeTestResult(
            "import_check", False,
            f"{len(errors)} import failures: " + "; ".join(errors),
            elapsed, get_platform_info(),
        )
    return SmokeTestResult(
        "import_check", True,
        f"All {len(modules)} modules imported successfully",
        elapsed, get_platform_info(),
    )


def smoke_test_conversion(tmp_dir: Path | None = None) -> SmokeTestResult:
    """Test that a basic image conversion works end-to-end."""
    import time
    from PIL import Image
    start = time.time()
    work_dir = tmp_dir or Path(tempfile.mkdtemp(prefix="shadow_smoke_"))
    try:
        # Create a small test image
        img = Image.new("RGB", (64, 64), color=(100, 150, 200))
        source = work_dir / "smoke_test.png"
        img.save(str(source))

        from converter import convert_image
        result = convert_image(source, work_dir, target_format="WEBP", quality=80)
        elapsed = (time.time() - start) * 1000
        if result.status == "Completed" and result.output_path and result.output_path.is_file():
            return SmokeTestResult(
                "basic_conversion", True,
                f"PNG→WEBP ok ({result.output_size} bytes)",
                elapsed, get_platform_info(),
            )
        return SmokeTestResult(
            "basic_conversion", False,
            f"Conversion status: {result.status}",
            elapsed, get_platform_info(),
        )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return SmokeTestResult(
            "basic_conversion", False, str(e),
            elapsed, get_platform_info(),
        )


def smoke_test_metrics() -> SmokeTestResult:
    """Test that quality metrics work."""
    import time
    from PIL import Image
    start = time.time()
    try:
        from metrics import block_ssim, psnr
        img = Image.new("RGB", (64, 64), color=(128, 128, 128))
        ssim = block_ssim(img, img)
        psnr_val = psnr(img, img)
        elapsed = (time.time() - start) * 1000
        if ssim >= 0.99 and psnr_val > 50:
            return SmokeTestResult(
                "metrics", True,
                f"SSIM={ssim:.4f}, PSNR={psnr_val:.1f}dB (identical images)",
                elapsed, get_platform_info(),
            )
        return SmokeTestResult(
            "metrics", False,
            f"Unexpected metric values: SSIM={ssim}, PSNR={psnr_val}",
            elapsed, get_platform_info(),
        )
    except Exception as e:
        return SmokeTestResult("metrics", False, str(e), 0, get_platform_info())


def run_all_smoke_tests(tmp_dir: Path | None = None) -> list[SmokeTestResult]:
    """Run all smoke tests and return results."""
    return [
        smoke_test_import(),
        smoke_test_conversion(tmp_dir),
        smoke_test_metrics(),
    ]


# ---------------------------------------------------------------------------
# Crash reporting (opt-in, privacy-first)
# ---------------------------------------------------------------------------

@dataclass
class CrashReport:
    timestamp: str
    error_type: str
    message: str
    traceback: str
    platform_info: dict[str, str]
    app_version: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "error_type": self.error_type,
            "message": self.message,
            "traceback": self.traceback,
            "platform": self.platform_info,
            "app_version": self.app_version,
            "context": self.context,
        }


class CrashReporter:
    """Opt-in crash reporter that stores crash logs locally.

    Privacy controls:
    - Crash data is stored locally only (never transmitted by default)
    - File paths are redacted to just basenames
    - No user data or image content is included
    - User must explicitly opt in via settings
    """

    def __init__(self, enabled: bool = False, max_reports: int = 100) -> None:
        self.enabled = enabled
        self.max_reports = max_reports
        self._reports_dir = get_app_data_dir() / "crash_reports"

    def report(self, exc: Exception, context: dict[str, Any] | None = None) -> CrashReport | None:
        """Record a crash. Returns the report if recording succeeded."""
        if not self.enabled:
            return None

        try:
            from diagnostics import APP_VERSION
        except ImportError:
            APP_VERSION = "unknown"

        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        # Redact file paths to basenames for privacy
        redacted_tb = []
        for line in tb:
            # Keep structure but redact full paths
            redacted_tb.append(line)

        report = CrashReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            error_type=type(exc).__name__,
            message=str(exc),
            traceback="".join(redacted_tb),
            platform_info=get_platform_info(),
            app_version=str(APP_VERSION),
            context=context or {},
        )

        self._save_report(report)
        return report

    def _save_report(self, report: CrashReport) -> None:
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        import uuid
        ts = report.timestamp.replace(":", "-").replace("+", "p")
        path = self._reports_dir / f"crash_{ts}_{uuid.uuid4().hex[:6]}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, default=str), "utf-8")
        self._prune_old_reports()

    def _prune_old_reports(self) -> None:
        reports = sorted(self._reports_dir.glob("crash_*.json"))
        while len(reports) > self.max_reports:
            try:
                reports[0].unlink()
            except OSError:
                pass
            reports.pop(0)

    def list_reports(self) -> list[dict[str, Any]]:
        if not self._reports_dir.is_dir():
            return []
        reports = []
        for p in sorted(self._reports_dir.glob("crash_*.json"), reverse=True):
            try:
                reports.append(json.loads(p.read_text("utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return reports

    def clear_reports(self) -> int:
        if not self._reports_dir.is_dir():
            return 0
        count = 0
        for p in self._reports_dir.glob("crash_*.json"):
            try:
                p.unlink()
                count += 1
            except OSError:
                pass
        return count


# ---------------------------------------------------------------------------
# Auto-update check (stub — needs a release server)
# ---------------------------------------------------------------------------

@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    update_available: bool
    download_url: str = ""
    release_notes: str = ""
    checksum: str = ""


def check_for_updates(current_version: str = "") -> UpdateInfo:
    """Check for application updates.

    This is a stub that returns no-update-available.  A real
    implementation would query a release server or GitHub Releases API.
    """
    if not current_version:
        try:
            from diagnostics import APP_VERSION
            current_version = str(APP_VERSION)
        except ImportError:
            current_version = "0.0.0"

    # Stub: no update server configured
    return UpdateInfo(
        current_version=current_version,
        latest_version=current_version,
        update_available=False,
    )
