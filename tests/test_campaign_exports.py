import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
from campaign_exports import plan_exports,run_campaign
from studio_actions import StudioResult


class CampaignExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'creative.png'
        Image.new('RGB',(1400,900),'coral').save(self.source)
        self.profile={'project':'Launch','client':'Acme','preset':'Web images','export_set':'Social image set'}

    def test_real_social_set_dimensions_manifest_and_source_preservation(self):
        before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        plan=plan_exports(self.profile,[self.source]);self.assertEqual(len(plan),3)
        result=run_campaign(self.profile,[self.source],self.root/'exports')
        self.assertTrue(result.ok,result.details)
        receipt=json.loads(Path(result.details['receipt']).read_text())
        sizes=[(1080,1080),(1080,1350),(1080,1920)]
        for job,size in zip(receipt['jobs'],sizes):
            with Image.open(Path(result.details['folder'])/job['relative_output']) as image:self.assertEqual(image.size,size)
            self.assertEqual(job['status'],'completed')
        self.assertEqual(before,hashlib.sha256(self.source.read_bytes()).hexdigest())
        archive=next(path for path in result.outputs if path.suffix=='.zip')
        with zipfile.ZipFile(archive) as z:
            self.assertIn('delivery-index.json',z.namelist());self.assertNotIn('campaign-receipt.json',z.namelist())
            self.assertEqual(set(j['relative_output'] for j in plan),{n for n in z.namelist() if n.endswith('.jpg')})
            self.assertNotIn(str(self.source),z.read('delivery-index.json').decode())
        from archive_tools import verify_package
        self.assertTrue(verify_package(archive)['ok'])

    def test_retry_only_failed_outputs_and_keep_success_hash(self):
        from agency_projects import run_project
        def fail_portrait(profile,*args,**kwargs):
            if profile['preset']=='Social portrait':return StudioResult([],{'failures':['Temporary failure']},False)
            return run_project(profile,*args,**kwargs)
        with patch('agency_projects.run_project',side_effect=fail_portrait):result=run_campaign(self.profile,[self.source],self.root/'exports',False)
        self.assertFalse(result.ok);self.assertEqual(result.details['exported'],2)
        receipt=Path(result.details['receipt']);before=json.loads(receipt.read_text())
        with patch('agency_projects.run_project',wraps=run_project) as convert:
            retried=run_campaign({},[],self.root,False,retry_receipt=receipt)
        self.assertTrue(retried.ok);self.assertEqual(convert.call_count,1)
        after=json.loads(receipt.read_text())
        self.assertEqual(before['jobs'][0]['output_sha256'],after['jobs'][0]['output_sha256'])

    def test_reject_changed_source_during_retry(self):
        cancelled=run_campaign(self.profile,[self.source],self.root/'exports',False,cancel_check=lambda:True)
        self.assertFalse(cancelled.ok);self.assertEqual(cancelled.details['status'],'cancelled')
        Image.new('RGB',(500,400),'blue').save(self.source)
        with patch('agency_projects.run_project') as convert:
            result=run_campaign({},[],self.root,retry_receipt=cancelled.details['receipt'])
        convert.assert_not_called();self.assertFalse(result.ok)
        self.assertIn('Source changed',result.details['failures'][0]['error'])

    def test_mixed_plan_routes_formats_and_mismatched_set_fails_before_writing(self):
        doc=self.root/'brief.docx';doc.write_bytes(b'fixture')
        video=self.root/'film.mp4';video.write_bytes(b'fixture')
        audio=self.root/'music.wav';audio.write_bytes(b'fixture')
        plan=plan_exports({**self.profile,'export_set':'Mixed client handoff'},[self.source,doc,video,audio])
        self.assertEqual([j['preset'] for j in plan],['Web images','Client documents','Video delivery','Audio master'])
        with self.assertRaisesRegex(ValueError,'cannot use'):run_campaign(self.profile,[doc],self.root/'not-created')
        self.assertFalse((self.root/'not-created').exists())

    def test_duplicate_names_get_unique_planned_paths_and_receipt_blocks_path_escape(self):
        other=self.root/'other';other.mkdir();second=other/'creative.png';second.write_bytes(self.source.read_bytes())
        jobs=plan_exports({**self.profile,'naming':'{stem}'},[self.source,second])
        self.assertEqual(len({j['relative_output'] for j in jobs}),6)
        result=run_campaign(self.profile,[self.source],self.root/'exports',False,cancel_check=lambda:True)
        receipt=Path(result.details['receipt']);data=json.loads(receipt.read_text());data['jobs'][0]['relative_output']='../../escape.jpg';receipt.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'inside'):run_campaign({},[],self.root,retry_receipt=receipt)

    def test_saved_campaign_profile_uses_shared_action_dispatcher(self):
        from agency_projects import save_profile,load_profile
        from studio_actions import run_action
        profile_file=save_profile(self.profile,self.root)
        self.assertEqual(load_profile(profile_file)['export_set'],'Social image set')
        result=run_action('project-delivery',[self.source],self.root/'delivery',options={'profile':str(profile_file),'package':False})
        self.assertTrue(result.ok,result.details);self.assertEqual(result.details['exported'],3)

    def test_packaging_retry_excludes_unplanned_files(self):
        with patch('archive_tools.build_delivery_package',side_effect=RuntimeError('Temporary packaging failure')):
            result=run_campaign(self.profile,[self.source],self.root/'exports')
        self.assertFalse(result.ok);self.assertEqual(result.details['exported'],3)
        receipt=Path(result.details['receipt']);private=receipt.parent/'social-square'/'private-notes.txt';private.write_text('internal')
        resumed=run_campaign({},[],self.root,retry_receipt=receipt)
        self.assertTrue(resumed.ok)
        archive=next(p for p in resumed.outputs if p.suffix=='.zip')
        with zipfile.ZipFile(archive) as z:self.assertFalse(any('private-notes' in name for name in z.namelist()))
