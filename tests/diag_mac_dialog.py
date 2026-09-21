"""Temporary macOS diagnostic (not collected by unittest: name isn't test_*).

Runs each scenario in its own subprocess with a timeout and reports which
ones never return from Tk's update(). Used once from a manual workflow to
find out why a dialog test stalls on the macOS runner.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

PRELUDE = """
import sys
sys.path.insert(0, '.')
import customtkinter as ctk
from format_browser import FormatBrowserDialog
from command_palette import CommandPalette, PaletteAction
OPTS = ['WEBP', 'PNG', 'JPEG', 'Video: MP4']
"""

SCENARIOS = {
    "A1 withdrawn root + browser, no-match query": """
root = ctk.CTk(); root.withdraw()
d = FormatBrowserDialog(root, OPTS, 'PNG', lambda l: None)
d.query.set('zzz'); d.update()
""",
    "A2 withdrawn root + browser, matching query": """
root = ctk.CTk(); root.withdraw()
d = FormatBrowserDialog(root, OPTS, 'PNG', lambda l: None)
d.query.set('png'); d.update()
""",
    "A3 withdrawn root + browser, no query, just update": """
root = ctk.CTk(); root.withdraw()
d = FormatBrowserDialog(root, OPTS, 'PNG', lambda l: None)
d.update()
""",
    "A4 withdrawn root + plain CTkToplevel": """
root = ctk.CTk(); root.withdraw()
d = ctk.CTkToplevel(root); d.transient(root); d.update()
""",
    "A5 withdrawn root + CTkToplevel with a scrollable frame": """
root = ctk.CTk(); root.withdraw()
d = ctk.CTkToplevel(root)
f = ctk.CTkScrollableFrame(d); f.pack(fill='both', expand=True)
ctk.CTkLabel(f, text='hello').pack(); d.update()
""",
    "B1 VISIBLE root + browser, no-match query": """
root = ctk.CTk(); root.update()
d = FormatBrowserDialog(root, OPTS, 'PNG', lambda l: None)
d.query.set('zzz'); d.update()
""",
    "B2 VISIBLE root + browser, matching query": """
root = ctk.CTk(); root.update()
d = FormatBrowserDialog(root, OPTS, 'PNG', lambda l: None)
d.query.set('png'); d.update()
""",
    "B3 VISIBLE root + browser, no-match, NO transient": """
root = ctk.CTk(); root.update()
d = FormatBrowserDialog(root, OPTS, 'PNG', lambda l: None)
d.transient(None) if False else None
d.query.set('zzz'); d.update_idletasks()
""",
    "C1 VISIBLE root + palette, no-match query": """
root = ctk.CTk(); root.update()
p = CommandPalette(root, [PaletteAction('Clear all', lambda: None)])
p.query.set('zzz'); p.update()
""",
    "C2 withdrawn root + palette, no-match query": """
root = ctk.CTk(); root.withdraw()
p = CommandPalette(root, [PaletteAction('Clear all', lambda: None)])
p.query.set('zzz'); p.update()
""",
}


def main() -> int:
    print(f"python {sys.version.split()[0]} on {sys.platform}")
    try:
        import tkinter

        print("Tk patchlevel:", tkinter.Tcl().eval("info patchlevel"))
    except Exception as exc:  # pragma: no cover
        print("Tk version unavailable:", exc)
    hung = []
    for name, body in SCENARIOS.items():
        code = PRELUDE + textwrap.dedent(body) + "\nprint('returned')\n"
        try:
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15)
            ok = "returned" in out.stdout
            status = "ok" if ok else f"ERROR rc={out.returncode}: {(out.stderr or '').strip().splitlines()[-1:]}"
        except subprocess.TimeoutExpired:
            status = "HUNG (no return from update within 15 s)"
            hung.append(name)
        print(f"  {name:58s} -> {status}")
    print(f"\n{len(hung)} scenario(s) hung")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
