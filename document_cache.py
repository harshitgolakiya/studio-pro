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
_profiles = {}
_warm_started = False


def _profile(folder):
    # One profile per app process/cache root. Preview work uses _lock, while
    # exporters retain their isolated profiles and other app instances get
    # different temporary directories.
    key=str(folder.resolve())
    if key not in _profiles or not Path(_profiles[key].name).exists():
        _profiles[key]=tempfile.TemporaryDirectory(prefix='preview-engine-',dir=folder)
    return Path(_profiles[key].name)/'profile'


def warm_preview_runtime(cancel_check=None):
    """Initialize the preview-only Office profile before the first document."""
    global _warm_started
    if _warm_started:return
    _warm_started=True
    def worker():
        try:
            check_cancel(cancel_check)
            from studio_runtime import find_libreoffice
            if not find_libreoffice() or not _lock.acquire(blocking=False):return
            try:
                folder=get_app_data_dir()/'document-previews';folder.mkdir(parents=True,exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='warmup-',dir=folder) as td:
                    source=Path(td)/'warmup.fodt'
                    source.write_text('<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2" office:mimetype="application/vnd.oasis.opendocument.text"><office:body><office:text><text:p>Shadow preview</text:p></office:text></office:body></office:document>',encoding='utf-8')
                    render_office(source,Path(td)/'warmup.pdf','PDF',cancel_check,profile_directory=_profile(folder))
            finally:_lock.release()
        except Exception:
            # Warming is optional; normal preview still reports real errors.
            import logging
            logging.getLogger(__name__).debug('Preview warmup skipped',exc_info=True)
    threading.Thread(target=worker,daemon=True,name='Shadow-preview-warmup').start()


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
            render_office(source, temporary, 'PDF', cancel_check,profile_directory=_profile(folder))
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
