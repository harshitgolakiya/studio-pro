from __future__ import annotations

import io
import os
import struct
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageCms


# ---------------------------------------------------------------------------
# ICC Profile Generation & Standards
# ---------------------------------------------------------------------------

def _to_s15fixed16(f: float) -> int:
    return int(round(f * 65536.0))


def _make_srgb_curv() -> bytes:
    """1024-sample IEC 61966-2.1 tone reproduction curve."""
    vals = bytearray()
    for i in range(1024):
        x = i / 1023.0
        if x <= 0.04045:
            y = x / 12.92
        else:
            y = ((x + 0.055) / 1.055) ** 2.4
        vals.extend(struct.pack(">H", int(round(max(0.0, min(1.0, y)) * 65535.0))))
    return b"curv\x00\x00\x00\x00" + struct.pack(">I", 1024) + vals


def _make_gamma_curv(gamma: float = 2.2) -> bytes:
    """Single-gamma curve type for ICC v2 profile."""
    gamma_u8f8 = int(round(gamma * 256.0))
    return b"curv\x00\x00\x00\x00\x00\x00\x00\x01" + struct.pack(">H", gamma_u8f8) + b"\x00\x00"


def build_matrix_rgb_profile(
    name: str,
    r_xyz: tuple[float, float, float],
    g_xyz: tuple[float, float, float],
    b_xyz: tuple[float, float, float],
    curve_bytes: bytes,
) -> bytes:
    """Build a compliant ICC v2.1 RGB matrix display/working-space profile."""
    tags: dict[bytes, bytes] = {}
    desc_str = name.encode("ascii", errors="replace")
    tags[b"desc"] = (
        b"desc\x00\x00\x00\x00"
        + struct.pack(">I", len(desc_str) + 1)
        + desc_str
        + b"\x00"
        + (b"\x00" * 16)
    )
    tags[b"cprt"] = b"text\x00\x00\x00\x00Public Domain / Shadow Media Studio\x00"
    tags[b"wtpt"] = b"XYZ \x00\x00\x00\x00" + struct.pack(
        ">iii", _to_s15fixed16(0.9642), _to_s15fixed16(1.0000), _to_s15fixed16(0.8249)
    )
    tags[b"rXYZ"] = b"XYZ \x00\x00\x00\x00" + struct.pack(
        ">iii", _to_s15fixed16(r_xyz[0]), _to_s15fixed16(r_xyz[1]), _to_s15fixed16(r_xyz[2])
    )
    tags[b"gXYZ"] = b"XYZ \x00\x00\x00\x00" + struct.pack(
        ">iii", _to_s15fixed16(g_xyz[0]), _to_s15fixed16(g_xyz[1]), _to_s15fixed16(g_xyz[2])
    )
    tags[b"bXYZ"] = b"XYZ \x00\x00\x00\x00" + struct.pack(
        ">iii", _to_s15fixed16(b_xyz[0]), _to_s15fixed16(b_xyz[1]), _to_s15fixed16(b_xyz[2])
    )
    tags[b"rTRC"] = curve_bytes
    tags[b"gTRC"] = curve_bytes
    tags[b"bTRC"] = curve_bytes

    tag_count = len(tags)
    header_size = 128
    tag_table_size = 4 + tag_count * 12
    offset = header_size + tag_table_size
    tag_table = struct.pack(">I", tag_count)
    tag_data = bytearray()

    for sig, data in tags.items():
        pad = (4 - (len(data) % 4)) % 4
        padded = data + (b"\x00" * pad)
        tag_table += sig + struct.pack(">II", offset + len(tag_data), len(data))
        tag_data.extend(padded)

    total_size = header_size + tag_table_size + len(tag_data)
    header = bytearray(128)
    struct.pack_into(">I", header, 0, total_size)
    header[4:8] = b"lcms"
    struct.pack_into(">I", header, 8, 0x02100000)  # ICC v2.1
    header[12:16] = b"mntr"
    header[16:20] = b"RGB "
    header[20:24] = b"XYZ "
    struct.pack_into(">HHHHHH", header, 24, 2026, 1, 1, 0, 0, 0)
    header[36:40] = b"acsp"
    header[40:44] = b"MSFT" if sys.platform == "win32" else b"APPL"
    struct.pack_into(
        ">iii", header, 68, _to_s15fixed16(0.9642), _to_s15fixed16(1.0000), _to_s15fixed16(0.8249)
    )
    header[80:84] = b"lcms"
    return bytes(header + tag_table + tag_data)


