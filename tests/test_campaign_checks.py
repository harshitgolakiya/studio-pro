import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
from campaign_checks import check_delivery, delivery_rules
from campaign_exports import run_campaign
from studio_runtime import StudioCancelled


class DeliveryChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'creative.png'
        Image.new('RGB',(2400,3600),'navy').save(self.source)
        self.profile={'project':'Campaign','preset':'Web images','export_set':'Social image set'}

    def exported(self,package=False):
        result=run_campaign(self.profile,[self.source],self.root/'exports',package)
        self.assertTrue(result.ok,result.details)
        self.receipt=Path(result.details['receipt']);self.data=json.loads(self.receipt.read_text())
        return result

    def write(self):self.receipt.write_text(json.dumps(self.data))

    def test_ready_report_and_private_report_excluded_from_zip(self):
        before=hashlib.sha256(self.source.read_bytes()).hexdigest();result=self.exported(True)
        report=check_delivery(self.receipt)
        self.assertEqual(report['status'],'Ready');self.assertEqual(report['files'],3)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),before)
        self.assertTrue((self.receipt.parent/'delivery-checks.json').is_file())
        with zipfile.ZipFile(self.receipt.parent/self.data['archive']) as archive:
            self.assertNotIn('delivery-checks.json',archive.namelist())
        self.assertEqual(result.details['delivery_check']['errors'],0)

    def test_missing_changed_and_wrong_dimensions_are_separate_failures(self):
        self.exported();first=self.data['jobs'][0];path=self.receipt.parent/first['relative_output']
        Image.new('RGB',(200,200),'red').save(path)
        report=check_delivery(self.receipt);text=str(report['results'][0]['issues'])
        self.assertIn('contents changed',text);self.assertIn('Expected 1080',text)
        path.unlink();report=check_delivery(self.receipt);self.assertIn('missing',str(report['results'][0]['issues']))
        self.assertEqual(report['status'],'Needs attention')

    def test_format_and_missing_variant_checked_even_with_matching_hash(self):
        self.exported();job=self.data['jobs'][0];path=self.receipt.parent/job['relative_output']
        Image.new('RGB',(1080,1080),'red').save(path,format='PNG')
        job['output_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.data['jobs'].pop();self.write()
        report=check_delivery(self.receipt)
        self.assertIn('Expected JPEG',str(report['results'][0]['issues']));self.assertIn('Social story',str(report['issues']))

    def test_oversized_and_enlarged_images_are_warnings(self):
        Image.new('RGB',(100,100),'navy').save(self.source);self.exported()
        report=check_delivery(self.receipt,{'max_file_mb':.0001})
        self.assertEqual(report['errors'],0);self.assertEqual(report['status'],'Ready with warnings')
        self.assertIn('enlargement',str(report));self.assertIn('limit',str(report))

    def test_bad_receipt_paths_and_invalid_limits_are_rejected(self):
        self.exported();self.data['jobs'][0]['relative_output']='../../outside.jpg';self.write()
        with self.assertRaisesRegex(ValueError,'inside'):check_delivery(self.receipt)
        for value in (-1,float('nan'),float('inf'),True,'25'):
            with self.assertRaises(ValueError):delivery_rules({'delivery_rules':{'max_file_mb':value}})
        self.assertEqual(delivery_rules({'delivery_rules':{'max_file_mb':0}})['max_file_mb'],0)

    def test_check_errors_stop_packaging_and_retry_rechecks(self):
        with patch('campaign_checks.check_delivery',return_value={'status':'Needs attention','errors':1,'warnings':0,'checked':'test'}),patch('archive_tools.build_delivery_package') as package:
            result=run_campaign(self.profile,[self.source],self.root/'exports',True)
        package.assert_not_called();self.assertFalse(result.ok);self.assertEqual(result.details['exported'],3)
        self.assertIn('attention',result.details['check_error'])
        retried=run_campaign({},[],self.root,retry_receipt=result.details['receipt'])
        self.assertTrue(retried.ok,retried.details);self.assertEqual(retried.details['delivery_check']['errors'],0)

    def test_cancellation_does_not_claim_files_were_checked(self):
        self.exported()
        with self.assertRaises(StudioCancelled):check_delivery(self.receipt,cancel_check=lambda:True)

    def test_pdf_readability_is_checked(self):
        from reportlab.pdfgen import canvas
        pdf=self.root/'brief.pdf';writer=canvas.Canvas(str(pdf));writer.drawString(20,700,'Campaign');writer.save()
        self.profile.update(preset='Client documents',export_set='Single preset')
        result=run_campaign(self.profile,[pdf],self.root/'exports',False);self.assertTrue(result.ok,result.details)
        receipt=Path(result.details['receipt']);data=json.loads(receipt.read_text());job=data['jobs'][0];output=receipt.parent/job['relative_output']
        output.write_bytes(b'not a PDF');job['output_sha256']=hashlib.sha256(output.read_bytes()).hexdigest();receipt.write_text(json.dumps(data))
        self.assertIn('PDF could not',str(check_delivery(receipt)))
