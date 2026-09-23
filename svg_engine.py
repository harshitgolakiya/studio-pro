"""SVG and SVGZ vector ingestion, inspection, and high-resolution rasterization engine."""
from __future__ import annotations

import gzip
import io
import os
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from PIL import Image, ImageColor, ImageDraw, ImageFile

try:
    import resvg_py

    _RESVG_AVAILABLE = True
except ImportError:
    _RESVG_AVAILABLE = False


SVG_EXTENSIONS: set[str] = {".svg", ".svgz"}

# Supported scale multipliers for UI / CLI presets
SVG_SCALE_OPTIONS: list[str] = [
    "1.0x (Default)",
    "1.5x",
    "2.0x (Retina)",
    "3.0x",
    "4.0x (Ultra HD)",
    "8.0x (Max Detail)",
]

# Supported background presets
SVG_BACKGROUND_OPTIONS: list[str] = [
    "Transparent",
    "White (#FFFFFF)",
    "Black (#000000)",
]


def is_resvg_available() -> bool:
    """Return True if the high-performance resvg_py engine is available."""
    return _RESVG_AVAILABLE


def is_svg_file(path_or_suffix: Path | str) -> bool:
    """Return True if the file path or suffix is a vector SVG or SVGZ format."""
    if isinstance(path_or_suffix, Path):
        ext = path_or_suffix.suffix.lower()
    else:
        ext = os.path.splitext(str(path_or_suffix))[1].lower()
        if not ext and str(path_or_suffix).startswith("."):
            ext = str(path_or_suffix).lower()
    return ext in SVG_EXTENSIONS


def normalize_svg_background(background: str | None) -> str | None:
    """Convert UI and preset background values to standard CSS colors or None."""
    if not background:
        return None
    bg_clean = str(background).strip().lower()
    if bg_clean in ("transparent", "none", "", "clear"):
        return None
    if bg_clean in ("white", "white (#ffffff)"):
        return "#ffffff"
    if bg_clean in ("black", "black (#000000)"):
        return "#000000"
    if bg_clean.startswith("#"):
        return bg_clean
    return background.strip()


def parse_svg_length(val: str | None, default: float = 100.0) -> float:
    """Convert CSS/SVG length strings (px, pt, in, cm, mm) to numeric pixels."""
    if not val:
        return default
    val = val.strip().lower()
    match = re.match(r"^([+-]?(?:\d+\.?\d*|\.\d+))([a-z%]*)$", val)
    if not match:
        return default
    num = float(match.group(1))
    unit = match.group(2)
    if unit == "pt":
        return num * 1.333
    if unit == "in":
        return num * 96.0
    if unit == "cm":
        return num * 37.795
    if unit == "mm":
        return num * 3.7795
    return num


def load_svg_string(path_or_bytes_or_str: Path | str | bytes) -> tuple[str, str | None]:
    """Read an SVG or SVGZ payload and return (svg_xml_string, file_path_if_exists)."""
    file_path: str | None = None
    if isinstance(path_or_bytes_or_str, (Path, str)):
        p = Path(path_or_bytes_or_str)
        if p.is_file():
            file_path = str(p.resolve())
            raw_bytes = p.read_bytes()
        else:
            if isinstance(path_or_bytes_or_str, str) and "<svg" in path_or_bytes_or_str:
                return path_or_bytes_or_str, None
            raw_bytes = str(path_or_bytes_or_str).encode("utf-8")
    else:
        raw_bytes = path_or_bytes_or_str

    # Decompress SVGZ (GZIP) if needed
    if raw_bytes[:2] == b"\x1f\x8b":
        raw_bytes = gzip.decompress(raw_bytes)

    try:
        svg_str = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        svg_str = raw_bytes.decode("latin-1", errors="replace")

    return svg_str, file_path


