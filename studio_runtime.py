"""Local engine discovery and cancellable subprocess execution."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable


class StudioCancelled(Exception):
    pass


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def model_directory() -> Path:
    return Path(os.environ.get("SHADOW_MODEL_DIR") or resource_root() / "vendor" / "models")


def find_libreoffice() -> str | None:
    override = os.environ.get("SHADOW_LIBREOFFICE")
    candidates = [Path(override)] if override else []
    for base in (resource_root(), Path(__file__).resolve().parent):
        candidates.extend(base / "vendor" / "libreoffice" / "program" / name
                          for name in ("soffice.com", "soffice.exe", "soffice"))
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
