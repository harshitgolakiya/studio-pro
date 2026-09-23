"""HDR tone mapping and high bit-depth processing engine.

Provides pure-Pillow tone curves and transfer functions (ACES Filmic, Extended
Reinhard, Linear Exposure, HLG, and PQ) along with bit-depth detection and codec
resolution for AVIF (10/12-bit), HEIF (10/12-bit), TIFF/PNG (16-bit), and 8-bit
web formats.
"""

from __future__ import annotations

import math
from typing import Sequence
from PIL import Image

# Supported bit depths per output format
FORMAT_BIT_DEPTHS: dict[str, list[int]] = {
    "AVIF": [8, 10, 12],
    "HEIC": [8, 10, 12],
    "HEIF": [8, 10, 12],
    "TIFF": [8, 16],
    "PNG": [8, 16],
    "WEBP": [8],
    "JPEG": [8],
    "JPG": [8],
    "GIF": [8],
    "BMP": [8],
    "ICO": [8],
    "ICNS": [8],
    "QOI": [8],
    "TGA": [8],
    "DDS": [8],
    "PPM": [8],
    "PDF": [8],
}

SUPPORTED_TONE_MAPPERS = ("none", "aces", "reinhard", "exposure", "hlg", "pq")


# ---------------------------------------------------------------------------
# Tone Mapping & Transfer Math Functions (Normalized [0.0, 1.0+] -> [0.0, 1.0])
# ---------------------------------------------------------------------------

def aces_filmic(x: float) -> float:
    """ACES Filmic tone curve (Krzysztof Narkowicz fit).

    Produces cinematic contrast, deep rich shadows, and soft highlight compression.
    """
    if x <= 0.0:
        return 0.0
    a = 2.51
    b = 0.03
    c = 2.43
    d = 0.59
    e = 0.14
    val = (x * (a * x + b)) / (x * (c * x + d) + e)
    return max(0.0, min(1.0, val))


def reinhard(x: float, white: float = 2.0) -> float:
    """Extended Reinhard tone reproduction curve with adjustable white point."""
    if x <= 0.0:
        return 0.0
    val = (x * (1.0 + x / (white * white))) / (1.0 + x)
    return max(0.0, min(1.0, val))


def linear_exposure(x: float, ev: float = 0.0) -> float:
    """Linear exposure adjustment scaled by 2^EV with smooth saturation roll-off."""
    if x <= 0.0:
        return 0.0
    scaled = x * (2.0 ** ev)
    if scaled <= 0.85:
        return max(0.0, min(1.0, scaled))
    # Soft shoulder above 0.85
    over = scaled - 0.85
    compressed = 0.85 + 0.15 * (1.0 - math.exp(-over / 0.35))
    return max(0.0, min(1.0, compressed))


def hlg_to_sdr(x: float) -> float:
    """ITU-R BT.2100 Hybrid Log-Gamma (HLG) optical conversion to SDR range."""
    if x <= 0.0:
        return 0.0
    a = 0.17883277
    b = 0.28466892
    c = 0.55991073
    if x <= 0.5:
        lin = (x * x) / 3.0
    else:
        lin = (math.exp((x - c) / a) + b) / 12.0
    # Map linear scene radiance into SDR range using ACES filmic rolloff
    return aces_filmic(lin * 2.5)


def pq_to_sdr(x: float) -> float:
    """SMPTE ST 2084 Perceptual Quantizer (PQ) optical conversion to SDR range."""
    if x <= 0.0:
        return 0.0
    m1 = 2610.0 / 16384.0
    m2 = (2523.0 / 4096.0) * 128.0
    c1 = 3424.0 / 4096.0
    c2 = (2413.0 / 4096.0) * 32.0
    c3 = (2392.0 / 4096.0) * 32.0

    v_p = x ** (1.0 / m2)
    num = max(0.0, v_p - c1)
    den = c2 - c3 * v_p
    lin = (num / den) ** (1.0 / m1) if den > 0 else 1.0
    # Scale from 10000-nit peak to standard 100-nit SDR display
    sdr_luminance = lin * 100.0
    return reinhard(sdr_luminance, white=3.0)


def evaluate_curve(
    val_norm: float,
    method: str = "aces",
    exposure_ev: float = 0.0,
) -> float:
    """Evaluate tone mapping and exposure for a normalized float value [0.0, 1.0+]."""
    method_key = (method or "none").strip().lower()
    
    # Pre-scale by exposure if specified
    if exposure_ev != 0.0:
        val_norm = val_norm * (2.0 ** exposure_ev)

    if method_key in ("aces", "aces_filmic"):
        return aces_filmic(val_norm)
    elif method_key in ("reinhard", "extended_reinhard"):
        return reinhard(val_norm)
    elif method_key in ("exposure", "exposure_boost"):
        return linear_exposure(val_norm, ev=0.0)
    elif method_key in ("hlg", "hlg_to_sdr"):
        return hlg_to_sdr(val_norm)
    elif method_key in ("pq", "pq_to_sdr"):
        return pq_to_sdr(val_norm)
    else:
        # None / linear clamp
        return max(0.0, min(1.0, val_norm))


# ---------------------------------------------------------------------------
# High Bit-Depth & HDR Detection
# ---------------------------------------------------------------------------