def extract_svg_metadata(path_or_bytes_or_str: Path | str | bytes) -> dict[str, Any]:
    """Extract viewBox, width, height, title, and description from SVG markup."""
    svg_str, _ = load_svg_string(path_or_bytes_or_str)
    meta: dict[str, Any] = {
        "width": 100,
        "height": 100,
        "viewBox": None,
        "title": "",
        "desc": "",
    }

    try:
        # Strip comments and parse XML
        root = ET.fromstring(svg_str)
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if tag.lower() != "svg":
            return meta

        attribs = {k.split("}")[-1]: v for k, v in root.attrib.items()}
        viewbox_str = attribs.get("viewBox") or attribs.get("viewbox")
        if viewbox_str:
            parts = [float(p) for p in re.split(r"[\s,]+", viewbox_str.strip()) if p]
            if len(parts) >= 4:
                meta["viewBox"] = tuple(parts[:4])
                meta["width"] = int(parts[2])
                meta["height"] = int(parts[3])

        if "width" in attribs:
            meta["width"] = int(parse_svg_length(attribs["width"], default=float(meta["width"])))
        if "height" in attribs:
            meta["height"] = int(parse_svg_length(attribs["height"], default=float(meta["height"])))

        # Title and Description children
        for child in root:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child_tag.lower() == "title" and child.text:
                meta["title"] = child.text.strip()
            elif child_tag.lower() == "desc" and child.text:
                meta["desc"] = child.text.strip()
    except Exception:
        pass

    return meta


def rasterize_svg(
    path_or_bytes_or_str: Path | str | bytes,
    scale: float = 1.0,
    background: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> Image.Image:
    """Rasterize an SVG or SVGZ vector file to a Pillow Image.Image with scale and background.

    Args:
        path_or_bytes_or_str: Path to .svg/.svgz file, raw SVG string, or bytes.
        scale: Resolution multiplier (e.g. 1.0, 2.0, 4.0).
        background: Canvas background ('transparent', '#ffffff', etc.).
        width: Optional fixed render width in pixels.
        height: Optional fixed render height in pixels.

    Returns:
        Pillow Image.Image (mode RGBA or RGB).
    """
    scale = max(0.05, min(32.0, float(scale)))
    bg_css = normalize_svg_background(background)
    svg_str, file_path = load_svg_string(path_or_bytes_or_str)

    # 1. Primary Engine: resvg_py (W3C-compliant Rust renderer)
    if is_resvg_available():
        try:
            kwargs: dict[str, Any] = {
                "zoom": scale,
                "shape_rendering": "geometric_precision",
                "text_rendering": "optimize_legibility",
                "image_rendering": "optimize_quality",
            }
            if bg_css:
                kwargs["background"] = bg_css
            if width is not None:
                kwargs["width"] = int(width)
            if height is not None:
                kwargs["height"] = int(height)

            # Prefer svg_string or svg_path
            png_bytes = resvg_py.svg_to_bytes(svg_string=svg_str, **kwargs)
            im = Image.open(io.BytesIO(png_bytes))
            im.load()
            return im
        except Exception:
            # Fall back to pure-Python engine if resvg fails on this input
            pass

    # 2. Pure-Python Fallback Engine
    return _rasterize_fallback(svg_str, scale=scale, background=bg_css, width=width, height=height)


def _rasterize_fallback(
    svg_str: str,
    scale: float = 1.0,
    background: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> Image.Image:
    """Pure-Python SVG rasterizer fallback using ElementTree and Pillow ImageDraw."""
    meta = extract_svg_metadata(svg_str)
    orig_w = meta["width"]
    orig_h = meta["height"]

    target_w = int(width) if width else max(1, int(round(orig_w * scale)))
    target_h = int(height) if height else max(1, int(round(orig_h * scale)))

    if background:
        try:
            bg_color = ImageColor.getrgb(background)
            if len(bg_color) == 3:
                im = Image.new("RGBA", (target_w, target_h), color=(*bg_color, 255))
            else:
                im = Image.new("RGBA", (target_w, target_h), color=bg_color)
        except Exception:
            im = Image.new("RGBA", (target_w, target_h), color=(0, 0, 0, 0))
    else:
        im = Image.new("RGBA", (target_w, target_h), color=(0, 0, 0, 0))

    draw = ImageDraw.Draw(im)
    sx = target_w / max(1.0, float(orig_w))
    sy = target_h / max(1.0, float(orig_h))

    try:
        root = ET.fromstring(svg_str)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
            attrs = {k.split("}")[-1].lower(): v for k, v in elem.attrib.items()}

            fill_val = attrs.get("fill", "black")
            stroke_val = attrs.get("stroke")
            fill_color = None
            stroke_color = None
            if fill_val not in ("none", "transparent", ""):
                try:
                    fill_color = ImageColor.getrgb(fill_val)
                except Exception:
                    fill_color = (0, 0, 0, 255)
            if stroke_val and stroke_val not in ("none", "transparent", ""):
                try:
                    stroke_color = ImageColor.getrgb(stroke_val)
                except Exception:
                    stroke_color = None

            if tag == "rect":
                x = parse_svg_length(attrs.get("x", "0")) * sx
                y = parse_svg_length(attrs.get("y", "0")) * sy
                w = parse_svg_length(attrs.get("width", "0")) * sx
                h = parse_svg_length(attrs.get("height", "0")) * sy
                draw.rectangle([x, y, x + w, y + h], fill=fill_color, outline=stroke_color)
            elif tag == "circle":
                cx = parse_svg_length(attrs.get("cx", "0")) * sx
                cy = parse_svg_length(attrs.get("cy", "0")) * sy
                r = parse_svg_length(attrs.get("r", "0")) * ((sx + sy) / 2.0)
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill_color, outline=stroke_color)
            elif tag == "ellipse":
                cx = parse_svg_length(attrs.get("cx", "0")) * sx
                cy = parse_svg_length(attrs.get("cy", "0")) * sy
                rx = parse_svg_length(attrs.get("rx", "0")) * sx
                ry = parse_svg_length(attrs.get("ry", "0")) * sy
                draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill_color, outline=stroke_color)
            elif tag == "line":
                x1 = parse_svg_length(attrs.get("x1", "0")) * sx
                y1 = parse_svg_length(attrs.get("y1", "0")) * sy
                x2 = parse_svg_length(attrs.get("x2", "0")) * sx
                y2 = parse_svg_length(attrs.get("y2", "0")) * sy
                draw.line([(x1, y1), (x2, y2)], fill=stroke_color or fill_color or (0, 0, 0, 255))
            elif tag in ("polygon", "polyline") and "points" in attrs:
                pts_str = attrs["points"].strip()
                coords = [float(c) for c in re.split(r"[\s,]+", pts_str) if c]
                if len(coords) >= 4:
                    pts = [(coords[i] * sx, coords[i + 1] * sy) for i in range(0, len(coords) - 1, 2)]
                    if tag == "polygon":
                        draw.polygon(pts, fill=fill_color, outline=stroke_color)
                    else:
                        draw.line(pts, fill=stroke_color or fill_color or (0, 0, 0, 255))
    except Exception:
        pass

    return im


