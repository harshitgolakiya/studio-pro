from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys

REQUIRED_PACKAGES: tuple[str, ...] = (
    "Pillow",
    "pillow-heif",
    "customtkinter",
    "yt-dlp",
)

REQUIRED_RUNTIME_TOOLS: tuple[str, ...] = (
    "ffmpeg",
    "ffprobe",
)


def _package_name_to_module(name: str) -> str:
    aliases = {
        "Pillow": "PIL",
        "customtkinter": "customtkinter",
        "yt-dlp": "yt_dlp",
        "pyinstaller": "PyInstaller",
    }
    return aliases.get(name, name.lower().replace("-", "_"))


def get_missing_packages() -> list[str]:
    # A frozen (PyInstaller) build is a self-contained bundle by definition --
    # there is no meaningful "missing package" state to detect or fix here,
    # and sys.executable is the packaged .exe itself, not a Python
    # interpreter. Treating it as one and shelling out to "install" packages
    # would just relaunch the whole app as a subprocess.
    if getattr(sys, "frozen", False):
        return []
    missing: list[str] = []
    for package in REQUIRED_PACKAGES:
        module_name = _package_name_to_module(package)
        if importlib.util.find_spec(module_name) is None:
            missing.append(package)
    return missing


def get_missing_runtime_tools() -> list[str]:
    """Return media tools that are neither bundled with the app nor available on PATH."""
    from media_engine import get_ffmpeg_path, get_ffprobe_path

    resolvers = {"ffmpeg": get_ffmpeg_path, "ffprobe": get_ffprobe_path}
    missing: list[str] = []
    for tool in REQUIRED_RUNTIME_TOOLS:
        resolver = resolvers.get(tool)
        found = resolver() if resolver else shutil.which(tool)
        if found is None:
            missing.append(tool)
    return missing


def get_setup_guidance_message() -> str:
    """Return a concise message explaining the missing setup items and the next action."""
    missing_packages = get_missing_packages()
    missing_tools = get_missing_runtime_tools()

    issues: list[str] = []
    if missing_packages:
        issues.append(
            "Python packages: " + ", ".join(missing_packages) + " (run: python -m pip install -r requirements.txt)"
        )
    if missing_tools:
        if sys.platform == "darwin":
            install_hint = "brew install ffmpeg"
        elif sys.platform == "win32":
            install_hint = "winget install Gyan.Dev.FFmpeg"
        else:
            install_hint = "install ffmpeg with your package manager"
        issues.append(
            "System tools: " + ", ".join(missing_tools)
            + f" (install FFmpeg and ffprobe from https://www.ffmpeg.org/download.html or {install_hint})"
        )

    if not issues:
        return "Everything looks ready for conversion."
    return "Setup required: " + "; ".join(issues)


def ensure_runtime_dependencies() -> list[str]:
    """Install missing runtime dependencies into the active environment.

    No-op in a frozen build -- see the guard in get_missing_packages(). This
    check is intentionally repeated here: this function is the one that
    actually shells out to `sys.executable -m pip install`, and it must never
    do that against a packaged .exe no matter how it gets called.
    """
    if getattr(sys, "frozen", False):
        return []
    missing = get_missing_packages()
    if not missing:
        return []

    install_targets = [pkg for pkg in missing]
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *install_targets],
        check=True,
    )
    return install_targets


def ensure_runtime_dependencies_noisy() -> list[str]:
    """Install missing dependencies while surfacing failures clearly."""
    try:
        return ensure_runtime_dependencies()
    except Exception as exc:  # pragma: no cover - bootstrapping path
        raise RuntimeError(
            "The app dependencies are missing. Please install them with: "
            "python -m pip install -r requirements.txt"
        ) from exc
