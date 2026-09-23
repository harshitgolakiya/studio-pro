"""Versioned processing recipes: named, portable snapshots of conversion settings.

A recipe file is JSON with a schema version so older files keep loading as
the settings model evolves. Loading always runs any needed migrations, then
coerces every field to its declared type and drops unknown keys, so a
hand-edited or foreign file can't put the UI into an inconsistent state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from settings import get_app_data_dir

RECIPE_SCHEMA_VERSION = 2
RECIPE_EXTENSION = ".shadow-recipe.json"

# Field -> (type, default). Only settings that describe *how* to convert are
# included; anything machine-specific (output folder) is deliberately left out
# so a recipe exported on one PC applies cleanly on another.
RECIPE_FIELDS: dict[str, tuple[type, Any]] = {
    "target_format": (str, "WEBP"),
    "quality": (int, 80),
    "lossless": (bool, False),
    "preserve_metadata": (bool, False),
    "strip_metadata": (bool, False),
    "slugify_names": (bool, False),
    "overwrite": (bool, False),
    "enable_target_size": (bool, False),
    "target_size_val": (str, "200"),
    "target_size_unit": (str, "KB"),
    "protect_quality": (bool, False),
    "min_ssim_text": (str, "0.95"),
    "enable_quality_target": (bool, False),
    "target_ssim_text": (str, "0.95"),
    "enable_resize": (bool, False),
    "max_dimension_text": (str, "1920"),
    "scale_percent_text": (str, "75"),
    "rotate_angle": (str, "0°"),
    "flip_h": (bool, False),
    "flip_v": (bool, False),
    "aspect_ratio": (str, "Original"),
    "enable_rounded": (bool, False),
    "corner_radius": (str, "20"),
    "grayscale": (bool, False),
    "normalize_audio": (bool, False),
    "filename_prefix": (str, ""),
    "filename_suffix": (str, ""),
    "enable_watermark": (bool, False),
    "watermark_type": (str, "text"),
    "watermark_text": (str, ""),
    "watermark_logo_path": (str, ""),
    "watermark_position": (str, "bottom-right"),
    "resize_condition": (str, "always"),
    "watermark_condition": (str, "always"),
    "color_profile_mode": (str, "preserve"),
    "color_profile_custom": (str, ""),
    "rendering_intent": (str, "relative_colorimetric"),
    "bit_depth": (str, "auto"),
    "hdr_tone_mapping": (str, "none"),
    "hdr_exposure": (float, 0.0),
    "raw_white_balance": (str, "camera"),
    "raw_exposure": (float, 0.0),
    "raw_demosaic": (str, "auto"),
    "svg_scale": (float, 1.0),
    "svg_background": (str, "transparent"),
    "psd_composite_mode": (str, "merged"),
    "psd_layer_index": (int, -1),
    "operation_order": (str, "color,rotate,flip,crop,grayscale,rounded,resize,watermark,tone_map"),
}


class RecipeError(ValueError):
    """Raised for unreadable, unsupported, or invalid recipe files."""


@dataclass
class Recipe:
    name: str
    settings: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    created: str = ""
    version: int = RECIPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.name = self.name.strip() or "Untitled recipe"
        self.settings = coerce_settings(self.settings)
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat(timespec="seconds")


def coerce_settings(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a complete settings dict with every field cast to its type."""
    out: dict[str, Any] = {}
    for key, (kind, default) in RECIPE_FIELDS.items():
        value = raw.get(key, default)
        try:
            if kind is bool:
                if isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "on")
                else:
                    value = bool(value)
            elif kind is int:
                value = int(float(value))
            elif kind is float:
                value = float(value)
            else:
                value = str(value)
        except (TypeError, ValueError):
            value = default
        out[key] = value
    out["quality"] = max(1, min(100, out["quality"]))
    rc = str(out.get("resize_condition", "always")).strip().lower().replace(" ", "_")
    if "4k" in rc:
        out["resize_condition"] = "only_above_4k"
    elif "2k" in rc:
        out["resize_condition"] = "only_above_2k"
    elif "larger" in rc:
        out["resize_condition"] = "only_if_larger"
    else:
        out["resize_condition"] = "always"

    wc = str(out.get("watermark_condition", "always")).strip().lower().replace(" ", "_").replace("≥", ">=")
    if "1200" in wc:
        out["watermark_condition"] = "only_if_>=_1200px"
    elif "800" in wc or "larger" in wc:
        out["watermark_condition"] = "only_if_>=_800px"
    else:
        out["watermark_condition"] = "always"

    cpm = str(out.get("color_profile_mode", "preserve")).strip().lower().replace(" ", "_")
    if "srgb" in cpm:
        out["color_profile_mode"] = "srgb"
    elif "p3" in cpm:
        out["color_profile_mode"] = "display_p3"
    elif "adobe" in cpm:
        out["color_profile_mode"] = "adobe_rgb"
    elif "cmyk" in cpm:
        out["color_profile_mode"] = "cmyk"
    elif "custom" in cpm:
        out["color_profile_mode"] = "custom"
    else:
        out["color_profile_mode"] = "preserve"

    ri = str(out.get("rendering_intent", "relative_colorimetric")).strip().lower().replace(" ", "_")
    if "perceptual" in ri:
        out["rendering_intent"] = "perceptual"
    elif "saturation" in ri:
        out["rendering_intent"] = "saturation"
    elif "absolute" in ri:
        out["rendering_intent"] = "absolute_colorimetric"
    else:
        out["rendering_intent"] = "relative_colorimetric"

    bd = str(out.get("bit_depth", "auto")).strip().lower()
    if "10" in bd:
        out["bit_depth"] = "10"
    elif "12" in bd:
        out["bit_depth"] = "12"
    elif "16" in bd:
        out["bit_depth"] = "16"
    elif "8" in bd:
        out["bit_depth"] = "8"
    else:
        out["bit_depth"] = "auto"

    htm = str(out.get("hdr_tone_mapping", "none")).strip().lower().replace(" ", "_")
    if "aces" in htm:
        out["hdr_tone_mapping"] = "aces"
    elif "reinhard" in htm:
        out["hdr_tone_mapping"] = "reinhard"
    elif "exposure" in htm:
        out["hdr_tone_mapping"] = "exposure"
    elif "hlg" in htm:
        out["hdr_tone_mapping"] = "hlg"
    elif "pq" in htm:
        out["hdr_tone_mapping"] = "pq"
    else:
        out["hdr_tone_mapping"] = "none"

    try:
        out["hdr_exposure"] = round(float(out.get("hdr_exposure", 0.0)), 2)
    except (ValueError, TypeError):
        out["hdr_exposure"] = 0.0

    rwb = str(out.get("raw_white_balance", "camera")).strip().lower().replace(" ", "_")
    if "auto" in rwb:
        out["raw_white_balance"] = "auto"
    elif "daylight" in rwb or "5500" in rwb:
        out["raw_white_balance"] = "daylight"
    elif "cloudy" in rwb or "6500" in rwb:
        out["raw_white_balance"] = "cloudy"
    elif "tungsten" in rwb or "3200" in rwb:
        out["raw_white_balance"] = "tungsten"
    elif "fluorescent" in rwb or "4000" in rwb:
        out["raw_white_balance"] = "fluorescent"
    else:
        out["raw_white_balance"] = "camera"

    rd = str(out.get("raw_demosaic", "auto")).strip().lower().replace(" ", "_")
    if "half" in rd:
        out["raw_demosaic"] = "half_size"
    elif "linear" in rd or "bilinear" in rd:
        out["raw_demosaic"] = "bilinear"
    elif "ahd" in rd:
        out["raw_demosaic"] = "ahd"
    else:
        out["raw_demosaic"] = "auto"

    try:
        out["raw_exposure"] = round(float(out.get("raw_exposure", 0.0)), 2)
    except (ValueError, TypeError):
        out["raw_exposure"] = 0.0

    try:
        raw_scale = raw.get("svg_scale", out.get("svg_scale", 1.0))
        scale_val = float(str(raw_scale).lower().replace("x", "").split()[0])
        out["svg_scale"] = round(max(0.05, min(32.0, scale_val)), 2)
    except (ValueError, TypeError, IndexError):
        out["svg_scale"] = 1.0

    raw_bg = str(raw.get("svg_background", out.get("svg_background", "transparent"))).strip().lower()
    if "white" in raw_bg:
        out["svg_background"] = "white"
    elif "black" in raw_bg:
        out["svg_background"] = "black"
    elif raw_bg.startswith("#"):
        out["svg_background"] = raw_bg
    else:
        out["svg_background"] = "transparent"

    # A hand-edited or older recipe may list unknown/partial steps.
    from converter import normalize_operation_order

    out["operation_order"] = ",".join(normalize_operation_order(out["operation_order"]))
    return out


