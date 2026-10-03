"""One wheel dispatcher per Tk root, with short, coalesced scroll transitions."""
import sys
import tkinter as tk
from tkinter import ttk
import weakref

import customtkinter as ctk

_OriginalScrollableFrame = ctk.CTkScrollableFrame


class SmoothScrollableFrame(_OriginalScrollableFrame):
    def __init__(self, *args, **kwargs):
        self._scroll_job = None
        self._scroll_target = None
        self._scroll_axis = 'y'
        super().__init__(*args, **kwargs)

    def bind_all(self, sequence=None, func=None, add=None):
        # CTk normally adds six global handlers for every frame, including
        # hidden tabs, and leaves those bindings behind when frames close.
        if sequence in {'<MouseWheel>', '<Button-4>', '<Button-5>'}:
            root = self._root()
            if not hasattr(root, '_shadow_scroll_frames'):
                root._shadow_scroll_frames = weakref.WeakSet()
                root._shadow_scroll_canvases = weakref.WeakKeyDictionary()
                for event in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                    root.bind_all(event, lambda e, r=root: _dispatch(r, e), add='+')
            root._shadow_scroll_frames.add(self)
            root._shadow_scroll_canvases[self._parent_canvas] = weakref.ref(self)
            return None
        if sequence and 'Shift_' in sequence:
            return None  # Shift is available in each wheel event's state.
        return super().bind_all(sequence, func, add)

    def scroll_wheel(self, event):
        axis = 'x' if getattr(event, 'state', 0) & 1 or self._orientation == 'horizontal' else 'y'
        if getattr(event, 'num', None) in (4, 5):
            distance = -60 if event.num == 4 else 60
        elif sys.platform.startswith('win'):
            distance = -event.delta / 120 * 60
        else:
            distance = -event.delta * 6
        distance *= self._get_widget_scaling()
        canvas = self._parent_canvas
        bounds = canvas.bbox('all')
        if not bounds:
            return
        extent = bounds[2 if axis == 'x' else 3]
        viewport = canvas.winfo_width() if axis == 'x' else canvas.winfo_height()
        if extent <= viewport:
            return
        view = canvas.xview if axis == 'x' else canvas.yview
        current = view()[0] * extent
        if self._scroll_target is None or self._scroll_axis != axis:
            self._scroll_target = current
        self._scroll_axis = axis
        self._scroll_target = max(0, min(extent - viewport, self._scroll_target + distance))
        if self._scroll_job is None:
            self._scroll_job = self.after(16, self._animate_scroll)

    def _animate_scroll(self):
        self._scroll_job = None
        canvas = self._parent_canvas
        bounds = canvas.bbox('all')
        if not bounds or self._scroll_target is None:
            return
        axis = self._scroll_axis
        extent = bounds[2 if axis == 'x' else 3]
        viewport = canvas.winfo_width() if axis == 'x' else canvas.winfo_height()
        target = max(0, min(max(0, extent - viewport), self._scroll_target))
        view = canvas.xview if axis == 'x' else canvas.yview
        move = canvas.xview_moveto if axis == 'x' else canvas.yview_moveto
        current = view()[0] * extent
        delta = target - current
        move((target if abs(delta) < 2 else current + delta * .45) / max(1, extent))
        if abs(delta) >= 2:
            self._scroll_job = self.after(16, self._animate_scroll)
        else:
            self._scroll_target = None

    def stop_scroll(self):
        if self._scroll_job is not None:
            self.after_cancel(self._scroll_job)
            self._scroll_job = None
        self._scroll_target = None

    def destroy(self):
        self.stop_scroll()
        from ui_dispatch import cancel_widget_callbacks
        cancel_widget_callbacks(self._parent_frame)
        root = self._root()
        if hasattr(root, '_shadow_scroll_frames'):
            root._shadow_scroll_frames.discard(self)
            root._shadow_scroll_canvases.pop(self._parent_canvas, None)
        super().destroy()


def _dispatch(root, event):
    widget = event.widget
    while widget is not None:
        # Text boxes, sliders and tables keep their own wheel behavior.
        if isinstance(widget, (ctk.CTkTextbox, ctk.CTkSlider, ttk.Treeview)):
            return None
        reference = root._shadow_scroll_canvases.get(widget)
        if reference is not None and reference() is not None:
            reference().scroll_wheel(event)
            return 'break'
        if widget in root._shadow_scroll_frames:
            widget.scroll_wheel(event)
            return 'break'
        widget = getattr(widget, 'master', None)
    return None


def install_scrolling():
    ctk.CTkScrollableFrame = SmoothScrollableFrame
