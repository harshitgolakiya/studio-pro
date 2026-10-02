"""Subtitle editing: timing, line length, find and replace, translation, and format conversion."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import textwrap
from typing import Callable

from studio_runtime import StagedOutput, check_cancel

SUBTITLE_EXTENSIONS = {".srt", ".vtt"}
SUBTITLE_FORMATS = {"SRT": ".srt", "VTT": ".vtt", "TXT": ".txt", "JSON": ".json"}
_TIMING = re.compile(r"(\d{1,2}:)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}:)?(\d{1,2}):(\d{2})[,.](\d{1,3})")
_VOICE_TAG = re.compile(r"^<v\s+([^>]+)>")
_BRACKET_SPEAKER = re.compile(r"^\[([^\]]{1,40})\]\s+")
_TAGS = re.compile(r"</?[a-zA-Z][^>]*>")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str
    speaker: str = ""


def _seconds(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    return int((hours or "0:").rstrip(":")) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000


def _stamp(seconds: float, separator: str) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def parse_subtitles(text: str) -> list[Cue]:
    """Read SRT or WebVTT. Cue numbers, VTT headers, notes, and styling blocks are ignored."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")):
        lines = block.strip("\n").split("\n")
        index = next((i for i, line in enumerate(lines) if _TIMING.search(line)), None)
        if index is None:
            continue
        match = _TIMING.search(lines[index])
        start, end = _seconds(*match.groups()[:4]), _seconds(*match.groups()[4:])
        body = "\n".join(line.strip() for line in lines[index + 1:] if line.strip())
        speaker = ""
        voice = _VOICE_TAG.match(body)
        bracket = _BRACKET_SPEAKER.match(body)
        if voice:
            speaker, body = voice.group(1).strip(), body[voice.end():]
        elif bracket:
            speaker, body = bracket.group(1).strip(), body[bracket.end():]
        body = _TAGS.sub("", body).strip()
        if body and end > start:
            cues.append(Cue(start, end, body, speaker))
    return cues


def load_subtitles(source: Path) -> list[Cue]:
    if source.suffix.lower() not in SUBTITLE_EXTENSIONS:
        raise ValueError("Choose an .srt or .vtt subtitle file")
    if not source.is_file():
        raise FileNotFoundError("The selected subtitle file no longer exists")
    data = source.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    cues = parse_subtitles(text)
    if not cues:
        raise ValueError("No subtitle cues were found in this file")
    return cues


def format_subtitles(cues: list[Cue], fmt: str) -> str:
    fmt = fmt.upper()
    if fmt == "TXT":
        return "\n".join((f"{c.speaker}: " if c.speaker else "") + c.text.replace("\n", " ") for c in cues) + "\n"
    if fmt == "JSON":
        return json.dumps([{"start": c.start, "end": c.end, "text": c.text, **({"speaker": c.speaker} if c.speaker else {})}
                           for c in cues], ensure_ascii=False, indent=2)
    if fmt not in ("SRT", "VTT"):
        raise ValueError(f"Choose one of: {', '.join(SUBTITLE_FORMATS)}")
    separator = "," if fmt == "SRT" else "."
    blocks = []
    for number, cue in enumerate(cues, 1):
        text = cue.text.replace("-->", "→")
        if cue.speaker:
            text = f"<v {cue.speaker}>{text}" if fmt == "VTT" else f"[{cue.speaker}] {text}"
        blocks.append(f"{number}\n{_stamp(cue.start, separator)} --> {_stamp(cue.end, separator)}\n{text}\n")
    return ("WEBVTT\n\n" if fmt == "VTT" else "") + "\n".join(blocks)


# -- edits ---------------------------------------------------------------

def shift_cues(cues: list[Cue], offset: float) -> list[Cue]:
    """Move every cue later (positive) or earlier (negative). Cues pushed before zero are dropped."""
    shifted = [replace(c, start=max(0.0, c.start + offset), end=c.end + offset) for c in cues]
    return [c for c in shifted if c.end > c.start and c.end > 0]


def scale_cues(cues: list[Cue], factor: float) -> list[Cue]:
    """Stretch timing, e.g. 25/23.976 after a frame-rate change."""
    if not 0.5 <= factor <= 2.0:
        raise ValueError("Timing scale must be between 0.5 and 2.0")
    return [replace(c, start=c.start * factor, end=c.end * factor) for c in cues]


def fix_overlaps(cues: list[Cue], gap: float = 0.04) -> list[Cue]:
    """Sort cues and end each one before the next begins."""
    ordered = sorted(cues, key=lambda c: (c.start, c.end))
    fixed = []
    for index, cue in enumerate(ordered):
        if index + 1 < len(ordered) and cue.end > ordered[index + 1].start - gap:
            cue = replace(cue, end=max(cue.start + 0.1, ordered[index + 1].start - gap))
        fixed.append(cue)
    return fixed


