"""Local engine discovery and cancellable subprocess execution."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from typing import Callable


class StudioCancelled(Exception):
    pass


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


_model_seed_lock = threading.Lock()


def model_directory() -> Path:
    override = os.environ.get("SHADOW_MODEL_DIR")
    if override:
        return Path(override)
    bundled = resource_root() / "vendor" / "models"
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return bundled
    # Downloaded weights must not change a signed or read-only .app bundle.
    directory = Path.home() / "Library" / "Application Support" / "Shadow" / "models"
    marker = directory / ".bundled-defaults-ready"
    with _model_seed_lock:
        if not marker.is_file():
            directory.mkdir(parents=True, exist_ok=True)
            if bundled.is_dir():
                for source in bundled.rglob("*"):
                    if not source.is_file():
                        continue
                    target = directory / source.relative_to(bundled)
                    if target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".shadow-seed-", delete=False) as stream:
                        temporary = Path(stream.name)
                    try:
                        shutil.copy2(source, temporary)
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
            marker.touch()
    return directory


def find_libreoffice() -> str | None:
    override = os.environ.get("SHADOW_LIBREOFFICE")
    candidates = [Path(override)] if override else []
    for base in (resource_root(), Path(__file__).resolve().parent):
        candidates.extend(base / "vendor" / "libreoffice" / "program" / name
                          for name in ("soffice.com", "soffice.exe", "soffice"))
        candidates.append(base / "vendor" / "libreoffice" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice")
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        if os.environ.get(env):
            candidates.extend(Path(os.environ[env]) / "LibreOffice" / "program" / name
                              for name in ("soffice.com", "soffice.exe"))
    candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return shutil.which("soffice") or shutil.which("libreoffice")


def check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check and cancel_check():
        raise StudioCancelled("Cancelled")


class StagedOutput:
    """A temporary file beside its destination, published atomically on success."""

    def __init__(self, destination: Path, overwrite: bool = False):
        self.destination = destination
        self.overwrite = overwrite
        self.output: Path | None = None
        self._reservations: set[Path] = set()

    def __enter__(self) -> "StagedOutput":
        from utils import reserve_output_path
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self._reserved = reserve_output_path(self.destination, self.overwrite, self._reservations)
        self._directory = tempfile.TemporaryDirectory(dir=self.destination.parent, prefix=".shadow-stage-")
        self.path = Path(self._directory.name) / ("result" + self.destination.suffix)
        return self

    def __exit__(self, kind, error, traceback) -> None:
        from utils import publish_output_file, release_output_path
        try:
            if kind is None:
                if not self.path.is_file():
                    raise RuntimeError("The operation produced no output")
                self.output = publish_output_file(self.path, self._reserved, self.overwrite, self._reservations)
        finally:
            self._directory.cleanup()
            release_output_path(self._reserved, self._reservations)


def run_engine(args: list[str], timeout: float = 180,
               cancel_check: Callable[[], bool] | None = None) -> str:
    """Drain output to disk, cap diagnostics, and terminate the owned process tree."""
    check_cancel(cancel_check)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags, start_new_session=sys.platform != "win32")
        started = time.monotonic()
        try:
            while process.poll() is None:
                check_cancel(cancel_check)
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"Engine timed out after {timeout:g} seconds")
                time.sleep(0.1)
            log.seek(0, 2)
            log.seek(max(0, log.tell() - 16000))
            diagnostic = log.read().decode("utf-8", errors="replace")
            if process.returncode:
                raise RuntimeError(f"Engine exited with code {process.returncode}: {diagnostic[-2000:]}")
            check_cancel(cancel_check)
            return diagnostic
        finally:
            if process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags, timeout=10, check=False)
                else:
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