# -- migrations ----------------------------------------------------------

def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """v1 files were a bare settings dict (plus optional 'name'); v2 wraps
    them in an envelope with metadata."""
    settings = {k: v for k, v in data.items() if k in RECIPE_FIELDS}
    if "format" in data and "target_format" not in settings:
        settings["target_format"] = data["format"]
    return {
        "version": 2,
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "created": data.get("created", ""),
        "settings": settings,
    }


_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migrate_v1_to_v2,
}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise RecipeError(f"Unrecognised recipe version: {version!r}")
    if version > RECIPE_SCHEMA_VERSION:
        raise RecipeError(
            f"This recipe was saved by a newer version of Shadow (schema {version}); "
            f"this build understands up to schema {RECIPE_SCHEMA_VERSION}."
        )
    while version < RECIPE_SCHEMA_VERSION:
        data = _MIGRATIONS[version](data)
        version = data["version"]
    return data


# -- (de)serialisation ---------------------------------------------------

def serialize_recipe(recipe: Recipe) -> dict[str, Any]:
    return {
        "version": RECIPE_SCHEMA_VERSION,
        "name": recipe.name,
        "description": recipe.description,
        "created": recipe.created,
        "settings": dict(recipe.settings),
    }


def parse_recipe(data: Any, fallback_name: str = "") -> Recipe:
    if not isinstance(data, dict):
        raise RecipeError("Recipe file must contain a JSON object.")
    data = migrate(dict(data))
    settings = data.get("settings")
    if not isinstance(settings, dict):
        raise RecipeError("Recipe file has no settings block.")
    return Recipe(
        name=str(data.get("name") or fallback_name),
        settings=settings,
        description=str(data.get("description") or ""),
        created=str(data.get("created") or ""),
        version=RECIPE_SCHEMA_VERSION,
    )