# Display P3 Bradford-adapted primaries to D50
_DISPLAY_P3_BYTES: bytes | None = None
_ADOBE_RGB_BYTES: bytes | None = None
_SRGB_BYTES: bytes | None = None


def get_srgb_profile_bytes() -> bytes:
    global _SRGB_BYTES
    if _SRGB_BYTES is None:
        prof = ImageCms.createProfile("sRGB")
        _SRGB_BYTES = ImageCms.ImageCmsProfile(prof).tobytes()
    return _SRGB_BYTES


def get_display_p3_profile_bytes() -> bytes:
    """Return ICC profile bytes for Display P3 (DCI-P3 primaries + sRGB transfer)."""
    global _DISPLAY_P3_BYTES
    if _DISPLAY_P3_BYTES is None:
        _DISPLAY_P3_BYTES = build_matrix_rgb_profile(
            "Display P3",
            (0.5151, 0.2412, -0.0011),
            (0.2919, 0.6922, 0.0419),
            (0.1571, 0.0666, 0.7841),
            _make_srgb_curv(),
        )
    return _DISPLAY_P3_BYTES


def get_adobe_rgb_profile_bytes() -> bytes:
    """Return ICC profile bytes for Adobe RGB (1998) (D50-adapted, gamma 2.2)."""
    global _ADOBE_RGB_BYTES
    if _ADOBE_RGB_BYTES is None:
        _ADOBE_RGB_BYTES = build_matrix_rgb_profile(
            "Adobe RGB (1998)",
            (0.60974, 0.31111, 0.01947),
            (0.20528, 0.62567, 0.06087),
            (0.14919, 0.06322, 0.74457),
            _make_gamma_curv(2.19921875),
        )
    return _ADOBE_RGB_BYTES


