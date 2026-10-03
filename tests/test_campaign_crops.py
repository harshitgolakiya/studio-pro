from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import Image
import customtkinter as ctk
from campaign_crops import crop_box,source_sha,settings_sha
from agency_projects import run_project,validate_profile,save_profile,load_profile
from campaign_exports import plan_exports
from crop_ui import CropDialog
from ui_dispatch import cancel_widget_callbacks


class CampaignCropTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'design.png';image=Image.new('RGB',(1200,400),'red');image.paste('blue',(800,0,1200,400));image.save(self.source)
        self.profile={'client':'Acme','project':'Launch','preset':'Social square','export_set':'Single preset'}

    def framed(self,x):
        profile=dict(self.profile)
        profile['crop_positions']={str(self.source.resolve()):{'Social square':{'x':x,'y':.5,'source_sha256':source_sha(self.source),'settings_sha256':settings_sha(profile,'Social square')}}}
        return profile

    def test_final_export_uses_position_without_early_center_crop(self):
        left=run_project(self.framed(0),[self.source],self.root/'left',False);right=run_project(self.framed(1),[self.source],self.root/'right',False)
        self.assertTrue(left.ok);self.assertTrue(right.ok)
        with Image.open(left.outputs[0]) as image:self.assertGreater(image.getpixel((540,540))[0],240);self.assertEqual(image.size,(1080,1080))
        with Image.open(right.outputs[0]) as image:self.assertGreater(image.getpixel((540,540))[2],240)
        self.assertEqual(crop_box((1200,400),(1080,1080),(1,.5)),(800,0,1200,400))

    def test_changed_source_invalidates_framing_and_profile_roundtrips(self):
        profile=self.framed(.2);file=save_profile(profile,self.root);self.assertEqual(load_profile(file)['crop_positions'],profile['crop_positions'])
        Image.new('RGB',(1000,400),'green').save(self.source)
        with self.assertRaisesRegex(ValueError,'changed'):run_project(profile,[self.source],self.root/'exports',False)
        invalid=self.framed(.5);invalid['crop_positions'][str(self.source.resolve())]['Social square']['x']=2
        with self.assertRaisesRegex(ValueError,'crop'):validate_profile(invalid)

    def test_crop_dialog_saves_adjusted_positions(self):
        root=ctk.CTk();root.withdraw();saved=[];dialog=CropDialog(root,self.profile,plan_exports(self.profile,[self.source]),saved.append)
        try:
            deadline=time.monotonic()+8
            while dialog._image is None and time.monotonic()<deadline:root.update();time.sleep(.02)
            self.assertIsNotNone(dialog._image);dialog.x.set(1);dialog.save()
            self.assertEqual(saved[0][str(self.source.resolve())]['Social square']['x'],1)
        finally:
            if not dialog._closed:dialog.destroy()
            cancel_widget_callbacks(root);root.destroy()

    def test_changed_processing_and_brand_logo_invalidate_saved_framing(self):
        profile=self.framed(.2);profile['settings']={'rotate_angle':'90°'}
        with self.assertRaisesRegex(ValueError,'changed'):run_project(profile,[self.source],self.root/'exports',False)
        logo=self.root/'logo.png';Image.new('RGBA',(20,20),'white').save(logo)
        profile=dict(self.profile,watermark=True,logo=str(logo));before=settings_sha(profile,'Social square')
        Image.new('RGBA',(20,20),'black').save(logo)
        self.assertNotEqual(before,settings_sha(profile,'Social square'))

    def test_closing_crop_dialog_discards_unsaved_changes(self):
        root=ctk.CTk();root.withdraw();saved=[];profile=self.framed(.2)
        dialog=CropDialog(root,profile,plan_exports(profile,[self.source]),saved.append)
        try:
            deadline=time.monotonic()+8
            while dialog._image is None and time.monotonic()<deadline:root.update();time.sleep(.02)
            self.assertIsNotNone(dialog._image);dialog.x.set(1);dialog.remember();dialog.destroy()
            self.assertFalse(saved);self.assertEqual(profile['crop_positions'][str(self.source.resolve())]['Social square']['x'],.2)
        finally:
            if not dialog._closed:dialog.destroy()
            cancel_widget_callbacks(root);root.destroy()
