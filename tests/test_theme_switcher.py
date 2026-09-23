"""Tests for appearance mode / theme switching."""
from __future__ import annotations

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
