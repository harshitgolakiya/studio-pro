from pathlib import Path
import tempfile
import tkinter as tk
import unittest
import time
from unittest.mock import patch

import customtkinter as ctk
from studio_dialog import StudioToolsDialog
from ui_dispatch import cancel_widget_callbacks


class SpeechUiTests(unittest.TestCase):
    def make_dialog(self):
        root = ctk.CTk()
        root.withdraw()
        root.output_directory = tk.StringVar(master=root, value=tempfile.gettempdir())
        dialog = StudioToolsDialog(root)
        tabs = dialog.generate_speech.master.master
        tabs.set("Text to Audio")
        for _ in range(6):
            root.update()
            time.sleep(0.05)
        self.addCleanup(self.close_dialog, root, dialog)
        return root, dialog

    @staticmethod
    def close_dialog(root, dialog):
        dialog.destroy()
        cancel_widget_callbacks(root)
        root.destroy()

    def test_generate_stays_inside_short_window_at_display_scales(self):
        try:
            for scale in (1.0, 1.25, 1.5):
                with self.subTest(scale=scale):
                    ctk.set_widget_scaling(scale)
                    ctk.set_window_scaling(scale)
                    root, dialog = self.make_dialog()
                    dialog.minsize(0, 0)
                    dialog.geometry("740x480")
                    for _ in range(4):
                        root.update()
                        time.sleep(0.05)
                    button = dialog.generate_speech
                    tab = button.master
                    self.assertTrue(button.winfo_ismapped())
                    self.assertGreater(button.winfo_height(), 20)
                    self.assertGreaterEqual(button.winfo_rooty(), tab.winfo_rooty())
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), tab.winfo_rooty() + tab.winfo_height())
                    self.assertLessEqual(dialog.script.winfo_rooty() + dialog.script.winfo_height(), dialog.voice_menu.winfo_rooty())
                    self.assertLessEqual(dialog.play_audio.winfo_rooty() + dialog.play_audio.winfo_height(), tab.winfo_rooty() + tab.winfo_height())
                    self.doCleanups()
        finally:
            ctk.set_widget_scaling(1.0)
            ctk.set_window_scaling(1.0)

    def test_selected_installed_voice_is_used_for_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root_dir = Path(temp)
            voice = root_dir / "en_US-amy-medium.onnx"
            voice.touch()
            Path(str(voice) + ".json").write_text("{}")
            with patch("studio_dialog.available_voices", return_value=[voice]), patch("studio_dialog.default_voice", return_value=voice):
                _, dialog = self.make_dialog()
            choice = next(iter(dialog._voices))
            self.assertIn("Amy", choice)
            dialog._select_voice(choice)
            dialog.script.insert("1.0", "Hello from the installed voice.")
            with patch("studio_dialog.filedialog.asksaveasfilename", return_value=str(root_dir / "voice.wav")), patch.object(dialog, "_run", side_effect=lambda work: work(lambda _: None)), patch("studio_dialog.synthesize_speech") as synthesize:
                dialog.generate_speech.invoke()
            self.assertEqual(synthesize.call_args.args[1:3], (root_dir / "voice.wav", voice))

    def test_preview_uses_selected_voice_without_save_dialog(self):
        with tempfile.TemporaryDirectory() as temp:
            root_dir = Path(temp)
            _, dialog = self.make_dialog()
            dialog._voice = root_dir / 'selected.voice.json'
            dialog.script.insert('1.0', 'What wonderful news!')
            with patch('settings.get_app_data_dir', return_value=root_dir), patch('studio_dialog.filedialog.asksaveasfilename') as save, patch.object(dialog, '_run', side_effect=lambda work:work(lambda _:None)), patch('studio_dialog.synthesize_speech') as synthesize:
                dialog.preview_voice.invoke()
            save.assert_not_called()
            self.assertEqual(synthesize.call_args.args[:3], ('What wonderful news!', root_dir/'voice-previews'/'sample.wav', dialog._voice))
            self.assertTrue(synthesize.call_args.kwargs['overwrite'])
            self.assertTrue(dialog._auto_play_preview)


if __name__ == "__main__":
    unittest.main()
