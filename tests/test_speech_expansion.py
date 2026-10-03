from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless  # noqa: F401

from studio_runtime import StudioCancelled

SRT = """1
00:00:01,000 --> 00:00:02,000
[Speaker 1] Hello agency

2
00:00:02,100 --> 00:00:06,000
This is a much longer subtitle line that needs to be wrapped for delivery
"""


class SubtitleTests(unittest.TestCase):
    def test_parse_srt_and_vtt_with_speakers(self):
        from subtitle_tools import format_subtitles, parse_subtitles
        cues = parse_subtitles(SRT)
        self.assertEqual((cues[0].start, cues[0].end, cues[0].text, cues[0].speaker), (1.0, 2.0, "Hello agency", "Speaker 1"))
        vtt = format_subtitles(cues, "VTT")
        self.assertTrue(vtt.startswith("WEBVTT"))
        self.assertIn("<v Speaker 1>Hello agency", vtt)
        again = parse_subtitles("WEBVTT\n\nNOTE made here\n\n" + vtt.split("\n\n", 1)[1])
        self.assertEqual(again[0].speaker, "Speaker 1")
        self.assertEqual(len(again), 2)
        self.assertEqual(format_subtitles(cues, "TXT").splitlines()[0], "Speaker 1: Hello agency")

    def test_edit_shift_wrap_replace_and_convert(self):
        from subtitle_tools import edit_subtitles, load_subtitles
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "talk.srt"
            source.write_text(SRT, encoding="utf-8")
            output, report = edit_subtitles(source, root / "edited.vtt", shift=1.5, max_chars=30,
                                            replacements={"agency": "studio"}, speaker_names={"Speaker 1": "Ana"})
            self.assertEqual(report["replacements"], 1)
            cues = load_subtitles(output)
            self.assertEqual((cues[0].start, cues[0].text, cues[0].speaker), (2.5, "Hello studio", "Ana"))
            self.assertGreater(report["cues_out"], report["cues_in"])
            self.assertTrue(all(len(line) <= 30 for cue in cues for line in cue.text.split("\n")))
            self.assertTrue(all(a.end <= b.start for a, b in zip(cues, cues[1:])))
            self.assertAlmostEqual(cues[-1].end, 7.5, places=2)
            with self.assertRaises(ValueError):
                edit_subtitles(source, source)
            with self.assertRaises(ValueError):
                edit_subtitles(source, root / "x.docx")
            with self.assertRaises(ValueError):
                edit_subtitles(source, root / "gone.srt", shift=-60)
            self.assertFalse((root / "gone.srt").exists())

    def test_scale_merge_and_overlap_fix(self):
        from subtitle_tools import Cue, fix_overlaps, merge_short_cues, scale_cues
        cues = [Cue(0, 0.4, "Hi"), Cue(0.5, 2, "there"), Cue(1.5, 3, "overlap")]
        self.assertEqual(merge_short_cues(cues)[0].text, "Hi there")
        fixed = fix_overlaps(cues)
        self.assertLess(fixed[1].end, fixed[2].start)
        self.assertAlmostEqual(scale_cues(cues, 2)[2].end, 6)
        with self.assertRaises(ValueError):
            scale_cues(cues, 5)


