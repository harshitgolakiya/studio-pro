from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
import numpy as np

from audio_preview import WavPlayer, wav_info


class AudioPreviewTests(unittest.TestCase):
    def test_preview_preserves_samples_and_selected_device(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'voice.wav'
            samples = np.array([0, 8192, -16384, 32767], dtype='<i2')
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
                wav.writeframes(samples.tobytes())
            info = wav_info(path)
            self.assertGreater(info['rms'], 0.1)
            done, errors = threading.Event(), []
            def finish(error): errors.append(error); done.set()
            with patch('sounddevice.OutputStream') as stream, patch('sounddevice.query_devices', return_value={'default_samplerate': 22050}):
                player = WavPlayer()
                player.play(path, device=7, finished=finish)
                self.assertTrue(done.wait(5))
                player._thread.join(1)
                self.assertEqual(errors, [None])
                self.assertEqual(stream.call_args.kwargs['device'], 7)
                played = stream.return_value.__enter__.return_value.write.call_args.args[0]
                np.testing.assert_allclose(played[:, 0], samples.astype(np.float32) / 32768)
            self.assertEqual(path.read_bytes()[44:], samples.tobytes())

    def test_playback_resamples_for_output_mix_rate_without_editing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'voice.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
                wav.writeframes(np.full(22050, 8192, dtype='<i2').tobytes())
            original = path.read_bytes()
            done = threading.Event()
            with patch('sounddevice.OutputStream') as stream, patch('sounddevice.query_devices', return_value={'default_samplerate': 48000}):
                player = WavPlayer()
                player.play(path, device=12, finished=lambda error: done.set())
                self.assertTrue(done.wait(5))
                player._thread.join(1)
                self.assertEqual(stream.call_args.kwargs['samplerate'], 48000)
                output = stream.return_value.__enter__.return_value.write.call_args_list
                self.assertEqual(sum(call.args[0].shape[0] for call in output), 48000)
            self.assertEqual(path.read_bytes(), original)

    def test_missing_file_finishes_with_error(self):
        player = WavPlayer()
        done, errors = threading.Event(), []
        def finish(error): errors.append(error); done.set()
        player.play(Path('missing-voice-preview.wav'), finished=finish)
        self.assertTrue(done.wait(5))
        player._thread.join(1)
        self.assertTrue(errors[0])