def find_system_cmyk_profile_path() -> Path | None:
    """Locate an available CMYK ICC profile from operating system standard paths."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        candidates.extend([
            Path(r"C:\Windows\System32\spool\drivers\color\RSWOP.icm"),
            Path(r"C:\Windows\System32\spool\drivers\color\USWebCoatedSWOP.icc"),
            Path(r"C:\Windows\System32\spool\drivers\color\CoatedFOGRA39.icc"),
        ])
    elif sys.platform == "darwin":
        candidates.extend([
            Path("/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc"),
            Path("/Library/ColorSync/Profiles/Generic CMYK Profile.icc"),
        ])
    else:
        candidates.extend([
            Path("/usr/share/color/icc/swop.icc"),
            Path("/usr/share/color/icc/fogra39.icc"),
        ])
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# Profile Inspection and Description
# ---------------------------------------------------------------------------

def get_image_profile(image: Image.Image) -> ImageCms.ImageCmsProfile | None:
    """Return the ImageCmsProfile embedded in the image, or None if untagged."""
    raw = image.info.get("icc_profile")
    if not raw:
        return None
    try:
        return ImageCms.ImageCmsProfile(io.BytesIO(raw))
    except Exception:
        return None


def describe_profile(profile_or_bytes: Any) -> str:
    """Return a clean human-readable name/description for an ICC profile."""
    if not profile_or_bytes:
        return "Untagged (Assumed sRGB)"
    try:
        if isinstance(profile_or_bytes, (bytes, bytearray)):
            prof = ImageCms.ImageCmsProfile(io.BytesIO(profile_or_bytes))
        else:
            prof = profile_or_bytes
        desc = ImageCms.getProfileDescription(prof).strip()
        if desc:
            return desc
        name = ImageCms.getProfileName(prof).strip()
        if name:
            return name
        return "Embedded ICC Profile"
    except Exception:
        return "Embedded Profile"


def is_wide_gamut(profile_or_bytes: Any) -> bool:
    """Return True if the profile appears to be wide-gamut (P3, Adobe RGB, ProPhoto, Rec2020)."""
    desc = describe_profile(profile_or_bytes).lower()
    return any(
        kw in desc
        for kw in ("p3", "display p3", "adobe", "adobergb", "prophoto", "rec2020", "bt.2020", "wide")
    )


# ---------------------------------------------------------------------------
# Rendering Intent Translation
# ---------------------------------------------------------------------------

INTENT_MAP = {
    "perceptual": ImageCms.Intent.PERCEPTUAL,
    "relative_colorimetric": ImageCms.Intent.RELATIVE_COLORIMETRIC,
    "saturation": ImageCms.Intent.SATURATION,
    "absolute_colorimetric": ImageCms.Intent.ABSOLUTE_COLORIMETRIC,
}


def parse_rendering_intent(intent: str | int) -> int:
    if isinstance(intent, int):
        return intent
    key = str(intent).strip().lower().replace(" ", "_")
    return INTENT_MAP.get(key, ImageCms.Intent.RELATIVE_COLORIMETRIC)


# ---------------------------------------------------------------------------
# Color Profile Conversions
# ---------------------------------------------------------------------------

def load_target_profile(
    mode: str,
    custom_path: str | Path | None = None,
) -> tuple[ImageCms.ImageCmsProfile | None, bytes | None, str]:
    """Resolve mode into (ImageCmsProfile, raw_bytes, display_label)."""
    key = str(mode or "preserve").strip().lower().replace(" ", "_")

    if key in ("srgb", "convert_to_srgb", "convert_to_srgb_(web_standard)"):
        p_bytes = get_srgb_profile_bytes()
        return ImageCms.ImageCmsProfile(io.BytesIO(p_bytes)), p_bytes, "sRGB"

    if key in ("display_p3", "p3", "convert_to_display_p3", "convert_to_display_p3_(wide_gamut)"):
        p_bytes = get_display_p3_profile_bytes()
        return ImageCms.ImageCmsProfile(io.BytesIO(p_bytes)), p_bytes, "Display P3"

    if key in ("adobe_rgb", "adobergb", "convert_to_adobe_rgb"):
        p_bytes = get_adobe_rgb_profile_bytes()
        return ImageCms.ImageCmsProfile(io.BytesIO(p_bytes)), p_bytes, "Adobe RGB"

    if key in ("cmyk", "convert_to_cmyk", "convert_to_cmyk_(print)"):
        cmyk_path = find_system_cmyk_profile_path()
        if cmyk_path:
            p_bytes = cmyk_path.read_bytes()
            return ImageCms.ImageCmsProfile(io.BytesIO(p_bytes)), p_bytes, "CMYK (SWOP/Standard)"
        # Fallback if no CMYK ICC on host
        return None, None, "CMYK"

    if key in ("custom", "custom_profile..."):
        if custom_path:
            p = Path(custom_path)
            if p.exists() and p.is_file():
                p_bytes = p.read_bytes()
                prof = ImageCms.ImageCmsProfile(io.BytesIO(p_bytes))
                return prof, p_bytes, describe_profile(prof)
        return None, None, "Custom (None)"

    return None, None, "Preserve (Source)"


def convert_color_profile(
    image: Image.Image,
    target_mode: str,
    custom_path: str | Path | None = None,
    intent: str | int = ImageCms.Intent.RELATIVE_COLORIMETRIC,
) -> tuple[Image.Image, bytes | None, str | None]:
    """Convert ``image`` to ``target_mode`` color profile.

    Returns:
        (converted_image, target_profile_bytes, status_note)
    """
    key = str(target_mode or "preserve").strip().lower().replace(" ", "_")
    if key in ("preserve", "preserve_(source)", "none", "untouched"):
        src_bytes = image.info.get("icc_profile")
        return image, src_bytes, None

    target_prof, target_bytes, label = load_target_profile(target_mode, custom_path)
    cms_intent = parse_rendering_intent(intent)

    # Resolve input profile
    src_prof = get_image_profile(image)
    if src_prof is None:
        # Default untagged RGB image to standard sRGB
        src_prof = ImageCms.createProfile("sRGB")

    # Handle CMYK target
    if key in ("cmyk", "convert_to_cmyk", "convert_to_cmyk_(print)"):
        if target_prof is not None:
            try:
                rgb_im = image.convert("RGB")
                cmyk_im = ImageCms.profileToProfile(
                    rgb_im,
                    src_prof,
                    target_prof,
                    renderingIntent=cms_intent,
                    outputMode="CMYK",
                )
                return cmyk_im, target_bytes, f"Converted to {label}"
            except Exception:
                pass
        # Fallback to standard Pillow RGB->CMYK separation
        cmyk_im = image.convert("CMYK")
        return cmyk_im, None, "Converted to CMYK"

    if target_prof is None:
        return image, image.info.get("icc_profile"), None

    try:
        # Check if source already matches target
        src_desc = describe_profile(src_prof).lower()
        if label.lower() in src_desc:
            return image, target_bytes, f"Kept in {label}"

        # Preserve alpha channel across transformation if present
        has_alpha = "A" in image.getbands()
        alpha_band = image.getchannel("A") if has_alpha else None

        rgb_im = image.convert("RGB")
        out_im = ImageCms.profileToProfile(
            rgb_im,
            src_prof,
            target_prof,
            renderingIntent=cms_intent,
            outputMode="RGB",
        )

        if has_alpha and alpha_band is not None:
            out_im = out_im.convert("RGBA")
            out_im.putalpha(alpha_band)

        return out_im, target_bytes, f"Converted to {label}"
    except Exception as e:
        # Graceful fallback: return original image with its original profile
        return image, image.info.get("icc_profile"), f"Color conversion warning: {e}"


# ---------------------------------------------------------------------------
# Gamut Clipping Analysis
# ---------------------------------------------------------------------------

def calculate_gamut_clipping(
    src_image: Image.Image,
    target_mode: str = "srgb",
    sample_max_edge: int = 400,
) -> float:
    """Calculate the percentage (0.0 to 100.0) of source pixels that get clipped

    when converted to ``target_mode`` (e.g. converting a wide-gamut image to sRGB).
    Uses pure-Pillow round-trip delta detection on a downsampled working copy.
    """
    src_prof = get_image_profile(src_image)
    if src_prof is None:
        # Untagged source is presumed sRGB, so clipping to sRGB is 0%
        return 0.0

    target_prof, _, _ = load_target_profile(target_mode)
    if target_prof is None:
        return 0.0

    try:
        w, h = src_image.size
        scale = min(1.0, sample_max_edge / max(w, h))
        if scale < 1.0:
            sw, sh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
            work_im = src_image.convert("RGB").resize((sw, sh), Image.Resampling.BILINEAR)
        else:
            work_im = src_image.convert("RGB")

        # Step 1: Forward transform (src -> target) with Relative Colorimetric (clips out-of-gamut)
        to_target = ImageCms.profileToProfile(
            work_im,
            src_prof,
            target_prof,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
        )

        # Step 2: Backward transform (target -> src)
        back_to_src = ImageCms.profileToProfile(
            to_target,
            target_prof,
            src_prof,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
        )

        # Step 3: Compute difference
        diff = ImageChops.difference(work_im, back_to_src)
        gray_diff = diff.convert("L")
        # Pixels with perceptible delta (> 5 in 0..255) were clipped outside gamut
        hist = gray_diff.histogram()
        total_pixels = sum(hist)
        clipped_pixels = sum(hist[6:])  # values 6 to 255
        return (clipped_pixels / max(1, total_pixels)) * 100.0
    except Exception:
        return 0.0
