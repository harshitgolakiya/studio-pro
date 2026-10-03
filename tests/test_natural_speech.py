from pathlib import Path
import tempfile
import tarfile
import shutil
import unittest
from unittest.mock import patch
from natural_speech import speech_chunks, install_voice_descriptors, voice_ready
from studio_runtime import StudioCancelled


class NaturalSpeechTests(unittest.TestCase):
    def test_paragraphs_and_sentence_boundaries_are_preserved(self):
        text = 'That is wonderful! Really?\n\nTake your time. ' + ('A long sentence. ' * 120)
        chunks = speech_chunks(text)
        self.assertEqual(chunks[0], 'That is wonderful! Really?')
        self.assertTrue(all(len(chunk) <= 800 for chunk in chunks))
        self.assertEqual(' '.join(' '.join(chunks).split()), ' '.join(text.split()))

    def test_installer_and_corrupt_descriptor_detection(self):
        import model_catalog
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);source=root/'source'/'kokoro';source.mkdir(parents=True)
            for name in ('model.onnx','voices.bin','tokens.txt','lexicon-us-en.txt','lexicon-gb-en.txt'):(source/name).write_bytes(b'fixture')
            (source/'espeak-ng-data').mkdir();(source/'espeak-ng-data'/'data').write_bytes(b'data')
            archive=root/'model.tar.bz2'
            with tarfile.open(archive,'w:bz2') as tar:tar.add(source,arcname='kokoro')
            entry=next(e for e in model_catalog.catalog() if e.key=='voice-kokoro-v1')
            with patch('model_catalog.model_directory',return_value=root/'models'), patch('model_catalog._download',side_effect=lambda url,path,**kw:shutil.copy2(archive,path)):
                target=model_catalog.install(entry)
                self.assertTrue(model_catalog.is_installed(entry))
                self.assertEqual(len(list((target/'voices').glob('*.voice.json'))),10)
                marker=target/'voices'/'af_heart.voice.json'
                self.assertTrue(voice_ready(marker))
                marker.write_text('{broken')
                self.assertFalse(voice_ready(marker))

    def test_cancelled_synthesis_does_not_publish_output(self):
        from speech_engine import synthesize_speech
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'speech.wav'
            with self.assertRaises(StudioCancelled):synthesize_speech('Hello.',output,cancel_check=lambda:True)
            self.assertFalse(output.exists())
