import os
from pathlib import Path
import subprocess
import sys
import threading

_reserve_lock = threading.Lock()


def format_file_size(size_in_bytes: int | None) -> str:
    """Return a compact, human-readable file size."""
    if size_in_bytes is None:
        return "-"
    units = ("B", "KB", "MB", "GB")
    size = float(max(size_in_bytes, 0))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return "-"


def format_saved_percentage(original_size: int, output_size: int) -> str:
    if original_size <= 0:
        return "0.0%"
    percentage = ((original_size - output_size) / original_size) * 100
    if percentage < 0:
        return f"{abs(percentage):.1f}% larger"
    return f"{percentage:.1f}%"


def next_available_output_path(
    output_path: Path,
    overwrite: bool = False,
    reserved_paths: set[Path] | None = None,
) -> Path:
    """Return output_path or a numbered sibling when overwriting is disabled."""
    if reserved_paths is None:
        reserved_paths = set()
    if (overwrite and output_path not in reserved_paths) or (
        not output_path.exists() and output_path not in reserved_paths
    ):
        return output_path
    counter = 1
    while True:
        candidate = output_path.with_name(
            f"{output_path.stem}_{counter}{output_path.suffix}"
        )
        if candidate not in reserved_paths and (overwrite or not candidate.exists()):
            return candidate
        counter += 1


def reserve_output_path(
    output_path: Path,
    overwrite: bool = False,
    reserved_paths: set[Path] | None = None,
) -> Path:
    """Atomically compute and reserve the next available output path.

    Concurrent batch workers must not both compute the same "next available"
    path and then race to add it to ``reserved_paths`` -- that gap let two
    threads silently overwrite each other's output. This combines the
    lookup and reservation under a single lock.
    """
    with _reserve_lock:
        path = next_available_output_path(output_path, overwrite, reserved_paths)
        if reserved_paths is not None:
            reserved_paths.add(path)
        return path


def slugify_filename(name: str) -> str:
    """Convert filename to web-safe lowercase slug (e.g. 'My Image 2026' -> 'my-image-2026')."""
    import re

    p = Path(name)
    stem = p.stem.strip().lower()
    stem = re.sub(r"[\s_]+", "-", stem)
    stem = re.sub(r"[^a-z0-9\-]+", "", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    return f"{stem or 'file'}{p.suffix}"


def build_destination_filename(
    stem: str,
    ext: str,
    slugify: bool = False,
    prefix: str = "",
    suffix: str = "",
) -> str:
    """Build standardized output filename applying optional slugification, prefix, and suffix."""
    name = stem
    if slugify:
        p = slugify_filename(f"{name}.tmp")
        name = Path(p).stem
    if prefix:
        name = f"{prefix}{name}"
    if suffix:
        name = f"{name}{suffix}"
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{name}{ext}"


def scan_directory_for_images(
    directory: Path,
    supported_extensions: set[str],
    recursive: bool = True,
) -> list[Path]:
    """Find all supported images inside a directory, optionally recursive."""
    if not directory.is_dir():
        return []
    results: list[Path] = []
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    for path in iterator:
        if path.is_file() and path.suffix.lower() in supported_extensions:
            results.append(path.resolve())
    return sorted(results)


def open_file_or_folder(path: Path) -> None:
    """Open a file or directory with the system default application."""
    if not path.exists():
        return
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def reveal_in_file_manager(path: Path) -> None:
    """Reveal a file in Windows Explorer or macOS Finder."""
    if not path.exists():
        return
    if sys.platform == "win32":
        subprocess.run(["explorer", f"/select,{path.resolve()}"], check=False)
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)], check=False)
    else:
        open_file_or_folder(path.parent if path.is_file() else path)


def export_results_to_csv(results: list[object], destination_path: Path) -> Path:
    """Export batch conversion results to a structured CSV file."""
    import csv

    with open(destination_path, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "Filename",
            "Status",
            "Original Size (Bytes)",
            "Original Size",
            "Output Size (Bytes)",
            "Output Size",
            "Saved",
            "Width",
            "Height",
            "Source Path",
            "Output Path",
            "Error",
        ])
        for r in results:
            writer.writerow([
                getattr(r.source_path, "name", str(r.source_path)),
                getattr(r, "status", ""),
                getattr(r, "original_size", "") or "",
                getattr(r, "original_size_text", ""),
                getattr(r, "output_size", "") or "",
                getattr(r, "output_size_text", ""),
                getattr(r, "saved", ""),
                getattr(r, "width", "") or "",
                getattr(r, "height", "") or "",
                str(getattr(r, "source_path", "")),
                str(getattr(r, "output_path", "") or ""),
                getattr(r, "error", "") or "",
            ])
    return destination_path


def _ps_quote(value: str) -> str:
    """Escape a value for safe interpolation inside a single-quoted PowerShell string."""
    return "'" + value.replace("'", "''") + "'"


def copy_image_file_to_clipboard(file_path: Path) -> bool:
    """Copy image file to the system clipboard so it can be pasted as file or image."""
    if not file_path.exists():
        return False
    if sys.platform == "win32":
        try:
            cmd = f"Set-Clipboard -LiteralPath {_ps_quote(str(file_path.resolve()))}"
            creation_flags = (
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                check=False,
                creationflags=creation_flags,
            )
            return True
        except Exception:
            return False
    if sys.platform == "darwin":
        try:
            # AppleScript `set the clipboard to (read ... as ...)` puts the
            # actual image data on the pasteboard (pastable into Finder/Mail/
            # Preview), not just the file path as text.
            posix_path = str(file_path.resolve())
            file_class = "TIFF picture" if file_path.suffix.lower() != ".png" else "«class PNGf»"
            script = f'set the clipboard to (read (POSIX file "{posix_path}") as {file_class})'
            subprocess.run(["osascript", "-e", script], check=False)
            return True
        except Exception:
            return False
    return False


def copy_text_to_clipboard(text: str) -> None:
    """Copy text string to system clipboard."""
    if sys.platform == "win32":
        try:
            cmd = f"Set-Clipboard -Value {_ps_quote(text)}"
            creation_flags = (
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                check=False,
                creationflags=creation_flags,
            )
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            subprocess.run(["pbcopy"], input=text, text=True, check=False)
        except Exception:
            pass


def play_completion_sound() -> None:
    """Play a subtle system chime upon batch completion."""
    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            subprocess.run(
                ["afplay", "/System/Library/Sounds/Glass.aiff"], check=False
            )
        except Exception:
            pass


