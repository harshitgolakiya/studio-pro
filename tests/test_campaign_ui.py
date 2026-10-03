from pathlib import Path
import tempfile
import tkinter as tk
import time
import unittest
from unittest.mock import patch
import customtkinter as ctk
from PIL import Image
from studio_dialog import StudioToolsDialog
from ui_dispatch import cancel_widget_callbacks


class CampaignUiTests(unittest.TestCase):
    def test_preview_saved_set_and_real_export_route(self):
        with tempfile.TemporaryDirectory() as td,patch('agency_projects.get_app_data_dir',return_value=Path(td)):
            root=ctk.CTk();root.withdraw();root.output_directory=tk.StringVar(master=root,value=td)
            dialog=StudioToolsDialog(root)
            try:
                source=Path(td)/'design.png';Image.new('RGB',(300,250),'navy').save(source)
                panel=dialog.panels['Projects'];panel.variables['project'].set('Campaign');panel.variables['client'].set('Agency')
                panel.variables['export_set'].set('Social image set');panel.sources=[source];panel.package.set(False)
                panel.preview();self.assertIn('3 exports',panel.report.cget('text'));self.assertIn('social-story/',panel.report.cget('text'))
                panel.save();panel.load_selected(next(iter(panel.labels)));self.assertEqual(panel.variables['export_set'].get(),'Social image set')
                panel.run();deadline=time.monotonic()+15
                while dialog._busy and time.monotonic()<deadline:root.update();time.sleep(.02)
                self.assertFalse(dialog._busy);self.assertIn('3/3 exported',panel.report.cget('text'))
                self.assertTrue(panel.last_receipt.is_file());self.assertEqual(dialog._last_output,panel.last_receipt.parent)
                panel.variables['project'].set('Different project')
                panel.retry();deadline=time.monotonic()+5
                while dialog._busy and time.monotonic()<deadline:root.update();time.sleep(.02)
                self.assertIn('3/3 exported',panel.report.cget('text'))
            finally:dialog.destroy();cancel_widget_callbacks(root);root.destroy()