# ---------------------------------------------------------------------------
# Pillow Plugin Registration
# ---------------------------------------------------------------------------

def _is_svg_header(prefix: bytes) -> bool:
    """Quick check for SVG / XML / gzip header."""
    p = prefix.lstrip()
    return p.startswith(b"<svg") or p.startswith(b"<?xml") or p.startswith(b"<!--") or prefix.startswith(b"\x1f\x8b")


class SvgImageFile(ImageFile.ImageFile):
    """Pillow ImagePlugin implementation for SVG vector files."""

    format = "SVG"
    format_description = "Scalable Vector Graphics"

    def _open(self) -> None:
        if self.filename:
            ext = os.path.splitext(self.filename)[1].lower()
            if ext not in SVG_EXTENSIONS:
                raise SyntaxError(f"Not an SVG vector format: {ext}")
        else:
            head = self.fp.read(512)
            self.fp.seek(0)
            if not _is_svg_header(head):
                raise SyntaxError("Not an SVG stream")
        try:
            target = self.filename if (getattr(self, "filename", None) and Path(self.filename).exists()) else self.fp.read()
            developed = rasterize_svg(target, scale=1.0)
            self._mode = developed.mode
            self._size = developed.size
            self.im = developed.im
            self.readonly = 1
        except Exception as err:
            raise SyntaxError(f"Unable to rasterize SVG file: {err}") from err


_REGISTERED = False


def register_svg_opener() -> None:
    """Register SVG format with Pillow."""
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        Image.init()
        Image.register_open(SvgImageFile.format, SvgImageFile, _is_svg_header)
        for ext in SVG_EXTENSIONS:
            Image.register_extension(SvgImageFile.format, ext.lower())
            Image.register_extension(SvgImageFile.format, ext.upper())
        _REGISTERED = True
    except Exception:
        pass


# Auto-register on import
register_svg_opener()
