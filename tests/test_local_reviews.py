import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from local_reviews import create_review,load_review,add_comment,add_revision,decide,version_status,package_approved,review_export


class LocalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.one=self.root/'creative.txt';self.one.write_text('First version')
        self.two=self.root/'caption.txt';self.two.write_text('Caption')
        self.path=create_review('Launch',[self.one,self.two],'Acme',self.root/'reviews')
        self.data=load_review(self.path);self.asset=self.data['assets'][0];self.version=self.asset['versions'][0]
        self.assertEqual(self.data['name'],'Launch')

    def approve(self):decide(self.path,self.asset['id'],self.version['id'],'Reviewer','Approved')

    def test_comments_and_decisions_are_bound_to_versions_and_revision_starts_draft(self):
        add_comment(self.path,self.asset['id'],self.version['id'],'Copywriter','Use a stronger opening.');self.approve()
        self.one.write_text('Second version');add_revision(self.path,self.asset['id'],self.one)
        versions=load_review(self.path)['assets'][0]['versions'];self.assertEqual(len(versions),2)
        self.assertEqual(versions[0]['status'],'Approved');self.assertEqual(versions[0]['comments'][0]['author'],'Copywriter')
        self.assertEqual(versions[1]['status'],'Draft');self.assertFalse(versions[1]['comments'])
        with self.assertRaisesRegex(ValueError,'current'):self.approve()
        with self.assertRaisesRegex(ValueError,'No current'):package_approved(self.path,self.root/'delivery.zip')

    def test_package_only_current_approved_files_and_verify_checksums(self):
        self.approve();add_comment(self.path,self.asset['id'],self.version['id'],'Reviewer','Private internal discussion')
        before=hashlib.sha256(self.one.read_bytes()).hexdigest();archive=package_approved(self.path,self.root/'delivery.zip')
        with zipfile.ZipFile(archive) as z:
            index=json.loads(z.read('approved-files.json'));self.assertEqual(index['excluded'],1)
            self.assertEqual(len(index['files']),1);self.assertEqual(index['files'][0]['approved_by'],'Reviewer')
            self.assertFalse(any('caption.txt' in name for name in z.namelist()))
            self.assertNotIn('Private internal discussion',z.read('approved-files.json').decode())
        from archive_tools import verify_package
        self.assertTrue(verify_package(archive)['ok']);self.assertEqual(before,hashlib.sha256(self.one.read_bytes()).hexdigest())

    def test_changed_snapshot_cannot_be_approved_or_packaged(self):
        self.approve();version=load_review(self.path)['assets'][0]['versions'][0]
        (self.path.parent/version['path']).write_text('Changed externally')
        self.assertEqual(version_status(self.path,version),'Changed')
        with self.assertRaisesRegex(ValueError,'changed'):self.approve()
        with self.assertRaisesRegex(ValueError,'No current'):package_approved(self.path,self.root/'delivery.zip')

    def test_missing_name_and_invalid_status_rejected_without_decisions(self):
        with self.assertRaisesRegex(ValueError,'reviewer'):decide(self.path,self.asset['id'],self.version['id'],'','Approved')
        with self.assertRaisesRegex(ValueError,'status'):decide(self.path,self.asset['id'],self.version['id'],'Reviewer','Published')
        self.assertFalse(load_review(self.path)['assets'][0]['versions'][0]['decisions'])

    def test_review_export_verifies_source_outputs_and_snapshots_them(self):
        receipt=self.root/'campaign-receipt.json'
        receipt.write_text(json.dumps({'version':1,'profile':{'project':'Export'},'jobs':[{'status':'completed','relative_output':self.one.name,'output_sha256':hashlib.sha256(self.one.read_bytes()).hexdigest()}]}))
        path=review_export(receipt,self.root/'reviews');self.one.write_text('Changed original')
        version=load_review(path)['assets'][0]['versions'][0];self.assertEqual(version_status(path,version),'Draft')
        with self.assertRaisesRegex(ValueError,'changed'):review_export(receipt,self.root/'reviews')

    def test_snapshot_path_escape_and_unbound_approval_are_rejected(self):
        data=load_review(self.path);data['assets'][0]['versions'][0]['status']='Approved';self.path.write_text(json.dumps(data))
        self.assertEqual(version_status(self.path,data['assets'][0]['versions'][0]),'Changed')
        data['assets'][0]['versions'][0]['path']='../../outside.txt';self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'inside'):load_review(self.path)

    def test_two_processes_keep_all_comments(self):
        import subprocess,sys
        code="import sys;from local_reviews import add_comment;[add_comment(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4],str(i)) for i in range(5)]"
        processes=[subprocess.Popen([sys.executable,'-c',code,str(self.path),self.asset['id'],self.version['id'],author],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for author in ('Production','Account')]
        for process in processes:
            stdout,stderr=process.communicate(timeout=15);self.assertEqual(process.returncode,0,stderr.decode())
        self.assertEqual(len(load_review(self.path)['assets'][0]['versions'][0]['comments']),10)

    def test_same_filename_variants_have_distinct_board_labels(self):
        sources=[]
        for variant in ('square','portrait','story'):
            source=self.root/variant/'creative.jpg';source.parent.mkdir();source.write_bytes(b'fixture');sources.append(source)
        path=create_review('Variants',sources,directory=self.root/'reviews')
        self.assertEqual(len({a['name'] for a in load_review(path)['assets']}),3)