# -- storage -------------------------------------------------------------

def recipes_dir() -> Path:
    path = get_app_data_dir() / "recipes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def slug_for(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "recipe"


def recipe_path(name: str, directory: Path | None = None) -> Path:
    return (directory or recipes_dir()) / f"{slug_for(name)}{RECIPE_EXTENSION}"


def save_recipe(recipe: Recipe, directory: Path | None = None) -> Path:
    path = recipe_path(recipe.name, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialize_recipe(recipe), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_recipe(path: Path) -> Recipe:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RecipeError(f"Recipe not found: {path}")
    except (OSError, ValueError) as exc:
        raise RecipeError(f"Could not read recipe {Path(path).name}: {exc}")
    fallback = Path(path).name.replace(RECIPE_EXTENSION, "").replace("-", " ").title()
    return parse_recipe(data, fallback_name=fallback)


def list_recipes(directory: Path | None = None) -> list[Recipe]:
    """All readable recipes, alphabetical by name. Unreadable files are skipped."""
    found: list[Recipe] = []
    for path in sorted((directory or recipes_dir()).glob(f"*{RECIPE_EXTENSION}")):
        try:
            found.append(load_recipe(path))
        except RecipeError:
            continue
    return sorted(found, key=lambda r: r.name.lower())


def find_recipe(name: str, directory: Path | None = None) -> Recipe | None:
    path = recipe_path(name, directory)
    return load_recipe(path) if path.is_file() else None


def delete_recipe(name: str, directory: Path | None = None) -> bool:
    path = recipe_path(name, directory)
    if path.is_file():
        path.unlink()
        return True
    return False


def duplicate_recipe(name: str, new_name: str, directory: Path | None = None) -> Recipe:
    source = find_recipe(name, directory)
    if source is None:
        raise RecipeError(f"No recipe named {name!r}.")
    copy = Recipe(name=new_name, settings=dict(source.settings), description=source.description)
    save_recipe(copy, directory)
    return copy


def import_recipe(source_path: Path, directory: Path | None = None) -> Recipe:
    """Validate an external file and copy it into the library (re-serialised
    at the current schema, so imports are also upgrades)."""
    recipe = load_recipe(source_path)
    save_recipe(recipe, directory)
    return recipe


def export_recipe(name: str, destination: Path, directory: Path | None = None) -> Path:
    recipe = find_recipe(name, directory)
    if recipe is None:
        raise RecipeError(f"No recipe named {name!r}.")
    destination = Path(destination)
    if destination.is_dir():
        destination = destination / recipe_path(name).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(recipe_path(name, directory), destination)
    return destination
