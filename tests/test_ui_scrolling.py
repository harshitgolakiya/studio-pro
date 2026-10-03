import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import customtkinter as ctk
from ui_scrolling import SmoothScrollableFrame, _dispatch


class ScrollingTests(unittest.TestCase):
    def setUp(self):
        self.root = ctk.CTk()
        self.root.geometry('360x220')
        self.addCleanup(self.close_root)

    def close_root(self):
        from ui_dispatch import cancel_widget_callbacks
        cancel_widget_callbacks(self.root)
        self.root.destroy()

    def pump(self, duration=.25):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.005)

    def test_global_binding_does_not_grow_and_closed_frames_are_removed(self):
        frame = SmoothScrollableFrame(self.root)
        binding = self.root.bind_all('<MouseWheel>')
        for _ in range(15):
            extra = SmoothScrollableFrame(self.root)
            self.assertEqual(self.root.bind_all('<MouseWheel>'), binding)
            extra.destroy()
        self.assertEqual(set(self.root._shadow_scroll_frames), {frame})

    def test_nested_panel_receives_wheel_and_textbox_keeps_own_scroll(self):
        outer = SmoothScrollableFrame(self.root)
        inner = SmoothScrollableFrame(outer)
        label = ctk.CTkLabel(inner, text='Nested content')
        with patch.object(inner, 'scroll_wheel') as inside, patch.object(outer, 'scroll_wheel') as outside:
            _dispatch(self.root, SimpleNamespace(widget=label))
            inside.assert_called_once()
            outside.assert_not_called()
            inside.reset_mock()
            textbox = ctk.CTkTextbox(inner)
            self.assertIsNone(_dispatch(self.root, SimpleNamespace(widget=textbox._textbox)))
            inside.assert_not_called()

    def test_scroll_moves_and_pending_animation_is_cancelled_at_destroy(self):
        frame = SmoothScrollableFrame(self.root)
        frame.pack(fill='both', expand=True)
        for number in range(30):
            ctk.CTkLabel(frame, text=f'Row {number}', height=28).pack()
        self.pump(.1)
        event = SimpleNamespace(delta=-120, state=0, num=None, widget=frame._parent_canvas)
        self.assertEqual(_dispatch(self.root, event), 'break')
        self.pump()
        self.assertGreater(frame._parent_canvas.yview()[0], 0)
        frame.scroll_wheel(event)
        timer = frame._scroll_job
        frame.destroy()
        self.assertNotIn(timer, self.root.tk.splitlist(self.root.tk.call('after', 'info')))
        self.assertNotIn(frame, self.root._shadow_scroll_frames)