def reflow_cues(cues: list[Cue], max_chars: int = 42, max_lines: int = 2) -> list[Cue]:
    """Wrap text to ``max_chars`` per line; cues needing more lines are split, sharing their time by length."""
    if not 20 <= max_chars <= 120 or not 1 <= max_lines <= 4:
        raise ValueError("Line length must be 20–120 characters and 1–4 lines")
    result = []
    for cue in cues:
        lines = textwrap.wrap(" ".join(cue.text.split()), width=max_chars, break_long_words=False) or [cue.text]
        groups = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]
        total = sum(len(" ".join(group)) for group in groups) or 1
        position = cue.start
        for number, group in enumerate(groups):
            share = (cue.end - cue.start) * len(" ".join(group)) / total
            end = cue.end if number == len(groups) - 1 else position + share
            result.append(Cue(position, end, "\n".join(group), cue.speaker))
            position = end
    return result


def merge_short_cues(cues: list[Cue], min_duration: float = 1.0, max_gap: float = 0.3, max_chars: int = 84) -> list[Cue]:
    """Join a too-brief cue to its neighbour when the same speaker continues almost immediately."""
    merged: list[Cue] = []
    for cue in cues:
        previous = merged[-1] if merged else None
        if (previous and previous.speaker == cue.speaker and cue.start - previous.end <= max_gap
                and (previous.end - previous.start < min_duration or cue.end - cue.start < min_duration)
                and len(previous.text) + len(cue.text) + 1 <= max_chars):
            merged[-1] = Cue(previous.start, cue.end, f"{previous.text} {cue.text}", cue.speaker)
        else:
            merged.append(cue)
    return merged


def replace_in_cues(cues: list[Cue], replacements: dict[str, str], match_case: bool = False) -> tuple[list[Cue], int]:
    count, result = 0, []
    patterns = [(re.compile(re.escape(find), 0 if match_case else re.I), value.replace("\\", "\\\\"))
                for find, value in replacements.items() if find]
    for cue in cues:
        text = cue.text
        for pattern, value in patterns:
            text, made = pattern.subn(value, text)
            count += made
        result.append(replace(cue, text=text))
    return [cue for cue in result if cue.text.strip()], count


def rename_speakers(cues: list[Cue], names: dict[str, str]) -> list[Cue]:
    """Replace labels such as ``Speaker 1`` with real names."""
    return [replace(cue, speaker=names.get(cue.speaker, cue.speaker)) for cue in cues]


def edit_subtitles(source: Path, destination: Path, shift: float = 0.0, scale: float = 1.0,
                   max_chars: int | None = None, max_lines: int = 2, merge_short: bool = False,
                   replacements: dict[str, str] | None = None, match_case: bool = False,
                   speaker_names: dict[str, str] | None = None, translate: tuple[str, str] | None = None,
                   overwrite: bool = False, cancel_check: Callable[[], bool] | None = None,
                   progress: Callable[[str], None] | None = None) -> tuple[Path, dict[str, int]]:
    """Apply edits in a fixed order and save as SRT, VTT, TXT, or JSON (by extension).

    Order: replace text, rename speakers, translate, merge short cues, rewrap
    lines, scale timing, shift timing, fix overlaps.
    """
    fmt = next((name for name, ext in SUBTITLE_FORMATS.items() if destination.suffix.lower() == ext), None)
    if fmt is None:
        raise ValueError(f"Save subtitles as one of: {', '.join(SUBTITLE_FORMATS.values())}")
    if destination.resolve() == source.resolve():
        raise ValueError("Choose a new output path to keep your original subtitles")
    cues = load_subtitles(source)
    report = {"cues_in": len(cues), "replacements": 0}
    check_cancel(cancel_check)
    if replacements:
        cues, report["replacements"] = replace_in_cues(cues, replacements, match_case)
    if speaker_names:
        cues = rename_speakers(cues, speaker_names)
    if translate:
        from translation_engine import translate_texts
        translated = translate_texts([cue.text.replace("\n", " ") for cue in cues], translate[0], translate[1],
                                     cancel_check, progress)
        cues = [replace(cue, text=text) for cue, text in zip(cues, translated) if text.strip()]
    if merge_short:
        cues = merge_short_cues(cues)
    if max_chars or translate:
        # Translated text has different line lengths; rewrap it even when not asked.
        cues = reflow_cues(cues, max_chars or 42, max_lines)
    if scale != 1.0:
        cues = scale_cues(cues, scale)
    if shift:
        cues = shift_cues(cues, shift)
    cues = fix_overlaps(cues)
    if not cues:
        raise ValueError("No cues remain after these edits")
    report["cues_out"] = len(cues)
    with StagedOutput(destination, overwrite) as stage:
        stage.path.write_text(format_subtitles(cues, fmt), encoding="utf-8")
    return stage.output, report


def translate_text_file(source: Path, destination: Path, source_language: str, target_language: str,
                        overwrite: bool = False, cancel_check: Callable[[], bool] | None = None,
                        progress: Callable[[str], None] | None = None) -> Path:
    """Translate a plain-text or Markdown file paragraph by paragraph, keeping blank lines."""
    if source.suffix.lower() not in {".txt", ".md", ".markdown"}:
        raise ValueError("Text translation reads .txt and .md files")
    if destination.resolve() == source.resolve():
        raise ValueError("Choose a new output path to keep your original file")
    from translation_engine import translate_texts
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    translated = translate_texts(lines, source_language, target_language, cancel_check, progress)
    with StagedOutput(destination, overwrite) as stage:
        stage.path.write_text("\n".join(translated) + "\n", encoding="utf-8")
    return stage.output
