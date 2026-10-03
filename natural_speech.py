"""Kokoro voices using the existing local sherpa-onnx runtime."""
import json
from pathlib import Path
import re
import textwrap
import wave

VOICES = {
    'af_heart': (3, 'Heart · US female'), 'am_michael': (16, 'Michael · US male'),
    'bf_emma': (21, 'Emma · UK female'), 'bm_daniel': (24, 'Daniel · UK male'),
}


def install_voice_descriptors(folder):
    folder = Path(folder) / 'voices'
    folder.mkdir(parents=True, exist_ok=True)
    for name, (speaker, label) in VOICES.items():
        (folder / f'{name}.voice.json').write_text(json.dumps({'engine':'kokoro', 'speaker_id':speaker,
                                                            'label':label + ' · Natural'}), encoding='utf-8')


def voice_ready(path):
    path = Path(path)
    if path.name.endswith('.voice.json'):
        root = path.parent.parent
        try:
            metadata = json.loads(path.read_text(encoding='utf-8'))
            valid = metadata.get('engine') == 'kokoro' and type(metadata.get('speaker_id')) is int and 0 <= metadata['speaker_id'] < 28 and isinstance(metadata.get('label'), str)
        except (OSError, ValueError, AttributeError):return False
        return valid and all((root / name).exists() for name in ('model.onnx','voices.bin','tokens.txt','espeak-ng-data','lexicon-us-en.txt','lexicon-gb-en.txt'))
    return path.is_file() and Path(str(path) + '.json').is_file()


def voice_label(path):
    path = Path(path)
    if path.name.endswith('.voice.json'):
        return json.loads(path.read_text(encoding='utf-8'))['label']
    return None


def speech_chunks(text):
    # Keep paragraph breaks and sentence punctuation; split only oversized paragraphs.
    chunks = []
    for paragraph in re.split(r'\n\s*\n', text.strip()):
        if len(paragraph) <= 800:chunks.append(paragraph)
        else:
            current = ''
            for sentence in re.split(r'(?<=[.!?])\s+', paragraph):
                for piece in textwrap.wrap(sentence, width=800, replace_whitespace=False):
                    if current and len(current) + len(piece) + 1 > 800:
                        chunks.append(current);current = ''
                    current = (current + ' ' + piece).strip()
            if current:chunks.append(current)
    return chunks


def synthesize_kokoro(text, temporary, voice_path, speed, cancel_check, progress):
    import sherpa_onnx
    import numpy as np
    from studio_runtime import check_cancel
    metadata = json.loads(Path(voice_path).read_text(encoding='utf-8'))
    root = Path(voice_path).parent.parent
    lexicon = root / ('lexicon-gb-en.txt' if Path(voice_path).name.startswith('b') else 'lexicon-us-en.txt')
    config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(model=str(root/'model.onnx'), voices=str(root/'voices.bin'),
                                                  tokens=str(root/'tokens.txt'), data_dir=str(root/'espeak-ng-data'),
                                                  lexicon=str(lexicon), lang='en'), num_threads=2), max_num_sentences=1)
    if not config.validate():raise RuntimeError('Natural voice pack is incomplete. Reinstall it in Voices / models.')
    if progress:progress('Loading natural voice…')
    engine = sherpa_onnx.OfflineTts(config)
    chunks = speech_chunks(text)
    with wave.open(str(temporary), 'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(engine.sample_rate)
        for index, chunk in enumerate(chunks):
            check_cancel(cancel_check)
            if progress:progress(f'Generating natural speech {index+1}/{len(chunks)}…')
            audio = engine.generate(chunk, sid=int(metadata['speaker_id']), speed=speed,
                                    callback=lambda samples, fraction:0 if cancel_check and cancel_check() else 1)
            check_cancel(cancel_check)
            samples = np.asarray(audio.samples, dtype=np.float32)
            if not samples.size or not np.isfinite(samples).all():raise RuntimeError('The voice produced invalid audio.')
            wav.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())
            if index < len(chunks)-1:wav.writeframes(bytes(int(engine.sample_rate*.18)*2))