class SpeakerLabelTests(unittest.TestCase):
    def test_labels_follow_overlap_and_first_appearance(self):
        from speech_engine import TranscriptSegment, format_transcript, label_speakers
        segments = [TranscriptSegment(0, 4, "Hello"), TranscriptSegment(4, 8, "Hola"), TranscriptSegment(8, 9, "Bye"),
                    TranscriptSegment(20, 21, "Silence")]
        labelled = label_speakers(segments, [(0, 4.5, 7), (4.5, 8, 3), (8, 9, 7)])
        self.assertEqual([s.speaker for s in labelled], ["Speaker 1", "Speaker 2", "Speaker 1", ""])
        self.assertEqual(format_transcript(labelled[:3], "TXT"), "Speaker 1: Hello\nSpeaker 2: Hola\nSpeaker 1: Bye\n")
        self.assertIn("[Speaker 2] Hola", format_transcript(labelled, "SRT"))
        self.assertIn('"speaker": "Speaker 1"', format_transcript(labelled, "JSON"))

    def test_missing_models_fail_clearly(self):
        from audio_tools import process_audio
        from speech_engine import detect_speakers
        from translation_engine import translate_texts
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SHADOW_MODEL_DIR": td}):
            source = Path(td) / "a.wav"
            source.write_bytes(b"audio")
            with self.assertRaises(RuntimeError) as caught:
                detect_speakers(source)
            self.assertIn("Models", str(caught.exception))
            with self.assertRaises(RuntimeError):
                process_audio(source, Path(td) / "out.wav", isolate_voice=True)
            with self.assertRaises(RuntimeError):
                translate_texts(["hello"], "en", "es")
            with self.assertRaises(ValueError):
                translate_texts(["hello"], "en", "en")
            self.assertFalse((Path(td) / "out.wav").exists())


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_is_consistent(self):
        from model_catalog import KIND_LABELS, catalog
        entries = catalog()
        self.assertEqual(len({e.key for e in entries}), len(entries))
        self.assertTrue(all(e.kind in KIND_LABELS and e.marker and (e.repo or e.files or e.archive or e.bundle_archive) for e in entries))
        self.assertTrue({"whisper", "voice", "translation", "diarization", "denoise", "color"} <= {e.kind for e in entries})

    def test_install_verify_remove_and_bad_checksum(self):
        from model_catalog import ModelEntry, install, installed_bytes, is_installed, remove
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SHADOW_MODEL_DIR": str(Path(td) / "models")}):
            payload = Path(td) / "payload.bin"
            payload.write_bytes(b"model-bytes")
            good = ModelEntry("t", "denoise", "Test", "Any", 1, "denoise", "m.bin",
                              files=((payload.as_uri(), "m.bin"),), sha256=hashlib.sha256(b"model-bytes").hexdigest())
            messages = []
            folder = install(good, messages.append)
            self.assertTrue(is_installed(good))
            self.assertEqual(installed_bytes(good), 11)
            self.assertTrue(messages)
            remove(good)
            self.assertFalse(is_installed(good))
            bad = ModelEntry("b", "denoise", "Bad", "Any", 1, "denoise", "b.bin",
                             files=((payload.as_uri(), "b.bin"),), sha256="0" * 64)
            with self.assertRaises(RuntimeError):
                install(bad)
            with self.assertRaises(StudioCancelled):
                install(good, cancel_check=lambda: True)
            self.assertEqual(list(folder.iterdir()) if folder.exists() else [], [])
            offline = ModelEntry("o", "denoise", "Offline", "Any", 1, "denoise", "o.bin",
                                 files=(((Path(td) / "absent.bin").as_uri(), "o.bin"),))
            with self.assertRaises(RuntimeError):
                install(offline)


@unittest.skipUnless(os.environ.get("SHADOW_TEST_FULL_STUDIO") == "1", "Set SHADOW_TEST_FULL_STUDIO=1 for actual local engines")
class LocalSpeechEngineTests(unittest.TestCase):
    def test_isolation_repeated_normalization_is_deterministic(self):
        import hashlib
        from audio_tools import process_audio, voice_isolation_model
        from speech_engine import synthesize_speech
        if not voice_isolation_model().is_file():
            self.skipTest("Voice isolation model is not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = synthesize_speech("Hello. This is the agency studio. We create marketing campaigns.", root / "voice.wav")
            hashes = []
            for index in range(8):
                output = process_audio(source, root / f"isolated-{index}.wav", isolate_voice=True)
                self.assertGreater(output.stat().st_size, 1000)
                hashes.append(hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(len(set(hashes)), 1, "Repeated isolation corrupted the same input")

    def test_voice_isolation_and_speaker_detection(self):
        import wave
        from audio_tools import process_audio, voice_isolation_model
        from speech_engine import detect_speakers, diarization_models, synthesize_speech
        if not voice_isolation_model().is_file() or not all(p.is_file() for p in diarization_models()):
            self.skipTest("Speaker and voice isolation models are not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            voice = synthesize_speech("Hello. This is the agency studio reviewing the campaign plan.", root / "voice.wav")
            isolated = process_audio(voice, root / "isolated.wav", isolate_voice=True)
            with wave.open(str(isolated)) as wav:
                self.assertGreater(wav.getnframes() / wav.getframerate(), 2)
            turns = detect_speakers(voice)
            self.assertEqual(len({speaker for _, _, speaker in turns}), 1)

    def test_translation_roundtrip_when_a_pair_is_installed(self):
        from subtitle_tools import edit_subtitles, load_subtitles
        from translation_engine import installed_pairs, translate_texts
        if ("en", "es") not in installed_pairs():
            self.skipTest("English → Spanish translation model is not installed")
        self.assertIn("gracias", translate_texts(["Thank you very much."], "en", "es")[0].lower())
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "talk.srt"
            source.write_text(SRT, encoding="utf-8")
            output, _ = edit_subtitles(source, Path(td) / "talk-es.srt", translate=("en", "es"))
            cues = load_subtitles(output)
            self.assertEqual(cues[0].speaker, "Speaker 1")
            self.assertIn("hola", cues[0].text.lower())


if __name__ == "__main__":
    unittest.main()
