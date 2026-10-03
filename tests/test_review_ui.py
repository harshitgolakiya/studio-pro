from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import customtkinter as ctk
from studio_dialog import StudioToolsDialog
from ui_dispatch import cancel_widget_callbacks
from local_reviews import load_review


class ReviewUiTests(unittest.TestCase):
    def test_create_comment_approve_package_and_revision(self):
        with tempfile.TemporaryDirectory() as td,patch('local_reviews.get_app_data_dir',return_value=Path(td)):
            root=ctk.CTk();root.withdraw();root.output_directory=tk.StringVar(master=root,value=td);dialog=StudioToolsDialog(root)
            def wait():
                deadline=time.monotonic()+10
                while dialog._busy and time.monotonic()<deadline:root.update();time.sleep(.02)
                self.assertFalse(dialog._busy)
            try:
                source=Path(td)/'creative.txt';source.write_text('Draft creative')
                dialog.open_tool('reviews',[source]);panel=dialog.panels['Reviews'];panel.name.set('Launch');panel.create();wait()
                self.assertIn('1 draft',panel.summary.cget('text'));panel.author.set('Reviewer');panel.comment.insert('1.0','Ready for the client.');panel.add_comment();wait()
                self.assertTrue(panel.menu.get().startswith('Launch ·'));self.assertEqual(panel.comment.get('1.0','end').strip(),'')
                self.assertIn('Ready for the client.',panel.history.get('1.0','end'));panel.state.set('Approved');panel.set_status();wait()
                self.assertIn('1 approved',panel.summary.cget('text'));panel.package();wait();self.assertEqual(dialog._last_output.suffix,'.zip')
                source.write_text('New revision')
                with patch('review_ui.filedialog.askopenfilename',return_value=str(source)):panel.revise();wait()
                self.assertIn('1 draft',panel.summary.cget('text'));self.assertEqual(len(load_review(panel.path)['assets'][0]['versions']),2)
                version=load_review(panel.path)['assets'][0]['versions'][-1]
                (panel.path.parent/version['path']).write_text('Externally changed')
                with patch('studio_dialog.messagebox.showerror'):panel.package();wait()
                self.assertIn('1 changed',panel.summary.cget('text'))
            finally:dialog.destroy();cancel_widget_callbacks(root);root.destroy()
