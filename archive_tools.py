"""ZIP, 7z, and TAR archives with safe extraction, manifests, and delivery packages.

Extraction never writes outside the chosen folder: absolute paths, parent
references, drive letters, links, and device entries are refused, and total
size and entry counts are bounded so a crafted archive cannot fill the disk.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
from typing import Callable
import zipfile

from studio_runtime import StagedOutput, check_cancel
from utils import next_available_output_path

ARCHIVE_FORMATS = {"ZIP": ".zip", "7Z": ".7z", "TAR.GZ": ".tar.gz", "TAR.XZ": ".tar.xz", "TAR": ".tar"}
_TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz"}
MANIFEST_NAME = "MANIFEST.json"
CHECKSUM_NAME = "SHA256SUMS.txt"

DEFAULT_MAX_BYTES = 20 * 1024 ** 3
DEFAULT_MAX_ENTRIES = 100_000
_MAX_RATIO = 200  # uncompressed : compressed, above 100 MB


class UnsafeArchive(ValueError):
    """The archive holds an entry that would escape the extraction folder or exhaust it."""


def archive_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(_TAR_SUFFIXES):
        return "tar"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".7z"):
        return "7z"
    raise ValueError(f"Unsupported archive: {path.name}. Supported: ZIP, 7z, TAR, TAR.GZ, TAR.BZ2, TAR.XZ")


def _stem(path: Path) -> str:
    name = path.name
    for suffix in sorted(_TAR_SUFFIXES + (".zip", ".7z"), key=len, reverse=True):
        if name.lower().endswith(suffix):
            return name[:-len(suffix)] or "archive"
    return path.stem


def _safe_member(name: str) -> PurePosixPath:
    """Normalize an entry name or raise when it could leave the extraction folder."""
    normal = name.replace("\\", "/")
    parts = [part for part in normal.split("/") if part not in ("", ".")]
    if (normal.startswith("/") or not parts or ".." in parts or any(":" in part for part in parts)
            or any(part.rstrip(" .") != part for part in parts) or "\x00" in normal):
        raise UnsafeArchive(f"Unsafe path in archive: {name!r}")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if any(part.split(".")[0].lower() in reserved for part in parts):
        raise UnsafeArchive(f"Reserved device name in archive: {name!r}")
    return PurePosixPath(*parts)


def inspect_archive(source: Path, password: str | None = None) -> dict:
    """List entries and totals without extracting. ``problems`` names anything extraction would refuse."""
    kind = archive_kind(source)
    if not source.is_file():
        raise FileNotFoundError("The selected archive no longer exists")
    entries, problems, encrypted = [], [], False
    try:
        if kind == "zip":
            with zipfile.ZipFile(source) as archive:
                for info in archive.infolist():
                    mode = info.external_attr >> 16
                    link = stat.S_ISLNK(mode)
                    encrypted = encrypted or bool(info.flag_bits & 0x1)
                    entries.append({"name": info.filename, "size": info.file_size, "packed": info.compress_size,
                                    "directory": info.is_dir(), "link": link})
        elif kind == "tar":
            with tarfile.open(source) as archive:
                for member in archive:
                    entries.append({"name": member.name, "size": member.size if member.isfile() else 0, "packed": 0,
                                    "directory": member.isdir(),
                                    "link": not (member.isfile() or member.isdir())})
        else:
            import py7zr
            try:
                with py7zr.SevenZipFile(source, password=password or None) as archive:
                    encrypted = archive.needs_password()
                    for info in archive.list():
                        entries.append({"name": info.filename, "size": info.uncompressed or 0,
                                        "packed": info.compressed or 0, "directory": info.is_directory,
                                        "link": bool(getattr(info, "is_symlink", False))})
            except Exception as exc:
                # An encrypted file list fails to parse in several library-specific ways.
                raise ValueError(f"{source.name} could not be opened. It may be damaged, or its password is "
                                 f"missing or wrong. ({type(exc).__name__})")
    except (zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
        raise ValueError(f"{source.name} is damaged or is not a valid archive: {exc}")
    for entry in entries:
        if entry["link"]:
            problems.append(f"Link or special entry: {entry['name']}")
        try:
            _safe_member(entry["name"])
        except UnsafeArchive as exc:
            problems.append(str(exc))
    return {"kind": kind, "entries": entries, "files": sum(1 for e in entries if not e["directory"]),
            "total_bytes": sum(e["size"] for e in entries), "packed_bytes": source.stat().st_size,
            "encrypted": encrypted, "problems": problems}


def extract_archive(source: Path, output_dir: Path, password: str | None = None,
                    max_bytes: int = DEFAULT_MAX_BYTES, max_entries: int = DEFAULT_MAX_ENTRIES,
                    cancel_check: Callable[[], bool] | None = None,
                    progress: Callable[[str], None] | None = None) -> Path:
    """Extract into a new folder inside ``output_dir`` and return that folder."""
    report = inspect_archive(source, password)
    if report["problems"]:
        raise UnsafeArchive("This archive was not extracted. " + "; ".join(report["problems"][:5]))
    if len(report["entries"]) > max_entries:
        raise UnsafeArchive(f"This archive has more than {max_entries:,} entries")
    total = report["total_bytes"]
    if total > max_bytes:
        raise UnsafeArchive(f"This archive expands to {total / 1024 ** 3:.1f} GB, above the "
                            f"{max_bytes / 1024 ** 3:.0f} GB limit")
    if total > 100 * 1024 ** 2 and total > _MAX_RATIO * max(report["packed_bytes"], 1):
        raise UnsafeArchive("This archive expands far beyond its size and looks like a decompression bomb")
    if report["encrypted"] and not password:
        raise ValueError("This archive is password-protected. Enter its password.")
    output_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(output_dir).free
    if total > free:
        raise OSError(f"Not enough free space: {total / 1024 ** 2:.0f} MB needed, {free / 1024 ** 2:.0f} MB available")
    staging = Path(tempfile.mkdtemp(dir=output_dir, prefix=".shadow-extract-"))
    try:
        written = 0
        if report["kind"] == "zip":
            with zipfile.ZipFile(source) as archive:
                for number, info in enumerate(archive.infolist(), 1):
                    check_cancel(cancel_check)
                    target = staging.joinpath(*_safe_member(info.filename).parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if progress and number % 25 == 1:
                        progress(f"Extracting {number} of {len(report['entries'])}…")
                    try:
                        with archive.open(info, pwd=password.encode("utf-8") if password else None) as reader, \
                                target.open("wb") as writer:
                            # Count real bytes: a header can understate the size.
                            while chunk := reader.read(1024 * 1024):
                                written += len(chunk)
                                if written > max_bytes:
                                    raise UnsafeArchive("This archive expands beyond the size limit")
                                writer.write(chunk)
                                check_cancel(cancel_check)
                    except RuntimeError as exc:
                        raise ValueError(f"Wrong password or unsupported encryption: {exc}")
        elif report["kind"] == "tar":
            with tarfile.open(source) as archive:
                for number, member in enumerate(archive, 1):
                    check_cancel(cancel_check)
                    _safe_member(member.name)
                    if progress and number % 25 == 1:
                        progress(f"Extracting {number} of {len(report['entries'])}…")
                    written += member.size if member.isfile() else 0
                    if written > max_bytes:
                        raise UnsafeArchive("This archive expands beyond the size limit")
                    archive.extract(member, staging, filter="data")
        else:
            import py7zr
            if progress:
                progress("Extracting 7z archive…")
            with py7zr.SevenZipFile(source, password=password or None) as archive:
                try:
                    archive.extractall(staging)
                except Exception as exc:
                    raise ValueError(f"The archive could not be extracted. Check the password: {exc}")
        check_cancel(cancel_check)
        destination = next_available_output_path(output_dir / _stem(source))
        os.rename(staging, destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _collect(sources: list[Path]) -> list[tuple[Path, str]]:
    """Files to pack with their archive names; a folder keeps its own name as the top level."""
    items: dict[str, Path] = {}
    for source in sources:
        if source.is_dir():
            for path in sorted(source.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    items.setdefault(f"{source.name}/{path.relative_to(source).as_posix()}", path)
        elif source.is_file():
            name, counter = source.name, 1
            while name in items and items[name] != source:
                name = f"{source.stem}_{counter}{source.suffix}"
                counter += 1
            items[name] = source
        else:
            raise FileNotFoundError(f"Not found: {source}")
    if not items:
        raise ValueError("There are no files to archive")
    return [(path, name) for name, path in items.items()]


def sha256_file(path: Path, cancel_check: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            check_cancel(cancel_check)
    return digest.hexdigest()


def create_archive(sources: list[Path], destination: Path, password: str | None = None,
                   extra_files: dict[str, bytes] | None = None, overwrite: bool = False,
                   cancel_check: Callable[[], bool] | None = None,
                   progress: Callable[[str], None] | None = None) -> Path:
    """Pack files and folders. The format follows the destination extension (.zip, .7z, .tar.gz, .tar.xz, .tar)."""
    kind = archive_kind(destination)
    if password and kind != "7z":
        raise ValueError("Password protection is available for 7z archives (AES-256)")
    items = _collect(sources)
    if destination.resolve() in {path.resolve() for path, _ in items}:
        raise ValueError("The archive cannot be saved inside the files it contains")
    extra_files = extra_files or {}
    with StagedOutput(destination, overwrite) as stage:
        # StagedOutput names its temp file from the last suffix only; keep it.
        if kind == "zip":
            with zipfile.ZipFile(stage.path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for number, (path, name) in enumerate(items, 1):
                    check_cancel(cancel_check)
                    if progress and number % 25 == 1:
                        progress(f"Packing {number} of {len(items)}…")
                    archive.write(path, name)
                for name, data in extra_files.items():
                    archive.writestr(name, data)
        elif kind == "tar":
            lower = destination.name.lower()
            mode = "w:gz" if lower.endswith((".gz", ".tgz")) else "w:xz" if lower.endswith((".xz", ".txz")) \
                else "w:bz2" if lower.endswith((".bz2", ".tbz2")) else "w"
            with tarfile.open(stage.path, mode) as archive:
                for number, (path, name) in enumerate(items, 1):
                    check_cancel(cancel_check)
                    if progress and number % 25 == 1:
                        progress(f"Packing {number} of {len(items)}…")
                    archive.add(path, name, recursive=False)
                for name, data in extra_files.items():
                    import io
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mtime = int(datetime.now(timezone.utc).timestamp())
                    archive.addfile(info, io.BytesIO(data))
        else:
            import py7zr
            with py7zr.SevenZipFile(stage.path, "w", password=password or None) as archive:
                if password:
                    archive.set_encrypted_header(True)
                for number, (path, name) in enumerate(items, 1):
                    check_cancel(cancel_check)
                    if progress and number % 25 == 1:
                        progress(f"Packing {number} of {len(items)}…")
                    archive.write(path, name)
                for name, data in extra_files.items():
                    archive.writestr(data, name)
    return stage.output


# -- manifests -----------------------------------------------------------

def build_manifest(items: list[tuple[Path, str]], details: dict | None = None,
                   cancel_check: Callable[[], bool] | None = None,
                   progress: Callable[[str], None] | None = None) -> dict:
    files = []
    for number, (path, name) in enumerate(items, 1):
        check_cancel(cancel_check)
        if progress and number % 10 == 1:
            progress(f"Checksumming {number} of {len(items)}…")
        files.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path, cancel_check)})
    return {"manifest_version": 1, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **(details or {}), "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files),
            "files": files}


def checksum_lines(manifest: dict) -> str:
    """``sha256sum``-compatible listing."""
    return "".join(f"{entry['sha256']} *{entry['path']}\n" for entry in manifest["files"])


def write_folder_manifest(folder: Path, details: dict | None = None,
                          cancel_check: Callable[[], bool] | None = None,
                          progress: Callable[[str], None] | None = None) -> Path:
    """Write MANIFEST.json and SHA256SUMS.txt describing every file in ``folder``."""
    if not folder.is_dir():
        raise FileNotFoundError("Choose an existing folder")
    items = [(path, path.relative_to(folder).as_posix()) for path in sorted(folder.rglob("*"))
             if path.is_file() and not path.is_symlink() and path.name not in (MANIFEST_NAME, CHECKSUM_NAME)]
    if not items:
        raise ValueError("This folder has no files")
    manifest = build_manifest(items, details, cancel_check, progress)
    with StagedOutput(folder / MANIFEST_NAME, overwrite=True) as stage:
        stage.path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    with StagedOutput(folder / CHECKSUM_NAME, overwrite=True) as sums:
        sums.path.write_text(checksum_lines(manifest), encoding="utf-8")
    return stage.output


def verify_folder(folder: Path, cancel_check: Callable[[], bool] | None = None) -> dict:
    """Compare a folder with its MANIFEST.json. ``ok`` is True only when every file matches."""
    manifest_path = folder / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"No {MANIFEST_NAME} in this folder")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {entry["path"]: entry for entry in manifest["files"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{MANIFEST_NAME} is not readable: {exc}")
    missing, changed = [], []
    for name, entry in expected.items():
        path = folder.joinpath(*_safe_member(name).parts)
        if not path.is_file():
            missing.append(name)
        elif path.stat().st_size != entry["bytes"] or sha256_file(path, cancel_check) != entry["sha256"]:
            changed.append(name)
    present = {path.relative_to(folder).as_posix() for path in folder.rglob("*")
               if path.is_file() and path.name not in (MANIFEST_NAME, CHECKSUM_NAME)}
    extra = sorted(present - set(expected))
    return {"ok": not (missing or changed or extra), "checked": len(expected), "missing": missing,
            "changed": changed, "unlisted": extra}


# -- delivery packages ---------------------------------------------------

def build_delivery_package(sources: list[Path], destination: Path, client: str = "", project: str = "",
                           notes: str = "", prepared_by: str = "", password: str | None = None,
                           overwrite: bool = False, cancel_check: Callable[[], bool] | None = None,
                           progress: Callable[[str], None] | None = None) -> Path:
    """Pack deliverables with a manifest, checksums, and a README for the recipient."""
    items = _collect(sources)
    details = {key: value for key, value in (("client", client.strip()), ("project", project.strip()),
                                             ("prepared_by", prepared_by.strip()), ("notes", notes.strip())) if value}
    manifest = build_manifest(items, details, cancel_check, progress)
    readme = [f"Delivery package{' for ' + client.strip() if client.strip() else ''}",
              f"Project: {project.strip()}" if project.strip() else "",
              f"Prepared by: {prepared_by.strip()}" if prepared_by.strip() else "",
              f"Created: {manifest['created']}",
              f"Files: {manifest['file_count']} ({manifest['total_bytes']:,} bytes)", "",
              notes.strip(), "" if notes.strip() else None,
              f"{MANIFEST_NAME} lists every file with its size and SHA-256 checksum.",
              f"To verify on macOS/Linux: shasum -a 256 -c {CHECKSUM_NAME}",
              f"To verify on Windows: Get-FileHash <file> -Algorithm SHA256, and compare with {CHECKSUM_NAME}.", ""]
    extra = {MANIFEST_NAME: json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
             CHECKSUM_NAME: checksum_lines(manifest).encode("utf-8"),
             "README.txt": "\n".join(line for line in readme if line is not None).encode("utf-8")}
    clash = sorted(set(extra) & {name for _, name in items})
    if clash:
        raise ValueError(f"Rename these files before packaging; the package writes its own: {', '.join(clash)}")
    return create_archive(sources, destination, password, extra, overwrite, cancel_check, progress)


def verify_package(source: Path, password: str | None = None,
                   cancel_check: Callable[[], bool] | None = None) -> dict:
    """Check a delivery package against the manifest inside it, without keeping extracted files."""
    with tempfile.TemporaryDirectory(prefix="shadow-verify-") as td:
        folder = extract_archive(source, Path(td), password, cancel_check=cancel_check)
        report = verify_folder(folder, cancel_check)
        report["unlisted"] = [name for name in report["unlisted"] if name != "README.txt"]
        report["ok"] = not (report["missing"] or report["changed"] or report["unlisted"])
        return report
