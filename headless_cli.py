"""Headless conversion and watched-folder entry point.

This module deliberately does not import the GUI. It is suitable for scripts,
scheduled tasks, and server-like local automation on Windows.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

from converter import SUPPORTED_EXTENSIONS, ConversionResult, convert_image, normalize_output_format
from doc_converter import SUPPORTED_DOCUMENT_EXTENSIONS, convert_document
from media_engine import SUPPORTED_AUDIO_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS, convert_media_file
from recipes import Recipe, load_recipe
from utils import scan_directory_for_images
from watch_folder import Route

ALL_SUPPORTED_EXTENSIONS = (
    SUPPORTED_EXTENSIONS
    | SUPPORTED_DOCUMENT_EXTENSIONS
    | SUPPORTED_AUDIO_EXTENSIONS
    | SUPPORTED_VIDEO_EXTENSIONS
)


def _target_kb(settings: dict[str, Any]) -> int | None:
    if not settings.get("enable_target_size"):
        return None
    value = float(settings.get("target_size_val", "0"))
    return max(1, int(value if settings.get("target_size_unit") == "KB" else value * 1024))


def _optional_int(value: object, enabled: bool) -> int | None:
    if not enabled:
        return None
    return int(str(value).replace("°", "").strip() or "0")


def _optional_float(value: object, enabled: bool) -> float | None:
    if not enabled:
        return None
    return float(str(value).strip())


def convert_path(source: Path, output_dir: Path, settings: dict[str, Any]) -> ConversionResult:
    """Convert one supported path using recipe-style settings."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = str(settings.get("target_format", "WEBP"))
    common = {
        "overwrite": bool(settings.get("overwrite", False)),
        "slugify_names": bool(settings.get("slugify_names", False)),
        "filename_prefix": str(settings.get("filename_prefix", "")),
        "filename_suffix": str(settings.get("filename_suffix", "")),
    }
    ext = source.suffix.lower()
    if ext in SUPPORTED_DOCUMENT_EXTENSIONS:
        document_format = next(
            (key for key in ("DOCX", "PDF", "HTML", "TXT", "MD") if key in target.upper()),
            "MD",
        )
        return convert_document(source, output_dir, target_format=document_format, **common)
    if ext in SUPPORTED_AUDIO_EXTENSIONS or ext in SUPPORTED_VIDEO_EXTENSIONS:
        media_format = "mp4"
        upper_target = target.upper()
        for marker, value in (
            ("WEBM", "webm"), ("ANIMATED WEBP", "animated_webp"),
            ("GIF", "gif"), ("MP3", "mp3"), ("AAC", "aac"),
            ("OPUS", "opus"), ("WAV", "wav"),
        ):
            if marker in upper_target:
                media_format = value
                break
        return convert_media_file(source, output_dir, target_format=media_format, **common)

    max_dimension = _optional_int(settings.get("max_dimension_text"), settings.get("enable_resize", False))
    scale_percent = _optional_float(settings.get("scale_percent_text"), settings.get("enable_resize", False))
    aspect_ratio = str(settings.get("aspect_ratio", "Original"))
    return convert_image(
        source,
        output_dir,
        quality=int(settings.get("quality", 80)),
        lossless=bool(settings.get("lossless", False)),
        preserve_metadata=bool(settings.get("preserve_metadata", False)),
        strip_metadata=bool(settings.get("strip_metadata", False)),
        max_width=max_dimension,
        max_height=max_dimension,
        scale_percent=scale_percent,
        target_format=normalize_output_format(target),
        target_kb=_target_kb(settings),
        watermark_text=str(settings.get("watermark_text", "")) if settings.get("enable_watermark") else "",
        watermark_logo_path=str(settings.get("watermark_logo_path", "")) if settings.get("enable_watermark") else "",
        watermark_position=str(settings.get("watermark_position", "bottom-right")),
        rotate_angle=_optional_int(settings.get("rotate_angle"), True) or 0,
        flip_h=bool(settings.get("flip_h", False)),
        flip_v=bool(settings.get("flip_v", False)),
        aspect_ratio=None if aspect_ratio == "Original" else aspect_ratio,
        corner_radius=_optional_int(settings.get("corner_radius"), settings.get("enable_rounded", False)) or 0,
        grayscale=bool(settings.get("grayscale", False)),
        min_ssim=_optional_float(settings.get("min_ssim_text"), settings.get("protect_quality", False)),
        target_ssim=_optional_float(settings.get("target_ssim_text"), settings.get("enable_quality_target", False)),
        operation_order=str(settings.get("operation_order", "")),
        bit_depth=str(settings.get("bit_depth", "auto")),
        hdr_tone_mapping=str(settings.get("hdr_tone_mapping", "none")),
        hdr_exposure=_optional_float(settings.get("hdr_exposure"), True) or 0.0,
        raw_white_balance=str(settings.get("raw_white_balance", "camera")),
        raw_exposure=_optional_float(settings.get("raw_exposure"), True) or 0.0,
        raw_demosaic=str(settings.get("raw_demosaic", "auto")),
        svg_scale=_optional_float(settings.get("svg_scale"), True) or 1.0,
        svg_background=str(settings.get("svg_background", "transparent")),
        **common,
    )


