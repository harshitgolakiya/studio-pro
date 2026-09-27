"""Thread-safe delivery of background results to a Tk window."""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from collections.abc import Callable


class TkEventBridge:
    """Queue worker callbacks and execute them from Tk's owning thread."""

    def __init__(self, root: tk.Misc, interval_ms: int = 40) -> None:
        self._root = root
        self._interval_ms = interval_ms
        self._events: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._closed = False
        self._after_id: str | None = root.after(interval_ms, self._drain)

    def post(self, callback: Callable[[], None]) -> bool:
        if self._closed:
            return False
        if threading.current_thread() is threading.main_thread():
            callback()
        else:
            self._events.put(callback)
        return True

    def _drain(self) -> None:
        self._after_id = None
        if self._closed:
            return
        while True:
            try:
                callback = self._events.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                reporter = getattr(self._root, "report_callback_exception", None)
                if reporter is not None:
                    reporter(*sys.exc_info())
        if not self._closed:
            self._after_id = self._root.after(self._interval_ms, self._drain)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except (tk.TclError, RuntimeError):
                pass
            self._after_id = None
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                break
