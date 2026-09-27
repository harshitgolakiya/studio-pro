"""Keyboard accessibility helpers for CustomTkinter controls.

CustomTkinter draws most interactive controls on canvases.  Those canvases
are not included in Tk's tab order by default, which makes an otherwise
functional interface mouse-only.  This module opts the interactive canvas
into focus traversal and supplies the keyboard behaviour users expect from
native controls.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk


_ACTIVATION_KEYS = ("<Return>", "<KP_Enter>", "<space>")


def _is_enabled(widget: tk.Misc) -> bool:
    try:
        return str(widget.cget("state")) != tk.DISABLED
    except (AttributeError, tk.TclError, ValueError):
        return True


def _activate(widget: tk.Misc) -> str:
    if not _is_enabled(widget):
        return "break"
    if isinstance(widget, ctk.CTkButton):
        widget.invoke()
    elif isinstance(widget, (ctk.CTkCheckBox, ctk.CTkSwitch)):
        widget.toggle()
    elif isinstance(widget, ctk.CTkRadioButton):
        widget.invoke()
    elif isinstance(widget, ctk.CTkOptionMenu):
        widget._clicked()  # CustomTkinter exposes no public open method.
    return "break"


def _adjust_slider(widget: ctk.CTkSlider, event: tk.Event) -> str:
    if not _is_enabled(widget):
        return "break"
    start = float(widget.cget("from_"))
    end = float(widget.cget("to"))
    steps = widget.cget("number_of_steps")
    step = abs(end - start) / float(steps or 20)
    if event.keysym == "Home":
        value = start
    elif event.keysym == "End":
        value = end
    else:
        direction = -1 if event.keysym in {"Left", "Down"} else 1
        value = float(widget.get()) + direction * step
    widget.set(value)
    command = getattr(widget, "_command", None)
    if command is not None:
        command(widget.get())
    return "break"


def _focus_canvas(widget: tk.Misc, action: Callable[[tk.Event], str] | None) -> None:
    canvas = getattr(widget, "_canvas", None)
    if canvas is None or getattr(widget, "_shadow_keyboard_enabled", False):
        return
    widget._shadow_keyboard_enabled = True
    canvas.configure(takefocus=1, highlightthickness=0)

    def focus_in(_event: tk.Event) -> None:
        canvas.configure(highlightthickness=2, highlightcolor="#16A394")

    def focus_out(_event: tk.Event) -> None:
        canvas.configure(highlightthickness=0)

    canvas.bind("<FocusIn>", focus_in, add=True)
    canvas.bind("<FocusOut>", focus_out, add=True)
    canvas.bind("<Button-1>", lambda _event: canvas.focus_set(), add=True)
    text_label = getattr(widget, "_text_label", None)
    if text_label is not None:
        text_label.bind("<Button-1>", lambda _event: canvas.focus_set(), add=True)
    if action is not None:
        for sequence in _ACTIVATION_KEYS:
            canvas.bind(sequence, action, add=True)


def enable_keyboard_navigation(root: tk.Misc) -> int:
    """Enable Tab, focus indication, and keyboard activation below *root*.

    Returns the number of newly enabled controls, which also makes the helper
    straightforward to verify in automated UI tests.
    """
    enabled = 0
    stack = [root]
    interactive = (
        ctk.CTkButton,
        ctk.CTkCheckBox,
        ctk.CTkSwitch,
        ctk.CTkRadioButton,
        ctk.CTkOptionMenu,
    )
    while stack:
        parent = stack.pop()
        stack.extend(parent.winfo_children())
        if isinstance(parent, interactive):
            already_enabled = getattr(parent, "_shadow_keyboard_enabled", False)
            _focus_canvas(parent, lambda event, item=parent: _activate(item))
            enabled += 0 if already_enabled else 1
        elif isinstance(parent, ctk.CTkSlider):
            already_enabled = getattr(parent, "_shadow_keyboard_enabled", False)
            _focus_canvas(parent, None)
            canvas = getattr(parent, "_canvas", None)
            if canvas is not None and not already_enabled:
                for sequence in ("<Left>", "<Right>", "<Up>", "<Down>", "<Home>", "<End>"):
                    canvas.bind(
                        sequence,
                        lambda event, item=parent: _adjust_slider(item, event),
                        add=True,
                    )
                enabled += 1
    return enabled
