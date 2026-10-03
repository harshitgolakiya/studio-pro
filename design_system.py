"""Shared visual tokens for every Shadow workspace and auxiliary window."""

BACKGROUND_LIGHT = '#F7F7FA'
BACKGROUND_DARK = '#141419'
SURFACE_LIGHT = '#FFFFFF'
SURFACE_DARK = '#1C1C23'
ELEVATED_LIGHT = '#EEEEF4'
ELEVATED_DARK = '#25252F'
ACCENT = '#7561D4'
ACCENT_HOVER = '#8975E4'
ACCENT_TEXT_LIGHT = '#6652C2'
ACCENT_TEXT_DARK = '#B9ADF3'
SELECTION_LIGHT = '#E2DDF3'
SELECTION_DARK = '#2B2639'
TEXT_LIGHT = '#282833'
TEXT_DARK = '#F0EFF6'
MUTED_LIGHT = '#777785'
MUTED_DARK = '#9493A3'
BORDER_LIGHT = '#DDDDE7'
BORDER_DARK = '#33333E'
DANGER_LIGHT = '#A74763'
DANGER_DARK = '#D98CA4'
DANGER_SURFACE_LIGHT = '#F7EAF0'
DANGER_SURFACE_DARK = '#35212B'
PRIMARY_TEXT = '#FFFFFF'

BACKGROUND = (BACKGROUND_LIGHT, BACKGROUND_DARK)
SURFACE = (SURFACE_LIGHT, SURFACE_DARK)
MUTED = (MUTED_LIGHT, MUTED_DARK)
BORDER = (BORDER_LIGHT, BORDER_DARK)
TEXT = (TEXT_LIGHT, TEXT_DARK)
SELECTION = (SELECTION_LIGHT, SELECTION_DARK)


def sync_window_chrome(window):
    """Keep native Windows title bars in the same palette as the client area."""
    import sys
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        import customtkinter as ctk
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        dark = ctk.get_appearance_mode().lower() == 'dark'
        mode = ctypes.c_int(int(dark))
        dwm = ctypes.windll.dwmapi
        for attribute in (20, 19):
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(mode), ctypes.sizeof(mode))
        for attribute, color in ((34, BORDER_DARK if dark else BORDER_LIGHT),
                                 (35, BACKGROUND_DARK if dark else BACKGROUND_LIGHT),
                                 (36, TEXT_DARK if dark else TEXT_LIGHT)):
            rgb = bytes.fromhex(color[1:])
            value = ctypes.c_uint(rgb[0] | rgb[1] << 8 | rgb[2] << 16)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except (OSError, AttributeError, RuntimeError):
        pass


def style_dialog(window, parent):
    """Apply native chrome and center newly mapped dialogs within the display."""
    def mapped(event):
        if event.widget is not window:
            return
        sync_window_chrome(window)
        if getattr(window, '_shadow_positioned', False):
            return
        window._shadow_positioned = True
        width, height = window.winfo_width(), window.winfo_height()
        screen_width, screen_height = window.winfo_screenwidth(), window.winfo_screenheight()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        x = max(8, min(x, screen_width - width - 8))
        y = max(32, min(y, screen_height - height - 48))
        window.geometry(f'+{x}+{y}')
    window.bind('<Map>', mapped, add='+')
