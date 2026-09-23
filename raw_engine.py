"""Camera RAW development engine.

Provides professional camera sensor RAW development with rawpy (LibRaw)
and pure-Python embedded preview extraction fallback. Supports Canon (.cr2, .cr3),
Nikon (.nef, .nrw), Sony (.arw, .srf, .sr2), Fujifilm (.raf), Olympus (.orf),
Panasonic (.rw2), Pentax (.pef), Samsung (.srw), and Adobe (.dng).
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageFile

try:
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:
    rawpy = None  # type: ignore[assignment]
    _RAWPY_AVAILABLE = False

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]
    _NUMPY_AVAILABLE = False


RAW_EXTENSIONS: set[str] = {
    ".dng",
    ".cr2",
    ".cr3",
    ".nef",
    ".nrw",
    ".arw",
    ".srf",
    ".sr2",
    ".raf",
    ".orf",
    ".rw2",
    ".pef",
    ".raw",
    ".srw",
}

# Standard White Balance Multipliers [R, G, B, G] relative to daylight
WB_MULTIPLIERS: dict[str, list[float]] = {
    "daylight": [2.0, 1.0, 1.5, 1.0],      # ~5500K
    "cloudy": [2.2, 1.0, 1.3, 1.0],        # ~6500K
    "tungsten": [1.4, 1.0, 2.4, 1.0],      # ~3200K
    "fluorescent": [1.8, 1.0, 2.0, 1.0],   # ~4000K
}


def is_raw_file(path_or_suffix: Path | str) -> bool:
    """Return True if the file path or suffix is a recognized camera RAW format."""
    if isinstance(path_or_suffix, Path):
        ext = path_or_suffix.suffix.lower()
    else:
        s = str(path_or_suffix)
        ext = os.path.splitext(s)[1].lower() if "." in s else f".{s}".lower()
    return ext in RAW_EXTENSIONS


def is_rawpy_available() -> bool:
    """Return True if rawpy and numpy are installed."""
    return bool(_RAWPY_AVAILABLE and _NUMPY_AVAILABLE)


# ---------------------------------------------------------------------------
# Pure-Python Embedded Preview Extraction
# ---------------------------------------------------------------------------

def extract_embedded_preview(path_or_bytes: Path | str | bytes) -> Image.Image | None:
    """Extract embedded full-resolution/high-resolution JPEG preview from a RAW file.

    Modern camera RAW formats (Canon CR2/CR3, Nikon NEF, Sony ARW, Fuji RAF, etc.)
    always embed a high-quality JPEG stream within their container.
    """
    try:
        if isinstance(path_or_bytes, bytes):
            data = path_or_bytes
        else:
            with open(path_or_bytes, "rb") as f:
                data = f.read()
    except Exception:
        return None

    if not data or len(data) < 1024:
        return None

    # Scan for JPEG streams starting with SOI (\xFF\xD8\xFF) and ending with EOI (\xFF\xD9)
    best_image: Image.Image | None = None
    best_pixels: int = 0

    idx = 0
    data_len = len(data)
    while idx < data_len - 4:
        # Find start of image
        start = data.find(b"\xff\xd8\xff", idx)
        if start == -1:
            break

        # Find end of image after start
        end = data.find(b"\xff\xd9", start + 4)
        if end == -1:
            break
        end += 2  # Include \xFF\xD9

        candidate_bytes = data[start:end]
        if len(candidate_bytes) >= 128:  # Filter empty fragments
            try:
                candidate = Image.open(io.BytesIO(candidate_bytes), formats=["JPEG"])
                candidate.load()
                pixels = candidate.width * candidate.height
                if pixels > best_pixels:
                    best_pixels = pixels
                    best_image = candidate
            except Exception:
                pass

        idx = start + 4

    return best_image


# ---------------------------------------------------------------------------
# RAW Development Pipeline
# ---------------------------------------------------------------------------

def develop_raw(
    path_or_bytes: Path | str | bytes,
    wb: str = "camera",
    exposure: float = 0.0,
    demosaic: str = "auto",
    output_bps: int = 8,
) -> Image.Image:
    """Develop a camera RAW file to a standard RGB/RGBA PIL Image.

    Args:
        path_or_bytes: Path to camera RAW file or raw bytes.
        wb: White balance preset ('camera', 'auto', 'daylight', 'cloudy', 'tungsten', 'fluorescent').
        exposure: Exposure compensation bias in EV (-3.0 to +3.0).
        demosaic: Demosaic algorithm ('auto', 'ahd', 'bilinear', 'half_size').
        output_bps: Bits per channel in output image (8 or 16).

    Returns:
        Developed PIL Image in RGB (or I;16) mode.
    """
    wb_key = (wb or "camera").strip().lower().replace(" ", "_")
    demosaic_key = (demosaic or "auto").strip().lower()

    # 1. Primary Engine: rawpy (LibRaw)
    if is_rawpy_available():
        try:
            return _develop_with_rawpy(
                path_or_bytes,
                wb_key=wb_key,
                exposure=exposure,
                demosaic_key=demosaic_key,
                output_bps=output_bps,
            )
        except Exception:
            # Fall back to pure-Python extraction below
            pass

    # 2. Pure-Python Fallback Engine: High-res embedded preview extraction
    preview = extract_embedded_preview(path_or_bytes)
    if preview is not None:
        return _postprocess_fallback(preview, wb_key=wb_key, exposure=exposure)

    # 3. Direct Pillow open (restricted to standard non-RAW formats to avoid recursion)
    try:
        if isinstance(path_or_bytes, bytes):
            im = Image.open(io.BytesIO(path_or_bytes), formats=["TIFF", "JPEG", "PNG"])
        else:
            im = Image.open(path_or_bytes, formats=["TIFF", "JPEG", "PNG"])
        im.load()
        if im.mode not in ("RGB", "RGBA", "L", "I;16"):
            im = im.convert("RGB")
        return _postprocess_fallback(im, wb_key=wb_key, exposure=exposure)
    except Exception as err:
        raise ValueError(f"Unable to develop camera RAW file: {err}") from err


def _develop_with_rawpy(
    path_or_bytes: Path | str | bytes,
    wb_key: str,
    exposure: float,
    demosaic_key: str,
    output_bps: int,
) -> Image.Image:
    """Develop sensor RAW using LibRaw through rawpy."""
    if isinstance(path_or_bytes, bytes):
        raw_ctx = rawpy.imread(io.BytesIO(path_or_bytes))
    else:
        raw_ctx = rawpy.imread(str(path_or_bytes))

    with raw_ctx as raw:
        postprocess_kwargs: dict[str, Any] = {
            "output_bps": 16 if output_bps == 16 else 8,
            "output_color": rawpy.ColorSpace.sRGB,
        }

        # White balance configuration
        if wb_key in ("auto", "auto_wb"):
            postprocess_kwargs["use_auto_wb"] = True
        elif wb_key in WB_MULTIPLIERS:
            postprocess_kwargs["user_wb"] = WB_MULTIPLIERS[wb_key]
        else:
            # Default: use camera white balance as shot
            postprocess_kwargs["use_camera_wb"] = True

        # Demosaicing configuration
        if demosaic_key == "half_size":
            postprocess_kwargs["half_size"] = True
        elif demosaic_key == "bilinear":
            postprocess_kwargs["demosaic_algorithm"] = rawpy.DemosaicAlgorithm.LINEAR
        else:
            # Default / AHD: Adaptive Homogeneity-Directed
            postprocess_kwargs["demosaic_algorithm"] = rawpy.DemosaicAlgorithm.AHD

        # Exposure compensation
        if exposure != 0.0:
            # exp_shift is 2^EV factor
            postprocess_kwargs["exp_shift"] = 2.0 ** exposure
            postprocess_kwargs["exp_preserve_highlights"] = 0.75

        rgb_array = raw.postprocess(**postprocess_kwargs)
        return Image.fromarray(rgb_array)


def _postprocess_fallback(
    im: Image.Image,
    wb_key: str,
    exposure: float,
) -> Image.Image:
    """Apply white balance and exposure adjustments to a fallback or preview image."""
    # Convert to RGB if needed
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")

    # Apply White Balance color gain if not camera/default
    if wb_key in ("cloudy", "warm"):
        # Warm tint: slight red boost, blue attenuation
        im = _adjust_color_gains(im, r_gain=1.08, g_gain=1.0, b_gain=0.92)
    elif wb_key in ("tungsten", "cool"):
        # Cool tint: blue boost, red attenuation
        im = _adjust_color_gains(im, r_gain=0.88, g_gain=1.0, b_gain=1.14)
    elif wb_key == "fluorescent":
        im = _adjust_color_gains(im, r_gain=0.95, g_gain=1.04, b_gain=1.02)

    # Apply Exposure EV shift if non-zero
    if exposure != 0.0:
        try:
            from hdr_tone_map import apply_tone_mapping
            im = apply_tone_mapping(im, method="exposure", exposure=exposure)
        except Exception:
            pass

    return im


def _adjust_color_gains(
    im: Image.Image,
    r_gain: float,
    g_gain: float,
    b_gain: float,
) -> Image.Image:
    """Fast channel gain adjustment using Pillow point lookup tables."""
    r_lut = [min(255, max(0, int(round(i * r_gain)))) for i in range(256)]
    g_lut = [min(255, max(0, int(round(i * g_gain)))) for i in range(256)]
    b_lut = [min(255, max(0, int(round(i * b_gain)))) for i in range(256)]

    if im.mode == "RGB":
        return im.point(r_lut + g_lut + b_lut)
    elif im.mode == "RGBA":
        a_lut = list(range(256))
        return im.point(r_lut + g_lut + b_lut + a_lut)
    return im


# ---------------------------------------------------------------------------
# Metadata Extraction
# ---------------------------------------------------------------------------

def extract_raw_metadata(path_or_bytes: Path | str | bytes) -> dict[str, Any]:
    """Extract camera make, model, exposure, and shooting metadata."""
    meta: dict[str, Any] = {
        "make": "",
        "model": "",
        "camera_make": "",
        "camera_model": "",
        "iso": None,
        "shutter_speed": "",
        "exposure_time": "",
        "aperture": "",
        "f_number": "",
        "focal_length": "",
        "date_time": "",
        "datetime": "",
        "lens": "",
    }

    # 1. Try rawpy metadata if available
    if is_rawpy_available():
        try:
            if isinstance(path_or_bytes, bytes):
                raw_ctx = rawpy.imread(io.BytesIO(path_or_bytes))
            else:
                raw_ctx = rawpy.imread(str(path_or_bytes))
            with raw_ctx as raw:
                sizes = raw.sizes
                meta["width"] = sizes.width
                meta["height"] = sizes.height
                meta["raw_width"] = sizes.raw_width
                meta["raw_height"] = sizes.raw_height
                return meta
        except Exception:
            pass

    # 2. Try PIL EXIF extraction
    try:
        if isinstance(path_or_bytes, bytes):
            im = Image.open(io.BytesIO(path_or_bytes), formats=["TIFF", "JPEG", "PNG"])
        else:
            im = Image.open(path_or_bytes, formats=["TIFF", "JPEG", "PNG"])
        exif = im.getexif()
        if exif:
            make = str(exif.get(0x010F, "")).strip()
            model = str(exif.get(0x0110, "")).strip()
            dt = str(exif.get(0x0132, "")).strip()
            meta["make"] = make
            meta["camera_make"] = make
            meta["model"] = model
            meta["camera_model"] = model
            meta["date_time"] = dt
    except Exception:
        pass

    meta["camera_make"] = meta["make"]
    meta["camera_model"] = meta["model"]
    return meta


# ---------------------------------------------------------------------------
# Pillow Plugin Registration
# ---------------------------------------------------------------------------

class RawImageFile(ImageFile.ImageFile):
    """Pillow ImageFile plugin for transparently opening Camera RAW files."""

    format = "RAW"
    format_description = "Camera RAW"

    def _open(self) -> None:
        if self.filename:
            ext = os.path.splitext(self.filename)[1].lower()
            if ext not in RAW_EXTENSIONS:
                raise SyntaxError(f"Not a recognized camera RAW extension: {ext}")
        try:
            content = self.fp.read()
            target = self.filename if (getattr(self, "filename", None) and Path(self.filename).exists()) else content
            developed = develop_raw(target)
            self._mode = developed.mode
            self._size = developed.size
            self.im = developed.im
            self.readonly = 1
        except Exception as err:
            raise SyntaxError(f"Unable to develop camera RAW file: {err}") from err


_REGISTERED = False


def register_raw_opener() -> None:
    """Register Camera RAW formats with Pillow."""
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        Image.init()
        Image.register_open(RawImageFile.format, RawImageFile, None)
        for ext in RAW_EXTENSIONS:
            Image.register_extension(RawImageFile.format, ext.lower())
            Image.register_extension(RawImageFile.format, ext.upper())
        _REGISTERED = True
    except Exception:
        pass


# Register on import
register_raw_opener()
