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
import faulthandler, sys
faulthandler.dump_traceback_later(20, exit=True, file=sys.stderr)
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
    # The app's own dialogs, opened the way a user opens them: from a visible window.
    "D1 VISIBLE root + LicenseDialog": """
from license_dialog import LicenseDialog
root = ctk.CTk(); root.update()
d = LicenseDialog(root); d.update()
""",
    "D2 VISIBLE root + WatchFolderDialog": """
from watch_folder_dialog import WatchFolderDialog
root = ctk.CTk(); root.update()
d = WatchFolderDialog(root); d.update()
""",
    "D3 VISIBLE root + URLDownloaderDialog": """
from url_downloader_dialog import URLDownloaderDialog
root = ctk.CTk(); root.update()
d = URLDownloaderDialog(root); d.update()
""",
    "D4 VISIBLE root + VideoTrimmerDialog": """
from pathlib import Path
from video_trimmer_dialog import VideoTrimmerDialog
root = ctk.CTk(); root.update()
d = VideoTrimmerDialog(root, Path('missing.mp4')); d.update()
""",
    "D5 VISIBLE root + RecipeManagerDialog": """
from recipe_dialog import RecipeManagerDialog
root = ctk.CTk(); root.update()
d = RecipeManagerDialog(root, lambda: {}, lambda s: None); d.update()
""",
    "D6 VISIBLE root + HistoryDialog": """
from history_dialog import HistoryDialog
root = ctk.CTk(); root.update()
d = HistoryDialog(root, lambda s: None); d.update()
""",
    "D7 VISIBLE root + OptimizerDialog": """
from pathlib import Path
from optimizer_dialog import OptimizerDialog
root = ctk.CTk(); root.update()
d = OptimizerDialog(root, Path('missing.png'), lambda c, q: None); d.update()
""",
    "D8 VISIBLE root + ImagePreviewDialog": """
import tempfile
from pathlib import Path
from PIL import Image
from preview_modal import ImagePreviewDialog
p = Path(tempfile.mkdtemp()) / 'a.png'; Image.new('RGB', (40, 30), 'red').save(p)
root = ctk.CTk(); root.update()
d = ImagePreviewDialog(root, p); d.update()
""",
    "E1 full app window constructs and updates": """
import os
os.environ['SHADOW_NO_QUEUE_RESTORE'] = '1'
from main import WebPCompressorApp
app = WebPCompressorApp(); app.update()
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
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
            ok = "returned" in out.stdout
            status = "ok" if ok else f"ERROR rc={out.returncode}: {(out.stderr or '').strip().splitlines()[-1:]}"
        except subprocess.TimeoutExpired:
            status = "HUNG (no return from update within 30 s)"
            hung.append(name)
            out = None
        print(f"  {name:58s} -> {status}")
        if out is not None and "Timeout (" in (out.stderr or ""):
            hung.append(name)
            frames = [ln for ln in out.stderr.splitlines() if ln.strip().startswith("File ")]
            print("      STALLED at (innermost first):")
            for ln in frames[:9]:
                print("        " + ln.strip())
    print(f"\n{len(hung)} scenario(s) hung")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
