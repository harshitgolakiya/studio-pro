"""What did this conversion silently throw away?

Compares a source file with its converted output and reports losses that
are easy to miss by eye: transparency flattened, animation collapsed to one
frame, 16-bit reduced to 8-bit, EXIF/GPS dropped (or GPS *retained* when the
user may have expected it gone), colour profile removed from a wide-gamut
source, truecolour reduced to a palette, and outputs larger than the input.
Also a pixel probe for the comparison view.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
from typing import Any

from PIL import Image

_GPS_IFD = 0x8825
_WIDE_GAMUT_HINTS = ("display p3", "p3", "adobe rgb", "adobergb", "prophoto", "rec2020", "rec. 2020", "bt.2020")
_HIGH_DEPTH_MODES = ("I", "F", "I;16", "I;16L", "I;16B", "I;16N")


@dataclass(frozen=True)
class LossWarning:
    severity: str  # "high" | "medium" | "info"
    title: str
    detail: str


@dataclass(frozen=True)
class ImageFacts:
    width: int
    height: int
    mode: str
    frames: int
    has_transparency: bool
    has_exif: bool
    has_gps: bool
    icc_name: str  # "" when there is no profile
    has_icc: bool
    size_bytes: int

    @property
    def wide_gamut(self) -> bool:
        name = self.icc_name.lower()
        return any(hint in name for hint in _WIDE_GAMUT_HINTS)


def _icc_name(icc: bytes | None) -> str:
    if not icc:
        return ""
    try:
        from PIL import ImageCms

        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return (ImageCms.getProfileDescription(profile) or "").strip()
    except Exception:
        return "embedded profile"


def _has_real_transparency(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA"):
        return im.getchannel("A").getextrema()[0] < 255
    if im.mode == "PA":
        return im.convert("RGBA").getchannel("A").getextrema()[0] < 255
    if "transparency" in im.info:
        return True
    return False


def gather_facts(path: Path) -> ImageFacts:
    with Image.open(path) as im:
        frames = int(getattr(im, "n_frames", 1) or 1)
        exif = im.getexif()
        has_gps = False
        try:
            has_gps = bool(exif.get_ifd(_GPS_IFD))
        except Exception:
            has_gps = _GPS_IFD in exif
        icc = im.info.get("icc_profile")
        return ImageFacts(
            width=im.width,
            height=im.height,
            mode=im.mode,
            frames=frames,
            has_transparency=_has_real_transparency(im),
            has_exif=bool(len(exif)),
            has_gps=has_gps,
            icc_name=_icc_name(icc),
            has_icc=bool(icc),
            size_bytes=path.stat().st_size,
        )


def compare_facts(src: ImageFacts, out: ImageFacts) -> list[LossWarning]:
    warnings: list[LossWarning] = []

    if src.has_transparency and not out.has_transparency:
        warnings.append(LossWarning("high", "Transparency lost", "The source has transparent pixels; the output is fully opaque (flattened onto a background)."))
    if src.frames > 1 and out.frames <= 1:
        warnings.append(LossWarning("high", "Animation lost", f"The source has {src.frames} frames; only one survived. Use WebP or GIF to keep animation."))
    if src.mode in _HIGH_DEPTH_MODES and out.mode not in _HIGH_DEPTH_MODES:
        warnings.append(LossWarning("medium", "Bit depth reduced", f"High-bit-depth source ({src.mode}) was reduced to 8 bits per channel ({out.mode})."))
    if src.mode not in ("P", "1", "L") and out.mode == "P":
        warnings.append(LossWarning("medium", "Reduced to a 256-colour palette", "Truecolour was quantised to an indexed palette; gradients may band."))
    if src.mode != "1" and out.mode == "1":
        warnings.append(LossWarning("medium", "Reduced to 1-bit monochrome", "Every pixel is now pure black or white."))

    if src.has_icc and not out.has_icc:
        if src.wide_gamut:
            warnings.append(LossWarning("high", "Wide-gamut colour profile removed", f"The source is tagged “{src.icc_name}” but the output has no profile, so viewers will assume sRGB and colours will look desaturated or shifted. Enable “Preserve metadata”."))
        else:
            warnings.append(LossWarning("info", "Colour profile removed", f"The embedded profile ({src.icc_name or 'ICC'}) was not carried over. Harmless for sRGB sources."))

    if src.has_exif and not out.has_exif:
        warnings.append(LossWarning("info", "EXIF metadata removed", "Camera, date and copyright fields are gone. Enable “Preserve metadata” to keep them."))
    if out.has_gps:
        warnings.append(LossWarning("medium", "GPS location retained", "The output still contains GPS coordinates. Enable “Strip EXIF & Camera GPS Metadata” before publishing."))

    if (src.width, src.height) != (out.width, out.height):
        warnings.append(LossWarning("info", "Resolution changed", f"{src.width}×{src.height} → {out.width}×{out.height} px."))
    if out.size_bytes > src.size_bytes:
        growth = (out.size_bytes - src.size_bytes) / max(1, src.size_bytes) * 100
        warnings.append(LossWarning("medium", "Output is larger than the source", f"The file grew by {growth:.0f}%. The source may already be well compressed, or the target format is lossless."))

    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(warnings, key=lambda w: order.get(w.severity, 3))


def audit_conversion(source_path: Path, output_path: Path | None) -> list[LossWarning]:
    if output_path is None or not Path(output_path).exists() or not Path(source_path).exists():
        return []
    try:
        return compare_facts(gather_facts(Path(source_path)), gather_facts(Path(output_path)))
    except Exception:
        return []


# -- pixel probe ---------------------------------------------------------

def display_to_source(x: int, y: int, display_size: tuple[int, int], source_size: tuple[int, int]) -> tuple[int, int] | None:
    """Map a point on the (scaled) preview to source pixel coordinates."""
    dw, dh = display_size
    sw, sh = source_size
    if dw <= 0 or dh <= 0 or not (0 <= x < dw and 0 <= y < dh):
        return None
    return min(sw - 1, int(x * sw / dw)), min(sh - 1, int(y * sh / dh))


def pixel_probe(original: Image.Image, converted: Image.Image | None, x: int, y: int) -> dict[str, Any] | None:
    """RGBA at (x, y) in source coordinates for both images, plus the per-channel delta."""
    if not (0 <= x < original.width and 0 <= y < original.height):
        return None
    a = original.convert("RGBA").getpixel((x, y))
    probe: dict[str, Any] = {"x": x, "y": y, "original": tuple(a)}
    if converted is not None:
        cx = min(converted.width - 1, int(x * converted.width / original.width))
        cy = min(converted.height - 1, int(y * converted.height / original.height))
        b = converted.convert("RGBA").getpixel((cx, cy))
        probe["converted"] = tuple(b)
        probe["delta"] = tuple(int(bv) - int(av) for av, bv in zip(a, b))
        probe["max_delta"] = max(abs(d) for d in probe["delta"])
    return probe


def format_probe(probe: dict[str, Any] | None) -> str:
    if not probe:
        return "Move the pointer over the image to inspect pixels"
    o = probe["original"]
    text = f"({probe['x']}, {probe['y']})   original RGBA {o[0]},{o[1]},{o[2]},{o[3]}  #{o[0]:02X}{o[1]:02X}{o[2]:02X}"
    if "converted" in probe:
        c, d = probe["converted"], probe["delta"]
        text += f"   →   output {c[0]},{c[1]},{c[2]},{c[3]}  #{c[0]:02X}{c[1]:02X}{c[2]:02X}   Δ {d[0]:+d},{d[1]:+d},{d[2]:+d},{d[3]:+d}"
    return text
