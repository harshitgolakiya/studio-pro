"""Bounded local cache for rendered Office previews; sources are never modified."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from office_engine import render_office
from settings import get_app_data_dir
from studio_runtime import check_cancel

_lock = threading.Lock()
MAX_BYTES = 512 * 1024 * 1024


def cache_key(source):
    source = Path(source).resolve()
    stat = source.stat()
    return hashlib.sha256(f'v1|{source}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()


def preview_pdf(source, cancel_check=None, progress=None):
    source = Path(source)
    folder = get_app_data_dir() / 'document-previews'
    folder.mkdir(parents=True, exist_ok=True)
    key = cache_key(source)
    cached = folder / f'{key}.pdf'
    while not _lock.acquire(timeout=.1):check_cancel(cancel_check)
    try:
        check_cancel(cancel_check)
        if cached.is_file() and cached.stat().st_size:
            cached.touch()
            return cached.read_bytes(), True
        if progress:progress('Preparing document layout…')
        with tempfile.TemporaryDirectory(prefix='render-', dir=folder) as td:
            temporary = Path(td) / 'preview.pdf'
            render_office(source, temporary, 'PDF', cancel_check)
            check_cancel(cancel_check)
            # Do not cache a preview if the source changed while rendering.
            data = temporary.read_bytes()
            if cache_key(source) == key:temporary.replace(cached)
        entries = sorted(folder.glob('*.pdf'), key=lambda path:path.stat().st_mtime, reverse=True)
        total = 0
        for index, path in enumerate(entries):
            total += path.stat().st_size
            if index >= 24 or total > MAX_BYTES:path.unlink(missing_ok=True)
        return data, False
    finally:_lock.release()
