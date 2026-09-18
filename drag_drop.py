"""Robust Windows drag-and-drop implementation for Tkinter / CustomTkinter applications.

Replaces the buggy windnd package which causes hard access violation (0xC0000005)
crashes on 64-bit Windows due to 32-bit pointer truncation in ctypes and calling
CallWindowProcW after freeing the drop handle.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Registry:
# _HOOKED_WINDOWS: {hwnd: (old_wndproc_ptr, c_wndproc_instance, widget)}
_HOOKED_WINDOWS: dict[int, tuple[int, Any, Any]] = {}
# _CALLBACKS: {hwnd: on_drop_files_callback}
_CALLBACKS: dict[int, Callable[[list[str]], None]] = {}

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    WM_DROPFILES = 0x0233
    WM_COPYDATA = 0x004A
    WM_COPYGLOBALDATA = 0x0049
    GWL_WNDPROC = -4
    GA_ROOT = 2
    MSGFLT_ALLOW = 1

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    if hasattr(user32, "GetWindowLongPtrW"):
        _GetWindowLongPtr = user32.GetWindowLongPtrW
        _SetWindowLongPtr = user32.SetWindowLongPtrW
    else:
        _GetWindowLongPtr = user32.GetWindowLongW
        _SetWindowLongPtr = user32.SetWindowLongW

    _GetWindowLongPtr.restype = ctypes.c_void_p
    _GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]

    _SetWindowLongPtr.restype = ctypes.c_void_p
    _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]

    shell32.DragAcceptFiles.restype = None
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [
        wintypes.WPARAM,
        wintypes.UINT,
        wintypes.LPWSTR,
        wintypes.UINT,
    ]

    shell32.DragFinish.restype = None
    shell32.DragFinish.argtypes = [wintypes.WPARAM]

    if hasattr(user32, "ChangeWindowMessageFilterEx"):
        user32.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
        user32.ChangeWindowMessageFilterEx.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]


def hook_dropfiles(widget: Any, on_drop_files: Callable[[list[str]], None]) -> bool:
    """Hook Windows drag-and-drop events for a Tk/CustomTkinter window.

    Ensures 64-bit safety, UIPI bypass, and non-blocking asynchronous dispatch
    to the Tkinter main loop.
    """
    if sys.platform != "win32":
        return False

    try:
        widget.update_idletasks()
    except Exception:
        pass

    try:
        child_hwnd = int(widget.winfo_id())
    except Exception as err:
        logger.warning("Could not get window handle for widget: %s", err)
        return False

    # Retrieve root toplevel window
    top_hwnd = user32.GetAncestor(child_hwnd, GA_ROOT) or user32.GetParent(child_hwnd) or child_hwnd

    hwnds_to_hook = {top_hwnd, child_hwnd}

    for hwnd in hwnds_to_hook:
        if not hwnd:
            continue

        _CALLBACKS[hwnd] = on_drop_files

        if hwnd in _HOOKED_WINDOWS:
            continue

        # Allow messages across integrity levels (prevents UIPI drag drop blocking)
        if hasattr(user32, "ChangeWindowMessageFilterEx"):
            for msg in (WM_DROPFILES, WM_COPYGLOBALDATA, WM_COPYDATA):
                try:
                    user32.ChangeWindowMessageFilterEx(hwnd, msg, MSGFLT_ALLOW, None)
                except Exception:
                    pass

        old_proc = _GetWindowLongPtr(hwnd, GWL_WNDPROC)
        if not old_proc:
            continue

        def make_wndproc(orig_proc: int):
            def wndproc(h: int, msg: int, wp: int, lp: int) -> int:
                if msg == WM_DROPFILES:
                    hdrop = wp
                    files: list[str] = []
                    try:
                        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                        for i in range(count):
                            length = shell32.DragQueryFileW(hdrop, i, None, 0)
                            buf = ctypes.create_unicode_buffer(length + 1)
                            shell32.DragQueryFileW(hdrop, i, buf, length + 1)
                            if buf.value:
                                files.append(buf.value)
                    finally:
                        try:
                            shell32.DragFinish(hdrop)
                        except Exception:
                            pass

                    cb = _CALLBACKS.get(h)
                    if cb and files:
                        try:
                            # Schedule on the Tkinter main event loop
                            widget.after(0, lambda f=files, callback=cb: callback(f))
                        except Exception as post_err:
                            logger.error("Failed scheduling drop callback: %s", post_err)
                    return 0

                return user32.CallWindowProcW(orig_proc, h, msg, wp, lp)

            return WNDPROC(wndproc)

        c_wndproc = make_wndproc(old_proc)
        _SetWindowLongPtr(hwnd, GWL_WNDPROC, c_wndproc)
        shell32.DragAcceptFiles(hwnd, True)

        _HOOKED_WINDOWS[hwnd] = (old_proc, c_wndproc, widget)

    return True


def unhook_dropfiles(widget: Any = None) -> None:
    """Restore original window procedures for hooked windows."""
    if sys.platform != "win32":
        return

    to_remove: list[int] = []
    for hwnd, (old_proc, _, hooked_widget) in _HOOKED_WINDOWS.items():
        if widget is None or hooked_widget == widget:
            try:
                shell32.DragAcceptFiles(hwnd, False)
                _SetWindowLongPtr(hwnd, GWL_WNDPROC, old_proc)
            except Exception:
                pass
            to_remove.append(hwnd)

    for hwnd in to_remove:
        _HOOKED_WINDOWS.pop(hwnd, None)
        _CALLBACKS.pop(hwnd, None)
