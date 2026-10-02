"""Offline text translation with local OPUS-MT models.

Each language pair is a model installed from Studio Tools → Models. Pairs
without a direct model are translated through English when both halves are
installed. Nothing is sent to a translation service.
"""
from __future__ import annotations

from pathlib import Path
import re
import threading
from typing import Callable

from studio_runtime import check_cancel, model_directory

_lock = threading.Lock()  # one translation model in memory at a time
_SENTENCE_END = re.compile(r"(?<=[.!?。！？…])\s+")
_MAX_SENTENCE = 400


def translation_directory() -> Path:
    return model_directory() / "translation"


def installed_pairs() -> list[tuple[str, str]]:
    """Language pairs with a direct model on disk."""
    root = translation_directory()
    if not root.is_dir():
        return []
    pairs = []
    for folder in sorted(root.iterdir()):
        if (folder / "model.bin").is_file() and (folder / "source.spm").is_file() and folder.name.count("-") == 1:
            source, target = folder.name.split("-")
            pairs.append((source, target))
    return pairs


def translation_route(source: str, target: str) -> list[tuple[str, str]]:
    """The installed models needed to get from ``source`` to ``target``."""
    if source == target:
        raise ValueError("Choose two different languages")
    pairs = set(installed_pairs())
    if (source, target) in pairs:
        return [(source, target)]
    if (source, "en") in pairs and ("en", target) in pairs:
        return [(source, "en"), ("en", target)]
    raise RuntimeError(f"No translation model for {source} → {target} is installed. "
                       "Add the language pair in Studio Tools → Models.")


def available_routes() -> list[tuple[str, str]]:
    """Every source/target combination that can be translated, including pivots through English."""
    pairs = set(installed_pairs())
    routes = set(pairs)
    for source, middle in pairs:
        if middle == "en":
            routes.update((source, target) for start, target in pairs if start == "en" and target != source)
    return sorted(routes)


def _split(text: str) -> list[str]:
    """Sentence-sized pieces; the models were trained on single sentences."""
    pieces = []
    for sentence in _SENTENCE_END.split(text.strip()):
        while len(sentence) > _MAX_SENTENCE:
            cut = sentence.rfind(" ", 0, _MAX_SENTENCE)
            cut = cut if cut > 0 else _MAX_SENTENCE
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if sentence:
            pieces.append(sentence)
    return pieces


def _translate_with(pair: tuple[str, str], texts: list[str], cancel_check, progress) -> list[str]:
    try:
        import ctranslate2
        import sentencepiece
    except ImportError as exc:
        raise RuntimeError("Translation engine is missing. Install requirements-studio.txt") from exc
    folder = translation_directory() / f"{pair[0]}-{pair[1]}"
    encoder = sentencepiece.SentencePieceProcessor(model_file=str(folder / "source.spm"))
    decoder = sentencepiece.SentencePieceProcessor(model_file=str(folder / "target.spm"))
    translator = ctranslate2.Translator(str(folder), device="cpu", compute_type="int8", intra_threads=4)
    results = []
    try:
        for number, text in enumerate(texts, 1):
            check_cancel(cancel_check)
            if progress and (number % 20 == 1 or number == len(texts)):
                progress(f"Translating {pair[0]} → {pair[1]}: {number} of {len(texts)}")
            if not text.strip():
                results.append(text)
                continue
            sentences = _split(text)
            # The models expect an end-of-sentence marker on each input.
            batch = [encoder.encode(sentence, out_type=str) + ["</s>"] for sentence in sentences]
            output = translator.translate_batch(batch, beam_size=4, max_decoding_length=256,
                                                repetition_penalty=1.1)
            results.append(" ".join(decoder.decode(item.hypotheses[0]) for item in output).strip())
    finally:
        del translator
    return results


def translate_texts(texts: list[str], source: str, target: str,
                    cancel_check: Callable[[], bool] | None = None,
                    progress: Callable[[str], None] | None = None) -> list[str]:
    """Translate each text, keeping the list's order and length."""
    route = translation_route(source, target)
    check_cancel(cancel_check)
    while not _lock.acquire(timeout=0.1):
        check_cancel(cancel_check)
    try:
        for pair in route:
            texts = _translate_with(pair, texts, cancel_check, progress)
    finally:
        _lock.release()
    return texts
