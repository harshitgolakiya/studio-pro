from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SHADOW_NO_QUEUE_RESTORE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: E402,F401

import customtkinter as ctk

from accessibility import enable_keyboard_navigation


class KeyboardAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = ctk.CTk()
        cls.root.geometry("320x180+2000+2000")
        cls.root.update()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def test_button_is_tabbable_and_activates_with_keyboard(self) -> None:
        calls: list[str] = []
        button = ctk.CTkButton(self.root, text="Run", command=lambda: calls.append("run"))
        button.pack()
        self.assertEqual(enable_keyboard_navigation(self.root), 1)
        self.assertEqual(int(button._canvas.cget("takefocus")), 1)

        button._canvas.focus_force()
        self.root.update()
        self.assertEqual(int(button._canvas.cget("highlightthickness")), 2)
        button._canvas.event_generate("<Return>")
        self.root.update()
        self.assertEqual(calls, ["run"])
        self.assertEqual(enable_keyboard_navigation(self.root), 0)
        button.destroy()

    def test_checkbox_space_toggles_value(self) -> None:
        value = ctk.BooleanVar(value=False)
        checkbox = ctk.CTkCheckBox(self.root, text="Keep metadata", variable=value)
        checkbox.pack()
        enable_keyboard_navigation(checkbox)

        checkbox._canvas.focus_force()
        self.root.update()
        checkbox._canvas.event_generate("<space>")
        self.root.update()
        self.assertTrue(value.get())
        checkbox.destroy()

    def test_slider_arrow_key_changes_value(self) -> None:
        slider = ctk.CTkSlider(self.root, from_=0, to=100, number_of_steps=10)
        slider.set(50)
        slider.pack()
        enable_keyboard_navigation(slider)

        slider._canvas.focus_force()
        self.root.update()
        slider._canvas.event_generate("<Right>")
        self.root.update()
        self.assertEqual(slider.get(), 60)
        slider.destroy()


if __name__ == "__main__":
    unittest.main()
