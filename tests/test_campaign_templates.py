import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import customtkinter as ctk
from PIL import Image
from agency_templates import save_template,load_template,instantiate_template,list_templates
from campaign_exports import run_campaign
from delivery_checks_ui import DeliveryChecksDialog
from studio_dialog import StudioToolsDialog
from ui_dispatch import cancel_widget_callbacks


class CampaignTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.profile={'project':'Old campaign','client':'Acme','id':'a'*32,'preset':'Web images','export_set':'Social image set',
                      'naming':'{client}-{project}-{stem}-{preset}','colors':['#7561D4'],'fonts':['Arial'],'settings':{'rotate_angle':'0°'},'delivery_rules':{'max_file_mb':10}}

    def test_template_keeps_brand_recipe_and_limits_without_campaign_state(self):
        self.profile['crop_positions']={};self.profile['sources']=['private/source.png'];self.profile['receipt']='private/receipt.json'
        path=save_template('Acme launch',self.profile,False,self.root);template=load_template(path)
        self.assertNotIn('sources',template['profile']);self.assertNotIn('receipt',template['profile']);self.assertNotIn('id',template['profile']);self.assertNotIn('crop_positions',template['profile'])
        campaign=instantiate_template(template,'New campaign');self.assertEqual(campaign['project'],'New campaign')
        self.assertEqual(campaign['delivery_rules'],{'max_file_mb':10});self.assertFalse(template['package'])
        campaign['settings']['rotate_angle']='90°';self.assertEqual(template['profile']['settings']['rotate_angle'],'0°')

    def test_invalid_templates_ignored_and_invalid_name_rejected(self):
        with patch('agency_templates.get_app_data_dir',return_value=self.root):
            saved=save_template('Good',self.profile);(saved.parent/'invalid.json').write_text('{broken')
            self.assertEqual(len(list_templates()),1)
        with self.assertRaises(ValueError):save_template(' ',self.profile,True,self.root)

    def test_project_ui_applies_template_and_preserves_saved_recipe(self):
        with patch('agency_templates.get_app_data_dir',return_value=self.root),patch('agency_projects.get_app_data_dir',return_value=self.root):
            root=ctk.CTk();root.withdraw();root.output_directory=tk.StringVar(master=root,value=str(self.root));root._collect_recipe_settings=lambda:{'rotate_angle':'90°'}
            dialog=StudioToolsDialog(root);panel=dialog.panels['Projects']
            try:
                save_template('Acme launch',self.profile,False);panel.refresh_templates();panel.template_menu.set(next(iter(panel.templates)));panel.variables['project'].set('New campaign');panel.apply_template()
                current=panel.current();self.assertEqual(current['project'],'New campaign');self.assertEqual(current['client'],'Acme');self.assertNotIn('id',current)
                self.assertEqual(current['settings']['rotate_angle'],'0°');self.assertEqual(panel.max_file_mb.get(),'10');self.assertFalse(panel.package.get())
                panel.use_queue_recipe();self.assertEqual(panel.current()['settings']['rotate_angle'],'90°')
                panel.save_template('Updated recipe');self.assertEqual(len(panel.templates),2)
            finally:dialog.destroy();cancel_widget_callbacks(root);root.destroy()

    def test_native_delivery_dialog_recheck_reports_changed_file(self):
        source=self.root/'creative.png';Image.new('RGB',(2200,3300),'navy').save(source)
        result=run_campaign(self.profile,[source],self.root/'exports',False);self.assertTrue(result.ok,result.details)
        receipt=Path(result.details['receipt']);root=ctk.CTk();root.withdraw();dialog=DeliveryChecksDialog(root,receipt)
        def wait():
            deadline=time.monotonic()+12
            while dialog._busy and time.monotonic()<deadline:root.update();time.sleep(.02)
            self.assertFalse(dialog._busy)
        try:
            wait();self.assertEqual(dialog.report['errors'],0)
            data=json.loads(receipt.read_text());(receipt.parent/data['jobs'][0]['relative_output']).unlink();dialog.recheck();wait()
            self.assertEqual(dialog.report['status'],'Needs attention');self.assertIn('missing',str(dialog.report))
        finally:dialog.destroy();cancel_widget_callbacks(root);root.destroy()
