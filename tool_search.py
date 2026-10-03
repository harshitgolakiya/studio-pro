"""Local tool search with everyday phrases, word matching and conservative typos."""
from difflib import get_close_matches
from functools import lru_cache
import re
import unicodedata

ALIASES = {
    'convert-image': 'compress image|make image smaller|shrink photo|resize picture|change image format|watermark photo|jpeg png webp',
    'convert-video': 'make video smaller|shrink video|compress mp4|reduce video size|change video format',
    'convert-audio': 'convert mp3|wav to mp3|change audio format|export mp3',
    'convert-document': 'word to pdf|docx to pdf|export document|document conversion',
    'transcribe': 'transcript|transcription|speech to text|video transcript|audio transcript|create subtitles|automatic captions',
    'speak': 'voiceover|text to speech|tts|generate speech|read aloud|narration|create voiceover',
    'audio': 'remove noise|clean audio|reduce background noise|normalize volume|make audio louder|trim audio',
    'audio-isolate': 'isolate voice|separate speech|extract voice|speech isolation',
    'speech-batch': 'batch transcription|multiple transcripts|transcribe recordings|speaker detection|diarization',
    'trim': 'cut video|shorten video|trim clip|cut clip',
    'pdf-merge': 'combine pdf|join pdf|merge documents|combine pdf files',
    'pdf-extract': 'split pdf|keep pdf pages|remove pdf pages|extract pages',
    'pdf-rotate': 'turn pdf pages|rotate scan|fix page orientation',
    'pdf-compress': 'make pdf smaller|shrink pdf|reduce pdf size',
    'pdf-images': 'pdf to images|pdf to jpg|pdf to png|export pdf pages',
    'ocr': 'scan to text|image to text|extract text|searchable pdf|read scanned document',
    'subtitle-edit': 'edit captions|fix subtitle timing|srt vtt|subtitle editor',
    'subtitle-translate': 'translate captions|subtitle translation|translate srt',
    'text-translate': 'translate text|document translation|change text language',
    'pdf-protect': 'password pdf|encrypt pdf|lock pdf',
    'pdf-unlock': 'remove pdf password|unlock document|decrypt pdf',
    'pdf-redact': 'hide sensitive text|redact document|remove private information',
    'pdf-sign': 'sign pdf|digital signature|sign document',
    'pdf-fill': 'fill pdf form|complete pdf form',
    'data-clean': 'remove duplicates|clean spreadsheet|duplicate rows',
    'archive-create': 'zip files|create zip|pack files|compress folder',
    'archive-extract': 'unzip|unpack|extract zip|extract 7z',
    'watch': 'watch folder|automatic conversion|folder automation',
    'download': 'download video|download audio|import url|save online media',
    'models': 'voice models|install voices|language models|manage voices',
    'recipes': 'save preset|saved presets|reuse settings',
    'history': 'recent conversions|previous jobs|past results',
}
STOP_WORDS = frozenset('a an the my your please i want need how can do to from for of and with get make'.split())


def normalize(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def tokens(text):
    return {word[:-1] if len(word) > 4 and word.endswith('s') else word
            for word in normalize(text).split() if word not in STOP_WORDS}


@lru_cache(maxsize=256)
def search_document(tool):
    title, key = normalize(tool.title), normalize(tool.key)
    aliases = tuple(normalize(alias) for alias in ALIASES.get(tool.key, '').split('|') if alias)
    words = tokens(' '.join((tool.title, tool.key, tool.group, tool.description, *aliases)))
    return title, key, aliases, words


def search_tools(tools, query):
    """Rank matching tools, preserving catalog order when scores are equal."""
    tools = list(tools)
    phrase = normalize(query)
    if not phrase:return tools
    # Preserve direction for named operations such as Audio to text / Text to audio.
    exact = [tool for tool in tools if phrase in search_document(tool)[:2]]
    if exact:return exact
    wanted = tokens(phrase)
    if not wanted:return []
    ranked = []
    for index, tool in enumerate(tools):
        title, key, aliases, words = search_document(tool)
        if phrase in aliases:score = 180
        elif phrase in title:score = 160
        elif any(phrase in alias for alias in aliases):score = 150
        elif wanted <= words:score = 120 if wanted <= tokens(title) else 100
        elif all(word in words or (len(word) >= 3 and any(candidate.startswith(word) for candidate in words))
                 or (len(word) >= 5 and get_close_matches(word, words, n=1, cutoff=.86)) for word in wanted):score = 60
        else:continue
        ranked.append((-score, index, tool))
    return [tool for _, _, tool in sorted(ranked, key=lambda item:item[:2])]
