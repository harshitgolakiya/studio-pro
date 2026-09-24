import unittest
from unittest.mock import patch
from pathlib import Path
import customtkinter as ctk

from main import WebPCompressorApp
from video_trimmer_dialog import VideoTrimmerDialog


class TestMediaContextVisibility(unittest.TestCase):
    def setUp(self):
        self.app = WebPCompressorApp()
        self.app.withdraw()

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_image_category_visibility(self):
        self.app._update_category_controls_visibility("image")
        self.assertEqual(self.app.size_row.winfo_manager(), "pack")
        self.assertEqual(self.app.ssim_row.winfo_manager(), "pack")
        self.assertEqual(self.app.video_options_row.winfo_manager(), "")
        self.assertEqual(self.app.audio_options_row.winfo_manager(), "")
        self.assertEqual(self.app.document_options_row.winfo_manager(), "")
        self.assertEqual(self.app.smart_trim_btn.winfo_manager(), "")

    def test_video_category_visibility(self):
        self.app._update_category_controls_visibility("video")
        self.assertEqual(self.app.video_options_row.winfo_manager(), "pack")
        self.assertEqual(self.app.smart_trim_btn.winfo_manager(), "pack")
        # Image-specific rows must be hidden
        self.assertEqual(self.app.size_row.winfo_manager(), "")
        self.assertEqual(self.app.ssim_row.winfo_manager(), "")
        self.assertEqual(self.app.estimate_label.winfo_manager(), "")
        self.assertEqual(self.app.preset_buttons_frame.winfo_manager(), "")
        self.assertEqual(self.app.audio_options_row.winfo_manager(), "")
        self.assertEqual(self.app.document_options_row.winfo_manager(), "")

    def test_audio_category_visibility(self):
        self.app._update_category_controls_visibility("audio")
        self.assertEqual(self.app.audio_options_row.winfo_manager(), "pack")
        self.assertEqual(self.app.video_options_row.winfo_manager(), "")
        self.assertEqual(self.app.size_row.winfo_manager(), "")
        self.assertEqual(self.app.ssim_row.winfo_manager(), "")
        self.assertEqual(self.app.document_options_row.winfo_manager(), "")
        self.assertEqual(self.app.smart_trim_btn.winfo_manager(), "")

    def test_document_category_visibility(self):
        self.app._update_category_controls_visibility("document")
        self.assertEqual(self.app.document_options_row.winfo_manager(), "pack")
        self.assertEqual(self.app.video_options_row.winfo_manager(), "")
        self.assertEqual(self.app.audio_options_row.winfo_manager(), "")
        self.assertEqual(self.app.size_row.winfo_manager(), "")
        self.assertEqual(self.app.ssim_row.winfo_manager(), "")
        self.assertEqual(self.app.smart_trim_btn.winfo_manager(), "")

    def test_trimmer_opens_from_queue_without_explicit_table_selection(self):
        test_video = Path("tests/fixtures/sample.mp4")
        self.app.selected_files = [test_video]
        self.app.row_ids[test_video] = "row_1"
        # Table selection is empty
        self.assertEqual(len(self.app.table.selection()), 0)

        with patch("main.VideoTrimmerDialog") as mock_dialog:
            self.app._open_selected_trimmer()
            mock_dialog.assert_called_once()
            called_args = mock_dialog.call_args[0]
            self.assertEqual(called_args[0], self.app)
            self.assertEqual(called_args[1], test_video)


if __name__ == "__main__":
    unittest.main()
