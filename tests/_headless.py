"""Imported by every test module that builds the app window.

A modal Tk dialog blocks forever when nobody is there to click it, which on
a CI runner means the job hangs until GitHub's 6-hour limit. This module
replaces every messagebox/filedialog entry point with a non-blocking stub
(answering "no"/cancel) and records the calls so tests can assert on them.
It also points the app's persistent files at temp locations so test runs
never touch the real app data.
"""
from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import sys
import tempfile
from tkinter import filedialog, messagebox

import unittest

# Watchdog: if one test is still running after this long, something is blocked
# (a Tk call that never returns, a modal we failed to stub). Dump every thread's
# stack and exit, so CI shows *where* instead of timing out silently. The
# slowest test takes ~20 s locally. Between tests the timer is re-armed at
# twice the limit so a stall in setUpClass/tearDownClass is caught too.
_WATCHDOG_SECONDS = int(os.environ.get("SHADOW_TEST_WATCHDOG_SECONDS", "150"))
faulthandler.enable()

if not getattr(unittest.TestCase, "_shadow_watchdog", False):
    _original_run = unittest.TestCase.run

    def _watched_run(self, result=None):
        faulthandler.dump_traceback_later(_WATCHDOG_SECONDS, exit=True, file=sys.stderr)
        try:
            return _original_run(self, result)
        finally:
            faulthandler.dump_traceback_later(_WATCHDOG_SECONDS * 2, exit=True, file=sys.stderr)

    unittest.TestCase.run = _watched_run
    unittest.TestCase._shadow_watchdog = True
    faulthandler.dump_traceback_later(_WATCHDOG_SECONDS * 2, exit=True, file=sys.stderr)

_TMP = Path(tempfile.gettempdir())
os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
os.environ.setdefault("SHADOW_HISTORY_FILE", str(_TMP / "shadow-test-history.jsonl"))
os.environ.setdefault("SHADOW_TEMP_REGISTRY", str(_TMP / "shadow-test-temp-registry.json"))

DIALOG_CALLS: list[tuple[str, tuple, dict]] = []


def _stub(name: str, result):
    def call(*args, **kwargs):
        DIALOG_CALLS.append((name, args, kwargs))
        return result

    call.__name__ = name
    return call


for _name, _result in (
    ("askyesno", False),
    ("askokcancel", False),
    ("askretrycancel", False),
    ("askyesnocancel", None),
    ("askquestion", "no"),
    ("showinfo", "ok"),
    ("showwarning", "ok"),
    ("showerror", "ok"),
):
    setattr(messagebox, _name, _stub(_name, _result))

for _name, _result in (
    ("askdirectory", ""),
    ("askopenfilename", ""),
    ("askopenfilenames", ()),
    ("asksaveasfilename", ""),
):
    setattr(filedialog, _name, _stub(_name, _result))
