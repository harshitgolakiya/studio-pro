"""Persistent client profiles, brand kits, naming, and repeatable delivery runs."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from string import Formatter
import uuid

from settings import get_app_data_dir
from studio_runtime import StagedOutput, check_cancel

PRESETS = {
    "Web images": {"target_format": "WEBP", "quality": 82, "enable_resize": True, "max_dimension_text": "1920"},
    "Social square": {"target_format": "JPG", "quality": 90, "enable_resize": True, "max_dimension_text": "1080", "aspect_ratio": "1:1"},
    "Social portrait": {"target_format": "JPG", "quality": 90, "enable_resize": True, "max_dimension_text": "1350", "aspect_ratio": "4:5"},
    "Social story": {"target_format": "JPG", "quality": 90, "enable_resize": True, "max_dimension_text": "1920", "aspect_ratio": "9:16"},
    "Print images": {"target_format": "TIFF", "lossless": True, "preserve_metadata": True},
    "Client documents": {"target_format": "PDF"},
    "Audio master": {"target_format": "WAV"},
    "Video delivery": {"target_format": "MP4"},
    "Current queue settings": {},
}
NAMING_FIELDS = {"client", "project", "stem", "preset", "index", "date"}


def projects_dir():
    path = get_app_data_dir() / "agency-projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_profile(profile):
    if not isinstance(profile, dict) or not str(profile.get("project", "")).strip():
        raise ValueError("Enter a project name")
    template = profile.get("naming", "{client}-{project}-{stem}-{index}")
    for _, field, specification, conversion in Formatter().parse(template):
        if field is not None and (field not in NAMING_FIELDS or conversion or specification):
            raise ValueError("Naming supports plain {client}, {project}, {stem}, {preset}, {index}, and {date}")
    colors = profile.get("colors", [])
    if not isinstance(colors, list) or any(not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors):
        raise ValueError("Brand colors must be #RRGGBB hex values")
    if not isinstance(profile.get("settings", {}), dict):
        raise ValueError("Project settings must be an object")
    from campaign_checks import delivery_rules
    delivery_rules(profile)
    if profile.get("preset", "Web images") not in PRESETS:
        raise ValueError("Choose a supported delivery preset")
    if profile.get('export_set', 'Single preset') not in {'Single preset','Social image set','Web + social images','Mixed client handoff'}:
        raise ValueError('Choose a supported export set')
    positions=profile.get('crop_positions',{})
    if not isinstance(positions,dict):raise ValueError('Invalid crop positions')
    import math
    for source,variants in positions.items():
        if not isinstance(source,str) or not isinstance(variants,dict):raise ValueError('Invalid crop positions')
        for preset,point in variants.items():
            if preset not in {'Social square','Social portrait','Social story'} or not isinstance(point,dict) or any(type(point.get(key)) not in (int,float) or not math.isfinite(point[key]) or not 0<=point[key]<=1 for key in ('x','y')) or any(not isinstance(point.get(key),str) or not re.fullmatch(r'[a-f0-9]{64}',point[key]) for key in ('source_sha256','settings_sha256')):raise ValueError('Invalid crop positions')
    identifier = str(profile.get("id", ""))
    if identifier and not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid project identifier")
    return profile


def save_profile(profile, directory=None):
    profile = dict(validate_profile(profile))
    profile.setdefault("version", 1)
    profile.setdefault("id", uuid.uuid4().hex)
    target = (directory or projects_dir()) / (profile["id"] + ".json")
    with StagedOutput(target, overwrite=True) as stage:
        stage.path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return stage.output


def load_profile(path):
    return validate_profile(json.loads(Path(path).read_text(encoding="utf-8")))


def list_profiles():
    profiles = []
    for path in projects_dir().glob("*.json"):
        try:
            profiles.append((path, load_profile(path)))
        except (OSError, ValueError):
            continue
    return sorted(profiles, key=lambda p: (p[1].get("client", ""), p[1]["project"]))


def delivery_name(profile, source, index):
    values = {"client": profile.get("client", ""), "project": profile["project"],
              "stem": source.stem, "preset": profile.get("preset", "Web images"),
              "index": str(index).zfill(3), "date": datetime.now().strftime("%Y-%m-%d")}
    name = profile.get("naming", "{client}-{project}-{stem}-{index}").format(**values)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name).strip(" .-")[:180]
    if not name or name.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "deliverable-" + str(index)
    return name


def run_project(profile, sources, output_dir, package=True, cancel_check=None, progress=None, include_brand=True):
    from headless_cli import _paths, convert_path
    from recipes import coerce_settings
    from archive_tools import build_delivery_package
    from studio_actions import StudioResult
    validate_profile(profile)
    paths = _paths([str(p) for p in sources])
    if not paths:
        raise ValueError("Choose supported files or a folder with supported files")
    settings = coerce_settings({**profile.get("settings", {}), **PRESETS[profile.get("preset", "Web images")]})
    settings["replace_source"] = False
    settings["overwrite"] = False
    from campaign_crops import SOCIAL_SIZES,social_settings,crop_position,social_rgb
    social=profile.get('preset') in SOCIAL_SIZES
    if social:settings=social_settings(profile,profile['preset'])
    logo = profile.get("logo", "")
    if profile.get("watermark"):
        if not logo or not Path(logo).is_file():
            raise ValueError("The brand logo is missing; choose it again")
        settings.update(enable_watermark=True, watermark_logo_path=logo)
    outputs, failures = [], []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(paths, 1):
        check_cancel(cancel_check)
        if progress:
            progress(f"{profile['project']}: {index}/{len(paths)} {source.name}")
        # Use the same conversions but publish only the project filename.
        import tempfile
        with tempfile.TemporaryDirectory(dir=output_dir, prefix=".shadow-project-") as td:
            result = convert_path(source, Path(td), settings)
            if result.status != "Completed":
                failures.append({"source": str(source), "error": result.error})
                continue
            check_cancel(cancel_check)
            with StagedOutput(output_dir / (delivery_name(profile, source, index) + ('.jpg' if social else result.output_path.suffix))) as stage:
                import shutil
                if social:
                    from PIL import Image, ImageOps
                    with Image.open(result.output_path) as image:
                        fitted = ImageOps.fit(social_rgb(image), SOCIAL_SIZES[profile["preset"]], method=Image.Resampling.LANCZOS,centering=crop_position(profile,source,profile['preset']))
                        fitted.save(stage.path, format="JPEG", quality=90, optimize=True)
                else:
                    shutil.copy2(result.output_path, stage.path)
            outputs.append(stage.output)
    converted = len(outputs)
    if include_brand and outputs and not failures and (profile.get("colors") or profile.get("fonts") or logo):
        brand = {"client": profile.get("client", ""), "project": profile["project"],
                 "colors": profile.get("colors", []), "fonts": profile.get("fonts", [])}
        if logo and Path(logo).is_file():
            with StagedOutput(output_dir / ("brand-logo" + Path(logo).suffix)) as stage:
                import shutil
                shutil.copy2(logo, stage.path)
            outputs.append(stage.output)
            brand["logo"] = stage.output.name
        with StagedOutput(output_dir / "brand-kit.json") as stage:
            stage.path.write_text(json.dumps(brand, indent=2), encoding="utf-8")
        outputs.append(stage.output)
    if package and outputs and not failures:
        archive = build_delivery_package(outputs, output_dir / (delivery_name(profile, Path("package"), 0) + ".zip"),
                                         client=profile.get("client", ""), project=profile["project"],
                                         cancel_check=cancel_check, progress=progress)
        outputs.append(archive)
    return StudioResult(outputs, {"converted": converted,
                                  "failures": failures}, not failures)
