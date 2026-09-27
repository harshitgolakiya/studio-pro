"""Tests for appearance mode / theme switching."""
from __future__ import annotations

import ctypes
import sys
import tests._headless  # noqa: F401

import unittest
import time
import customtkinter as ctk
import main
from settings import load_settings, update_setting


class ThemeSwitcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.WebPCompressorApp._offer_queue_restore = lambda self: None
        cls.app = main.WebPCompressorApp()
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass

    def test_theme_switch_fast_and_accurate(self):
        # Switching between themes should be instantaneous (< 1.0s) and not hang
        for mode in ["Light", "Dark", "System", "Light", "Dark"]:
            t0 = time.perf_counter()
            self.app._apply_appearance_mode_change(mode)
            self.app.update()
            elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 1.5, f"Theme switch to {mode} was too slow ({elapsed:.3f}s)")
            self.assertIn(ctk.get_appearance_mode().lower(), ["light", "dark"])

        # Check settings persistence
        settings = load_settings()
        self.assertEqual(settings.get("theme"), "Dark")

    def test_table_theme_styling(self):
        # In Light mode, table background must be light and text dark
        self.app._apply_appearance_mode_change("Light")
        self.app.update()
        light_style = self.app.table_style.lookup("Treeview", "background")
        light_fg = self.app.table_style.lookup("Treeview", "foreground")
        self.assertEqual(light_style, "#ffffff")
        self.assertEqual(light_fg, "#14212b")

        # In Dark mode, table background must be dark and text light
        self.app._apply_appearance_mode_change("Dark")
        self.app.update()
        dark_style = self.app.table_style.lookup("Treeview", "background")
        dark_fg = self.app.table_style.lookup("Treeview", "foreground")
        self.assertEqual(dark_style, "#11161d")
        self.assertEqual(dark_fg, "#f4f7fa")

    def test_initial_window_is_positioned_on_screen(self):
        geometry = self.app.geometry()
        size, x_text, y_text = geometry.replace("-", "+-").split("+")[:3]
        width, height = (int(value) for value in size.split("x"))
        x, y = int(x_text), int(y_text)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        expected_width = min(1380, max(980, self.app.winfo_screenwidth() - 32))
        self.assertEqual((width, height), (expected_width, 760))
        self.assertLessEqual(
            x + round(self.app._apply_window_scaling(width)),
            round(self.app._apply_window_scaling(self.app.winfo_screenwidth())),
        )

    @unittest.skipUnless(sys.platform == "win32", "Windows DWM only")
    def test_native_frame_follows_light_and_dark_theme(self):
        client_hwnd = self.app.winfo_id()
        frame_hwnd = ctypes.windll.user32.GetParent(client_hwnd) or client_hwnd
        for mode, expected in (("Light", 0), ("Dark", 1)):
            with self.subTest(mode=mode):
                self.app._apply_appearance_mode_change(mode)
                actual = ctypes.c_int(-1)
                result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    frame_hwnd,
                    20,
                    ctypes.byref(actual),
                    ctypes.sizeof(actual),
                )
                self.assertEqual(result, 0)
                self.assertEqual(actual.value, expected)