def _result_json(result: ConversionResult) -> dict[str, Any]:
    return {
        "event": "result",
        "source": str(result.source_path),
        "output": str(result.output_path) if result.output_path else None,
        "status": result.status,
        "saved": result.saved,
        "error": result.error,
    }


def _event_json(event: str, **payload: object) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False))


def _paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value).resolve()
        if path.is_dir():
            paths.extend(scan_directory_for_images(path, ALL_SUPPORTED_EXTENSIONS, recursive=True))
        elif path.is_file() and path.suffix.lower() in ALL_SUPPORTED_EXTENSIONS:
            paths.append(path)
    return list(dict.fromkeys(paths))


def load_watch_router(
    rules_path: Path,
    watch_dir: Path,
    fallback_output: Path,
    fallback_settings: dict[str, Any],
) -> Callable[[Path], Route | None]:
    """Load JSON rules and return a stable file-to-recipe/output router.

    A rule matches when every supplied condition matches. An unmatched file
    uses the document's ``default`` route, or the CLI fallback route. Set
    ``default`` to ``null`` to skip unmatched files.
    """
    data = json.loads(rules_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rules", []), list):
        raise ValueError("Rules file must contain a 'rules' list.")
    base = rules_path.parent
    default = data.get("default", "__fallback__")
    recipe_cache: dict[Path, dict[str, Any]] = {}

    def route_for(rule: dict[str, Any], file_path: Path) -> Route | None:
        recipe_value = rule.get("recipe")
        if recipe_value is None:
            settings = fallback_settings
        else:
            recipe_path = (base / str(recipe_value)).resolve()
            if recipe_path not in recipe_cache:
                recipe_cache[recipe_path] = load_recipe(recipe_path).settings
            settings = recipe_cache[recipe_path]
        output_value = rule.get("output")
        output = fallback_output if output_value is None else (watch_dir / str(output_value))
        return output, settings

    def matches(rule: dict[str, Any], file_path: Path) -> bool:
        extensions = rule.get("extensions")
        if extensions and file_path.suffix.lower() not in {str(ext).lower() if str(ext).startswith(".") else f".{str(ext).lower()}" for ext in extensions}:
            return False
        pattern = rule.get("glob")
        if pattern and not file_path.match(str(pattern)):
            return False
        contains = rule.get("name_contains")
        if contains and str(contains).lower() not in file_path.name.lower():
            return False
        size = file_path.stat().st_size
        if rule.get("min_bytes") is not None and size < int(rule["min_bytes"]):
            return False
        if rule.get("max_bytes") is not None and size > int(rule["max_bytes"]):
            return False
        return True

    def router(file_path: Path) -> Route | None:
        for rule in data["rules"]:
            if isinstance(rule, dict) and matches(rule, file_path):
                return route_for(rule, file_path)
        if default is None:
            return None
        if isinstance(default, dict):
            return route_for(default, file_path)
        return fallback_output, fallback_settings

    return router


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shadow headless media conversion")
    parser.add_argument("paths", nargs="*", help="Files or directories to convert")
    parser.add_argument("--output", type=Path, help="Destination directory")
    parser.add_argument("--recipe", type=Path, help="Portable .shadow-recipe.json file")
    parser.add_argument("--rules", type=Path, help="JSON watched-folder routing rules")
    parser.add_argument("--watch", type=Path, help="Watch a folder until interrupted")
    parser.add_argument("--watch-output", type=Path, help="Destination for watched files")
    parser.add_argument("--poll-interval", type=float, default=1.5)
    parser.add_argument("--json", action="store_true", help="Emit one JSON object per result")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    recipe = load_recipe(args.recipe) if args.recipe else Recipe("CLI defaults")
    settings = recipe.settings
    if args.watch:
        from watch_folder import FolderWatcher

        output = args.watch_output or args.output or args.watch / "optimized"
        router = load_watch_router(args.rules, args.watch, output, settings) if args.rules else None
        def on_watch_event(level: str, message: str) -> None:
            if args.json:
                _event_json("watch", level=level, message=message)
            else:
                print(f"[{level}] {message}")

        watcher = FolderWatcher(
            args.watch, output, target_format=settings["target_format"],
            quality=settings["quality"], poll_interval=args.poll_interval,
            recipe_settings=settings,
            route_file=router,
            on_event=on_watch_event,
        )
        watcher.start()
        try:
            while watcher.is_running:
                time.sleep(0.25)
        except KeyboardInterrupt:
            watcher.stop()
        return 0

    if not args.output:
        _parser().error("--output is required unless --watch is used")
    paths = _paths(args.paths)
    if not paths:
        print("No supported input files found.", file=sys.stderr)
        return 2
    exit_code = 0
    total = len(paths)
    if args.json:
        _event_json("started", total=total, output=str(args.output))
    for index, source in enumerate(paths, start=1):
        result = convert_path(source, args.output, settings)
        if args.json:
            _event_json("progress", completed=index, total=total, source=str(source), status=result.status)
            print(json.dumps(_result_json(result)))
        else:
            print(f"{result.status}: {source.name}" + (f" -> {result.output_path}" if result.output_path else ""))
        if result.status != "Completed":
            exit_code = 1
    if args.json:
        _event_json("finished", total=total, exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())