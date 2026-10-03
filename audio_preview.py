"""Owned, cancellable WAV playback with an explicit output device."""
from pathlib import Path
import threading
import wave


def output_devices():
    import sounddevice as sd
    devices = {'System default': None}
    # Show one host API on Windows to avoid repeating each speaker four times.
    hosts = sd.query_hostapis()
    preferred = next((i for i, host in enumerate(hosts) if host['name'] == 'Windows WASAPI'), None)
    for index, device in enumerate(sd.query_devices()):
        if device['max_output_channels'] > 0 and (preferred is None or device['hostapi'] == preferred):
            label = device['name']
            if label in devices: label = f'{label} ({index})'
            devices[label] = index
    return devices


def wav_info(path):
    import numpy as np
    with wave.open(str(path)) as wav:
        if wav.getsampwidth() != 2:
            raise ValueError('Preview supports 16-bit WAV audio.')
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768
        return {'duration': wav.getnframes() / wav.getframerate(),
                'peak': float(np.max(np.abs(samples))) if samples.size else 0.0,
                'rms': float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0}


class WavPlayer:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def stop(self):
        self._stop.set()

    def play(self, path: Path, device=None, volume=1.0, finished=lambda error: None):
        if self._thread and self._thread.is_alive():
            raise RuntimeError('Stop the current preview before playing another one.')
        stop = self._stop = threading.Event()
        def worker():
            error = None
            try:
                import numpy as np
                import sounddevice as sd
                import av
                with wave.open(str(path)) as wav:
                    if wav.getsampwidth() != 2:
                        raise ValueError('Preview supports 16-bit WAV audio.')
                    channels, rate = wav.getnchannels(), wav.getframerate()
                    if channels not in (1, 2):
                        raise ValueError('Preview supports mono or stereo WAV audio.')
                    # WASAPI shared outputs often require the device's mix
                    # rate (usually 48kHz), while Piper voices use 22.05kHz.
                    # Resample only playback; the exported WAV stays intact.
                    output_rate = int(sd.query_devices(device, 'output')['default_samplerate'])
                    layout = 'mono' if channels == 1 else 'stereo'
                    resampler = av.AudioResampler(format='fltp', layout=layout, rate=output_rate)
                    with sd.OutputStream(device=device, samplerate=output_rate, channels=channels, dtype='float32') as stream:
                        while not stop.is_set():
                            raw = wav.readframes(2048)
                            if not raw: break
                            samples = np.frombuffer(raw, dtype='<i2').reshape(1, -1)
                            frame = av.AudioFrame.from_ndarray(samples, format='s16', layout=layout)
                            frame.sample_rate = rate
                            for converted in resampler.resample(frame):
                                stream.write(np.ascontiguousarray(converted.to_ndarray().T) * max(0.0, min(1.0, volume)))
                        if not stop.is_set():
                            for converted in resampler.resample(None):
                                stream.write(np.ascontiguousarray(converted.to_ndarray().T) * max(0.0, min(1.0, volume)))
                        if stop.is_set(): stream.abort()
            except Exception as exc:
                error = str(exc)
            finished(error)
        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