def is_high_bit_depth(image: Image.Image) -> bool:
    """Return True if image mode or info indicates >8-bit channel depth."""
    if image.mode in ("I;16", "I;16L", "I;16B", "I;16N", "I", "F"):
        return True
    # Check info or metadata tags if present
    bits = image.info.get("bits", 8)
    if isinstance(bits, int) and bits > 8:
        return True
    if isinstance(bits, (list, tuple)) and any(b > 8 for b in bits):
        return True
    return False


def get_image_bit_depth(image: Image.Image) -> int:
    """Return the bit depth per channel (e.g. 8, 10, 12, 16, 32)."""
    if image.mode in ("I;16", "I;16L", "I;16B", "I;16N"):
        return 16
    if image.mode in ("I", "F"):
        return 32
    bits = image.info.get("bits")
    if isinstance(bits, int):
        return bits
    if isinstance(bits, (list, tuple)) and bits:
        return max(bits)
    return 8


def supported_bit_depths(format_name: str) -> list[int]:
    """Return list of supported bit depths for given format name."""
    fmt = format_name.upper().strip()
    return FORMAT_BIT_DEPTHS.get(fmt, [8])


def resolve_target_bit_depth(
    source_image: Image.Image | None,
    requested: str | int,
    target_format: str,
) -> int:
    """Resolve the actual encoding bit depth for a given format and user request.

    Args:
        source_image: Optional source PIL image to infer source bit depth from.
        requested: 'auto', 8, 10, 12, 16 (or string equivalent).
        target_format: Target format (e.g. 'AVIF', 'HEIC', 'WEBP', 'PNG', 'TIFF').

    Returns:
        Integer bit depth supported by target_format (e.g. 8, 10, 12, 16).
    """
    valid_depths = supported_bit_depths(target_format)
    max_supported = max(valid_depths)

    req_str = str(requested).strip().lower()

    if req_str in ("auto", "", "default"):
        if source_image is not None:
            src_depth = get_image_bit_depth(source_image)
            if src_depth > 8:
                # Pick the closest supported bit depth that doesn't discard unnecessarily
                for d in sorted(valid_depths):
                    if d >= src_depth:
                        return d
                return max_supported
        return valid_depths[0]  # default to standard (8)

    # Explicit depth requested
    try:
        req_int = int(req_str)
    except ValueError:
        return 8

    if req_int in valid_depths:
        return req_int

    # Fallback to closest supported
    if req_int > max_supported:
        return max_supported
    # Pick lowest >= req_int or max available
    for d in sorted(valid_depths):
        if d >= req_int:
            return d
    return valid_depths[0]


# ---------------------------------------------------------------------------
# High Performance Image Tone Mapping
# ---------------------------------------------------------------------------

def apply_tone_mapping(
    image: Image.Image,
    method: str = "aces",
    exposure: float = 0.0,
) -> Image.Image:
    """Apply HDR transfer function and tone mapping curve to image.

    Args:
        image: PIL Image in RGB, RGBA, L, LA, or I;16 mode.
        method: Tone mapping algorithm ('none', 'aces', 'reinhard', 'exposure', 'hlg', 'pq').
        exposure: Exposure EV bias (-3.0 to +3.0).

    Returns:
        Tone-mapped PIL Image.
    """
    method_key = (method or "none").strip().lower()
    if method_key == "none" and exposure == 0.0:
        return image

    # 1. 16-bit / 32-bit single-channel image handling (I;16, I, F)
    if image.mode in ("I;16", "I;16L", "I;16B", "I;16N", "I"):
        return _tone_map_16bit(image, method_key, exposure)

    if image.mode == "F":
        # Convert float radiance to normalized I;16 then tone map
        im_i = image.convert("I")
        return _tone_map_16bit(im_i, method_key, exposure)

    # 2. Standard 8-bit channels (RGB, RGBA, L, LA) via C-level LUT
    # Build 256-entry lookup table for the curve
    lut_channel = [
        int(round(evaluate_curve(i / 255.0, method_key, exposure) * 255.0))
        for i in range(256)
    ]
    # Clamp safety
    lut_channel = [min(255, max(0, v)) for v in lut_channel]

    if image.mode == "L":
        return image.point(lut_channel)
    elif image.mode == "LA":
        # Keep alpha unchanged
        alpha_lut = list(range(256))
        return image.point(lut_channel + alpha_lut)
    elif image.mode == "RGB":
        return image.point(lut_channel * 3)
    elif image.mode == "RGBA":
        alpha_lut = list(range(256))
        return image.point((lut_channel * 3) + alpha_lut)
    else:
        # Fallback: convert to RGB or RGBA, apply, and return
        has_trans = "A" in image.getbands() or "transparency" in image.info
        target_mode = "RGBA" if has_trans else "RGB"
        converted = image.convert(target_mode)
        return apply_tone_mapping(converted, method, exposure)


def _tone_map_16bit(
    image: Image.Image,
    method: str,
    exposure: float,
) -> Image.Image:
    """Tone-map a 16-bit integer image to an 8-bit L channel using 65536 LUT."""
    # Ensure image is in I;16 format
    if image.mode != "I;16":
        image = image.convert("I;16")

    # Build 65536 8-bit lookup table
    lut_bytes = bytes(
        min(255, max(0, int(round(evaluate_curve(i / 65535.0, method, exposure) * 255.0))))
        for i in range(65536)
    )

    raw_bytes = image.tobytes()
    arr = memoryview(raw_bytes).cast("H")
    out_bytes = bytes(lut_bytes[val] for val in arr)
    return Image.frombytes("L", image.size, out_bytes)
