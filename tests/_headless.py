"""Imported by every test module that builds the app window.

A modal Tk dialog blocks forever when nobody is there to click it, which on
a CI runner means the job hangs until GitHub's 6-hour limit. This module
replaces every messagebox/filedialog entry point with a non-blocking stub
(answering "no"/cancel) and records the calls so tests can assert on them.
It also points the app's persistent files at temp locations so test runs
never touch the real app data.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
from tkinter import filedialog, messagebox

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
