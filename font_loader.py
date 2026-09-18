"""Loads the app's bundled fonts (Inter for body text, Outfit for headings)
as process-private GDI font resources on Windows.

CustomTkinter/Tk only resolve fonts by family name through the OS font
table -- a bundled .ttf sitting in assets/fonts/ does nothing on its own
unless it's registered with Windows first. AddFontResourceEx with
FR_PRIVATE makes the fonts available to this process only, needs no admin
rights or installer step, and is automatically released when the process
exits.

Must run before any CTkFont()/Tk widget is created, since font family
resolution happens at widget-creation time.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys

BODY_FONT = "Inter"
DISPLAY_FONT = "Outfit"

FR_PRIVATE = 0x10


def _fonts_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "assets" / "fonts"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "assets" / "fonts"


def load_bundled_fonts() -> bool:
    """Register the bundled Inter/Outfit .ttf files for this process only.

    Returns True if at least one font file was successfully registered.
    Safe to call on non-Windows platforms (no-op) or if the font files are
    missing (the app falls back to a system font via the theme default).
    """
    if sys.platform != "win32":
        return False

    fonts_dir = _fonts_dir()
    if not fonts_dir.is_dir():
        return False

    gdi32 = ctypes.windll.gdi32
    loaded_any = False
    for font_file in sorted(fonts_dir.glob("*.ttf")):
        try:
            result = gdi32.AddFontResourceExW(str(font_file), FR_PRIVATE, 0)
            if result > 0:
                loaded_any = True
        except Exception:
            continue
    return loaded_any
