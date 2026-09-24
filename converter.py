from __future__ import annotations

from dataclasses import dataclass
import io
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageSequence

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    # The dependency is included in release builds. Keeping imports resilient
    # gives source users a useful error only when they actually select HEIF.
    pass

try:
    import raw_engine
    from raw_engine import register_raw_opener, RAW_EXTENSIONS

    register_raw_opener()
except ImportError:
    RAW_EXTENSIONS = set()
    raw_engine = None

try:
    import svg_engine
    from svg_engine import register_svg_opener, SVG_EXTENSIONS

    register_svg_opener()
except ImportError:
    SVG_EXTENSIONS = set()
    svg_engine = None

try:
    import jxl_engine
    from jxl_engine import register_jxl_opener, is_jxl_available

    register_jxl_opener()
except ImportError:
    jxl_engine = None
    is_jxl_available = lambda: False

try:
    import psd_engine
except ImportError:
    psd_engine = None

import temp_tracker
from utils import (
    build_destination_filename,
    format_file_size,
    format_saved_percentage,
    reserve_output_path,
)
from watermark import apply_image_watermark, apply_text_watermark

SUPPORTED_EXTENSIONS = {
    # Common web and camera formats
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".webp",
    ".avif", ".avifs", ".heic", ".heif", ".hif", ".gif", ".jxl",
    # Vector graphics
    ".svg", ".svgz",
    # Professional Camera RAW formats
    ".dng", ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".raf", ".orf", ".rw2", ".pef", ".raw", ".srw",
    # Bitmaps, icons, and layered artwork
    ".bmp", ".dib", ".tiff", ".tif", ".ico", ".icns", ".cur", ".psd",
    # JPEG 2000 family
    ".jp2", ".j2k", ".j2c", ".jpc", ".jpf", ".jpx",
    # Texture and interchange formats
    ".dds", ".tga", ".icb", ".vda", ".vst", ".qoi", ".pcx", ".dcx",
    # Portable anymap and workstation formats
    ".ppm", ".pgm", ".pbm", ".pnm", ".pfm",
    ".sgi", ".rgb", ".rgba", ".bw", ".xbm", ".xpm", ".im", ".msp",
}

# User-facing name -> (file extension, Pillow encoder name). These are the
# general-purpose Pillow encoders that can reliably accept ordinary photos or
# artwork on Windows and macOS. Read-only/scientific plugins are input-only.
IMAGE_OUTPUT_FORMATS: dict[str, tuple[str, str]] = {
    "WEBP": (".webp", "WEBP"),
    "AVIF": (".avif", "AVIF"),
    "HEIC": (".heic", "HEIF"),
    "JXL": (".jxl", "JXL"),
    "JPEG": (".jpg", "JPEG"),
    "PNG": (".png", "PNG"),
    "GIF": (".gif", "GIF"),
    "BMP": (".bmp", "BMP"),
    "TIFF": (".tiff", "TIFF"),
    "JPEG 2000": (".jp2", "JPEG2000"),
    "TGA": (".tga", "TGA"),
    "DDS": (".dds", "DDS"),
    "QOI": (".qoi", "QOI"),
    "PPM": (".ppm", "PPM"),
    "PCX": (".pcx", "PCX"),
    "ICO": (".ico", "ICO"),
    "ICNS": (".icns", "ICNS"),
    "SGI": (".sgi", "SGI"),
    "XBM": (".xbm", "XBM"),
    "PDF": (".pdf", "PDF"),
}

IMAGE_FORMAT_CAPABILITIES: dict[str, dict[str, object]] = {
    "WEBP": {"category": "Modern web", "description": "Excellent web compression with transparency and animation.", "badges": ("Alpha", "Animation", "Lossy", "Lossless", "Metadata")},
    "AVIF": {"category": "Modern web", "description": "Very small modern files for photos and web delivery.", "badges": ("Alpha", "Animation", "High efficiency")},
    "HEIC": {"category": "Photography", "description": "High-efficiency Apple and mobile photography format.", "badges": ("Alpha", "Metadata", "High efficiency")},
    "JXL": {"category": "Modern web", "description": "Next-generation JPEG XL with high fidelity, HDR, and lossless support.", "badges": ("Alpha", "Lossless", "Lossy", "HDR", "High efficiency")},
    "JPEG": {"category": "Web & photo", "description": "Universal photographic output with progressive encoding.", "badges": ("Universal", "Lossy", "Metadata")},
    "PNG": {"category": "Web & design", "description": "Lossless artwork, screenshots, and transparent graphics.", "badges": ("Alpha", "Lossless", "Web")},
    "GIF": {"category": "Animation", "description": "Widely compatible indexed-color animation.", "badges": ("Animation", "Transparency", "Indexed")},
    "BMP": {"category": "Legacy", "description": "Uncompressed Windows bitmap for maximum compatibility.", "badges": ("Lossless", "Windows", "Large files")},
    "TIFF": {"category": "Professional", "description": "Lossless archival, print, scanning, and publishing output.", "badges": ("Alpha", "Lossless", "Print")},
    "JPEG 2000": {"category": "Professional", "description": "Wavelet-based archival and specialist imaging format.", "badges": ("Alpha", "Lossless", "Wavelet")},
    "TGA": {"category": "Texture & game", "description": "Simple alpha-capable texture and interchange format.", "badges": ("Alpha", "Lossless", "Texture")},
    "DDS": {"category": "Texture & game", "description": "GPU texture container used by games and 3D tools.", "badges": ("Alpha", "GPU texture", "Game")},
    "QOI": {"category": "Modern lossless", "description": "Fast, simple lossless image format with alpha support.", "badges": ("Alpha", "Lossless", "Fast")},
    "PPM": {"category": "Technical", "description": "Portable uncompressed RGB interchange format.", "badges": ("Lossless", "Uncompressed", "Technical")},
    "PCX": {"category": "Legacy", "description": "Legacy paint and publishing bitmap format.", "badges": ("Lossless", "Legacy")},
    "ICO": {"category": "Icons", "description": "Multi-resolution Windows icons and favicons.", "badges": ("Alpha", "Multi-size", "Windows")},
    "ICNS": {"category": "Icons", "description": "Multi-resolution macOS application icon format.", "badges": ("Alpha", "Multi-size", "macOS")},
    "SGI": {"category": "Technical", "description": "Silicon Graphics workstation and texture format.", "badges": ("Alpha", "Lossless", "Legacy")},
    "XBM": {"category": "Legacy", "description": "Monochrome X11 bitmap source format.", "badges": ("Monochrome", "X11", "Legacy")},
    "PDF": {"category": "Document", "description": "Package one image or a complete batch as a document.", "badges": ("Document", "Multi-page", "Portable")},
}

LOSSY_IMAGE_FORMATS = {"WEBP", "AVIF", "HEIC", "JPEG", "JXL"}


def normalize_output_format(value: str) -> str:
    """Return a canonical IMAGE_OUTPUT_FORMATS key for a UI/API value."""
    fmt = value.upper().strip()
    aliases = {
        "JPG": "JPEG",
        "JPEG / JPG": "JPEG",
        "JPG / JPEG": "JPEG",
        "JPE": "JPEG",
        "JFIF": "JPEG",
        "HEIF": "HEIC",
        "HIF": "HEIC",
        "JP2": "JPEG 2000",
        "JPEG2000": "JPEG 2000",
        "JPEGXL": "JXL",
        "JPEG-XL": "JXL",
        ".JXL": "JXL",
        "TIF": "TIFF",
        "PDF (COMBINED)": "PDF",
    }
    return aliases.get(fmt, fmt)


@dataclass
class ConversionResult:
    source_path: Path
    output_path: Path | None
    original_size: int | None
    output_size: int | None
    saved: str
    status: str
    error: str | None = None
    width: int | None = None
    height: int | None = None
    note: str | None = None  # e.g. why the size solver overshot its target

    @property
    def original_size_text(self) -> str:
        return format_file_size(self.original_size)

    @property
    def output_size_text(self) -> str:
        return format_file_size(self.output_size)


def solve_target_size_quality(
    image: Image.Image,
    target_bytes: int,
    fmt: str = "WEBP",
    save_kwargs: dict | None = None,
) -> int:
    """Binary search over compression quality (1-95) to hit target byte size."""
    kwargs = dict(save_kwargs or {})
    low, high = 5, 95
    best_quality: int | None = None
    smallest_quality_seen: int | None = None
    smallest_size_seen: int | None = None

    for _ in range(7):  # 7 iterations yields 1-quality-step accuracy
        mid = (low + high) // 2
        kwargs["quality"] = mid
        buf = io.BytesIO()
        try:
            image.save(buf, format=fmt, **kwargs)
            size = buf.tell()
        except Exception:
            break

        if smallest_size_seen is None or size < smallest_size_seen:
            smallest_size_seen = size
            smallest_quality_seen = mid

        if size <= target_bytes:
            best_quality = mid
            low = mid + 1
        else:
            high = mid - 1

    if best_quality is not None:
        return best_quality
    # Target size could not be reached even at the lowest quality tried.
    # Use the smallest result we actually produced instead of silently
    # falling back to a high default quality that overshoots the target.
    return smallest_quality_seen if smallest_quality_seen is not None else 5


def _encode_and_measure(
    image: Image.Image,
    fmt: str,
    quality: int,
    save_kwargs: dict | None = None,
) -> tuple[int, float]:
    """Encode in memory at ``quality``; return (bytes, SSIM vs. the input)."""
    from metrics import ssim_downscaled

    buf = io.BytesIO()
    image.save(buf, format=fmt, quality=quality, **(save_kwargs or {}))
    size = buf.getbuffer().nbytes
    buf.seek(0)
    decoded = Image.open(buf)
    decoded.load()
    return size, ssim_downscaled(image, decoded)


def solve_quality_for_ssim(
    image: Image.Image,
    target_ssim: float,
    fmt: str = "WEBP",
    save_kwargs: dict | None = None,
) -> tuple[int, float]:
    """Lowest quality (5-95) whose SSIM meets ``target_ssim``; if none does,
    the highest-SSIM quality tried. Returns (quality, achieved_ssim)."""
    low, high = 5, 95
    best: tuple[int, float] | None = None
    highest: tuple[int, float] | None = None
    for _ in range(7):
        mid = (low + high) // 2
        try:
            _size, ssim = _encode_and_measure(image, fmt, mid, save_kwargs)
        except Exception:
            break
        if highest is None or ssim > highest[1]:
            highest = (mid, ssim)
        if ssim >= target_ssim:
            best = (mid, ssim)
            high = mid - 1
        else:
            low = mid + 1
    return best or highest or (95, 1.0)


# The processing stack. Each name is one step; the order is user-reorderable
# (see the "Processing stack" panel) and stored in recipes.
DEFAULT_OPERATION_ORDER: tuple[str, ...] = (
    "color", "rotate", "flip", "crop", "grayscale", "rounded", "resize", "watermark", "tone_map",
)
OPERATION_LABELS: dict[str, str] = {
    "color": "Color Management",
    "rotate": "Rotate",
    "flip": "Flip",
    "crop": "Aspect-ratio crop",
    "grayscale": "Grayscale",
    "rounded": "Rounded corners",
    "resize": "Resize",
    "watermark": "Watermark",
    "tone_map": "HDR & Tone Mapping",
}

ResizeSpec = tuple  # (scale_percent | None, max_width | None, max_height | None)


def normalize_operation_order(order: object) -> tuple[str, ...]:
    """Return a complete, valid order: unknown names dropped, duplicates
    collapsed, anything missing appended in its default position."""
    if isinstance(order, str):
        names = [part.strip().lower() for part in order.split(",")]
    elif order:
        names = [str(part).strip().lower() for part in order]  # type: ignore[union-attr]
    else:
        names = []
    seen: list[str] = []
    for name in names:
        if name in DEFAULT_OPERATION_ORDER and name not in seen:
            seen.append(name)
    for name in DEFAULT_OPERATION_ORDER:
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def compute_resize_dims(
    size: tuple[int, int],
    scale_percent: float | None = None,
    max_width: int | None = None,
    max_height: int | None = None,
    condition: str = "always",
) -> tuple[int, int] | None:
    """Proportional target size for an image of ``size``, or None if no resize is needed.
    Supports conditional resizing: 'always', 'only_if_larger', 'only_above_4k', 'only_above_2k'.
    """
    w, h = size
    cond = str(condition or "always").strip().lower().replace(" ", "_").replace(">", "above_")

    if cond in ("only_above_4k", "above_4k"):
        # 4K UHD: 3840x2160 (~8.29 MP). Check both max dimension and total pixels.
        if max(w, h) < 3840 and (w * h) < 8_294_400:
            return None
    elif cond in ("only_above_2k", "above_2k"):
        # 2K/QHD: 2560x1440 (~3.68 MP).
        if max(w, h) < 2560 and (w * h) < 3_686_400:
            return None
    elif cond == "only_if_larger":
        # Only downscale if the image actually exceeds max_width or max_height
        if max_width and w <= max_width and max_height and h <= max_height:
            return None
        if max_width and not max_height and w <= max_width:
            return None
        if max_height and not max_width and h <= max_height:
            return None
        if scale_percent is not None and scale_percent >= 100:
            return None

    if scale_percent is not None and 1 <= scale_percent < 100:
        return max(1, int(round(w * scale_percent / 100.0))), max(1, int(round(h * scale_percent / 100.0)))
    if (max_width and w > max_width) or (max_height and h > max_height):
        ratio = min((max_width or w) / w, (max_height or h) / h)
        return max(1, int(round(w * ratio))), max(1, int(round(h * ratio)))
    return None


def apply_image_transformations(
    image: Image.Image,
    rotate_angle: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
    aspect_ratio: str | None = None,
    corner_radius: int = 0,
    grayscale: bool = False,
    resize_spec: ResizeSpec | None = None,
    watermark_fn: object = None,
    order: object = None,
    resize_condition: str = "always",
    watermark_condition: str = "always",
    color_profile_mode: str = "preserve",
    color_profile_custom: str = "",
    rendering_intent: str = "relative_colorimetric",
    hdr_tone_mapping: str = "none",
    hdr_exposure: float = 0.0,
) -> Image.Image:
    """Run the processing stack in ``order`` (default: color, rotate, flip, crop,
    grayscale, rounded, resize, watermark, tone_map).

    Resize dimensions are computed from the image *as it arrives at the
    resize step*, so a crop or rotation earlier in the stack can never be
    stretched back to the source's proportions.
    """

    def step_color(im: Image.Image) -> Image.Image:
        if not color_profile_mode or str(color_profile_mode).strip().lower() in ("preserve", "preserve_(source)", "none", "untouched"):
            return im
        try:
            from color_manager import convert_color_profile
            out_im, _, _ = convert_color_profile(
                im,
                target_mode=color_profile_mode,
                custom_path=color_profile_custom,
                intent=rendering_intent,
            )
            return out_im
        except Exception:
            return im

    def step_rotate(im: Image.Image) -> Image.Image:
        if rotate_angle == 90:
            return im.transpose(Image.Transpose.ROTATE_270)
        if rotate_angle == 180:
            return im.transpose(Image.Transpose.ROTATE_180)
        if rotate_angle == 270:
            return im.transpose(Image.Transpose.ROTATE_90)
        if rotate_angle != 0:
            return im.rotate(-rotate_angle, expand=True, resample=Image.Resampling.BICUBIC)
        return im

    def step_flip(im: Image.Image) -> Image.Image:
        if flip_h:
            im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if flip_v:
            im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        return im

    def step_crop(im: Image.Image) -> Image.Image:
        if not (aspect_ratio and ":" in aspect_ratio):
            return im
        try:
            parts = aspect_ratio.split(":")
            rw, rh = float(parts[0]), float(parts[1])
            if rw > 0 and rh > 0:
                cur_w, cur_h = im.size
                target_ratio = rw / rh
                cur_ratio = cur_w / cur_h
                if cur_ratio > target_ratio:
                    new_w = max(1, int(round(cur_h * target_ratio)))
                    left = (cur_w - new_w) // 2
                    return im.crop((left, 0, left + new_w, cur_h))
                if cur_ratio < target_ratio:
                    new_h = max(1, int(round(cur_w / target_ratio)))
                    top = (cur_h - new_h) // 2
                    return im.crop((0, top, cur_w, top + new_h))
        except Exception:
            pass
        return im

    def step_grayscale(im: Image.Image) -> Image.Image:
        if not grayscale:
            return im
        has_alpha = "A" in im.getbands() or "transparency" in im.info
        if has_alpha:
            rgba = im.convert("RGBA")
            a = rgba.getchannel("A")
            gray = rgba.convert("L")
            return Image.merge("RGBA", (gray, gray, gray, a))
        return im.convert("L").convert("RGB")

    def step_rounded(im: Image.Image) -> Image.Image:
        if corner_radius <= 0:
            return im
        w, h = im.size
        rad = min(corner_radius, min(w, h) // 2)
        if rad <= 0:
            return im
        im = im.convert("RGBA")
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (w, h)], radius=rad, fill=255)
        im.putalpha(ImageChops.multiply(mask, im.getchannel("A")))
        return im

    def step_resize(im: Image.Image) -> Image.Image:
        if not resize_spec:
            return im
        dims = compute_resize_dims(im.size, *resize_spec, condition=resize_condition)
        return im.resize(dims, Image.Resampling.LANCZOS) if dims else im

    def step_watermark(im: Image.Image) -> Image.Image:
        if not callable(watermark_fn):
            return im
        w_cond = str(watermark_condition or "always").strip().lower().replace(" ", "_").replace("≥", ">=")
        if ("800" in w_cond or w_cond in ("only_if_larger", "only_if_>=_800px")) and max(im.size) < 800:
            return im
        if ("1200" in w_cond or w_cond == "only_if_>=_1200px") and max(im.size) < 1200:
            return im
        return watermark_fn(im)

    def step_tone_map(im: Image.Image) -> Image.Image:
        if (not hdr_tone_mapping or str(hdr_tone_mapping).strip().lower() in ("none", "direct")) and hdr_exposure == 0.0:
            return im
        try:
            from hdr_tone_map import apply_tone_mapping
            return apply_tone_mapping(im, method=hdr_tone_mapping, exposure=hdr_exposure)
        except Exception:
            return im

    steps = {
        "color": step_color,
        "rotate": step_rotate,
        "flip": step_flip,
        "crop": step_crop,
        "grayscale": step_grayscale,
        "rounded": step_rounded,
        "resize": step_resize,
        "watermark": step_watermark,
        "tone_map": step_tone_map,
    }
    im = image
    for name in normalize_operation_order(order):
        im = steps[name](im)
    return im


def _make_watermark_fn(
    watermark_logo_path: str,
    watermark_text: str,
    watermark_position: str,
    watermark_scale_pct: float,
    watermark_opacity: float,
):
    """Closure applying the configured watermark, or None when there isn't one."""
    if watermark_logo_path and Path(watermark_logo_path).is_file():
        return lambda im: apply_image_watermark(
            im,
            logo_path=watermark_logo_path,
            position=watermark_position,
            scale_pct=watermark_scale_pct,
            opacity=watermark_opacity,
        )
    if watermark_text.strip():
        return lambda im: apply_text_watermark(
            im, text=watermark_text, position=watermark_position, opacity=watermark_opacity
        )
    return None


def flatten_to_rgb(image: Image.Image, background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Composite any transparency onto a solid background before dropping the alpha channel.

    A bare ``.convert("RGB")`` on an RGBA/P-with-transparency image does not
    blend the alpha channel -- it just discards it, which turns transparent
    pixels black in formats that can't carry transparency (JPEG, PDF).
    """
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flattened = Image.new("RGB", rgba.size, background)
        flattened.paste(rgba, mask=rgba.getchannel("A"))
        return flattened
    return image.convert("RGB")


def _process_frame_image(
    frame: Image.Image,
    resize_spec: ResizeSpec | None = None,
    watermark_logo_path: str = "",
    watermark_scale_pct: float = 0.20,
    watermark_position: str = "bottom-right",
    watermark_opacity: float = 0.7,
    watermark_text: str = "",
    rotate_angle: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
    aspect_ratio: str | None = None,
    corner_radius: int = 0,
    grayscale: bool = False,
    operation_order: object = None,
    resize_condition: str = "always",
    watermark_condition: str = "always",
    color_profile_mode: str = "preserve",
    color_profile_custom: str = "",
    rendering_intent: str = "relative_colorimetric",
    hdr_tone_mapping: str = "none",
    hdr_exposure: float = 0.0,
    bit_depth: str = "auto",
) -> Image.Image:
    f = apply_image_transformations(
        frame.copy(),
        rotate_angle=rotate_angle,
        flip_h=flip_h,
        flip_v=flip_v,
        aspect_ratio=aspect_ratio,
        corner_radius=corner_radius,
        grayscale=grayscale,
        resize_spec=resize_spec,
        watermark_fn=_make_watermark_fn(
            watermark_logo_path, watermark_text, watermark_position,
            watermark_scale_pct, watermark_opacity,
        ),
        order=operation_order,
        resize_condition=resize_condition,
        watermark_condition=watermark_condition,
        color_profile_mode=color_profile_mode,
        color_profile_custom=color_profile_custom,
        rendering_intent=rendering_intent,
        hdr_tone_mapping=hdr_tone_mapping,
        hdr_exposure=hdr_exposure,
    )
    if f.mode not in ("RGB", "RGBA"):
        has_trans = "A" in f.getbands() or "transparency" in f.info
        f = f.convert("RGBA" if has_trans else "RGB")
    return f


def convert_image(
    source_path: Path,
    output_directory: Path,
    quality: int = 80,
    overwrite: bool = False,
    reserved_paths: set[Path] | None = None,
    lossless: bool = False,
    preserve_metadata: bool = False,
    max_width: int | None = None,
    max_height: int | None = None,
    scale_percent: float | None = None,
    target_format: str = "WEBP",
    target_kb: int | None = None,
    watermark_text: str = "",
    watermark_logo_path: str = "",
    watermark_scale_pct: float = 0.20,
    watermark_position: str = "bottom-right",
    watermark_opacity: float = 0.7,
    strip_metadata: bool = False,
    slugify_names: bool = False,
    filename_prefix: str = "",
    filename_suffix: str = "",
    rotate_angle: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
    aspect_ratio: str | None = None,
    corner_radius: int = 0,
    grayscale: bool = False,
    min_ssim: float | None = None,
    target_ssim: float | None = None,
    operation_order: object = None,
    resize_condition: str = "always",
    watermark_condition: str = "always",
    color_profile_mode: str = "preserve",
    color_profile_custom: str = "",
    rendering_intent: str = "relative_colorimetric",
    bit_depth: str = "auto",
    hdr_tone_mapping: str = "none",
    hdr_exposure: float = 0.0,
    raw_white_balance: str = "camera",
    raw_exposure: float = 0.0,
    raw_demosaic: str = "auto",
    svg_scale: float = 1.0,
    svg_background: str = "transparent",
    psd_composite_mode: str = "merged",
    psd_layer_index: int = -1,
) -> ConversionResult:
    """Convert and optimize image with format conversion, resizing, watermarking, and target size solver.

    ``target_ssim`` switches lossy formats to quality-target mode: the lowest
    quality whose SSIM meets the target is used and ``quality`` is ignored.
    ``min_ssim`` is a floor for the size solver: if hitting ``target_kb``
    would drop SSIM below it, quality is raised to the floor instead and the
    result carries a note saying the target was overshot.
    """
    original_size = None
    width = None
    height = None
    note: str | None = None
    try:
        if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError("Unsupported image format")
        if not source_path.is_file():
            raise FileNotFoundError("The selected image no longer exists")
        if not 1 <= quality <= 100:
            raise ValueError("Quality must be between 1 and 100")

        original_size = source_path.stat().st_size
        output_directory.mkdir(parents=True, exist_ok=True)

        fmt = normalize_output_format(target_format)
        if fmt not in IMAGE_OUTPUT_FORMATS:
            raise ValueError(f"Unsupported output image format: {target_format}")
        dest_ext, pillow_format = IMAGE_OUTPUT_FORMATS[fmt]

        dest_filename = build_destination_filename(
            stem=source_path.stem,
            ext=dest_ext,
            slugify=slugify_names,
            prefix=filename_prefix,
            suffix=filename_suffix,
        )
        output_path = reserve_output_path(
            output_directory / dest_filename,
            overwrite,
            reserved_paths,
        )

        is_raw = source_path.suffix.lower() in RAW_EXTENSIONS
        is_svg = source_path.suffix.lower() in SVG_EXTENSIONS
        if is_raw and raw_engine is not None:
            raw_target_bps = 16 if bit_depth in ("16", "auto") and dest_ext in (".tif", ".tiff", ".png") else 8
            image_obj = raw_engine.develop_raw(
                source_path,
                wb=raw_white_balance,
                exposure=raw_exposure,
                demosaic=raw_demosaic,
                output_bps=raw_target_bps,
            )
        elif is_svg and svg_engine is not None:
            image_obj = svg_engine.rasterize_svg(
                source_path,
                scale=svg_scale,
                background=svg_background,
            )
        elif source_path.suffix.lower() == ".psd" and psd_engine is not None and (psd_composite_mode != "merged" or (psd_layer_index is not None and psd_layer_index >= 0)):
            target_layers = [psd_layer_index] if (psd_layer_index is not None and psd_layer_index >= 0) else None
            image_obj = psd_engine.composite_psd(
                source_path,
                composite_mode=psd_composite_mode,
                layer_indices=target_layers,
            )
        else:
            image_obj = Image.open(source_path)

        with image_obj as image:
            is_animated = bool(getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1)

            # Resize is a stack step: its dimensions are derived from the image
            # as it reaches that step, not from the untouched source.
            resize_spec: ResizeSpec = (scale_percent, max_width, max_height)

            if is_animated and fmt in ("WEBP", "GIF"):
                frames: list[Image.Image] = []
                durations: list[int] = []
                loop = image.info.get("loop", 0)

                for frame in ImageSequence.Iterator(image):
                    pf = _process_frame_image(
                        frame,
                        resize_spec=resize_spec,
                        operation_order=operation_order,
                        watermark_logo_path=watermark_logo_path,
                        watermark_scale_pct=watermark_scale_pct,
                        watermark_position=watermark_position,
                        watermark_opacity=watermark_opacity,
                        watermark_text=watermark_text,
                        rotate_angle=rotate_angle,
                        flip_h=flip_h,
                        flip_v=flip_v,
                        aspect_ratio=aspect_ratio,
                        corner_radius=corner_radius,
                        grayscale=grayscale,
                        resize_condition=resize_condition,
                        watermark_condition=watermark_condition,
                        color_profile_mode=color_profile_mode,
                        color_profile_custom=color_profile_custom,
                        rendering_intent=rendering_intent,
                    )
                    frames.append(pf)
                    durations.append(frame.info.get("duration", 100))

                width, height = frames[0].size
                temporary_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=output_directory, suffix=f".tmp{dest_ext}", delete=False
                    ) as temporary_file:
                        temporary_path = Path(temporary_file.name)
                    temp_tracker.register(temporary_path)

                    if fmt == "WEBP":
                        save_options = {
                            "format": "WEBP",
                            "save_all": True,
                            "append_images": frames[1:],
                            "duration": durations,
                            "loop": loop,
                            "quality": quality,
                            "method": 6,
                            "lossless": lossless,
                        }
                        frames[0].save(temporary_path, **save_options)
                    else:
                        gif_frames = [
                            frame.convert("RGBA").convert(
                                "P", palette=Image.Palette.ADAPTIVE
                            )
                            for frame in frames
                        ]
                        gif_frames[0].save(
                            temporary_path,
                            format="GIF",
                            save_all=True,
                            append_images=gif_frames[1:],
                            duration=durations,
                            loop=loop,
                            optimize=True,
                            disposal=2,
                        )
                    os.replace(temporary_path, output_path)
                finally:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                        temp_tracker.unregister(temporary_path)

                output_size = output_path.stat().st_size
                return ConversionResult(
                    source_path,
                    output_path,
                    original_size,
                    output_size,
                    format_saved_percentage(original_size, output_size),
                    "Completed",
                    width=width,
                    height=height,
                )

            image.load()
            try:
                image = ImageOps.exif_transpose(image)
            except Exception:
                pass

            # Run the processing stack (transforms, resize, watermark) in the
            # user's chosen order.
            image = apply_image_transformations(
                image,
                rotate_angle=rotate_angle,
                flip_h=flip_h,
                flip_v=flip_v,
                aspect_ratio=aspect_ratio,
                corner_radius=corner_radius,
                grayscale=grayscale,
                resize_spec=resize_spec,
                watermark_fn=_make_watermark_fn(
                    watermark_logo_path, watermark_text, watermark_position,
                    watermark_scale_pct, watermark_opacity,
                ),
                order=operation_order,
                resize_condition=resize_condition,
                watermark_condition=watermark_condition,
                color_profile_mode=color_profile_mode,
                color_profile_custom=color_profile_custom,
                rendering_intent=rendering_intent,
                hdr_tone_mapping=hdr_tone_mapping,
                hdr_exposure=hdr_exposure,
            )

            from hdr_tone_map import resolve_target_bit_depth, apply_tone_mapping
            effective_bit_depth = resolve_target_bit_depth(image, bit_depth, fmt)

            # If image is high bit-depth/HDR float and output format only supports 8-bit,
            # tone-map down to 8-bit smoothly so highlights don't blow out
            if image.mode in ("I;16", "I;16L", "I;16B", "I", "F") and effective_bit_depth == 8:
                image = apply_tone_mapping(
                    image,
                    method="aces" if (not hdr_tone_mapping or hdr_tone_mapping == "none") else hdr_tone_mapping,
                    exposure=hdr_exposure,
                )

            width, height = image.size

            # Metadata extraction (unless strip_metadata is True)
            exif_data = None
            icc_profile = None
            if preserve_metadata and not strip_metadata:
                try:
                    exif = image.getexif()
                    if exif:
                        exif_data = exif.tobytes()
                except Exception:
                    exif_data = None
                try:
                    icc_profile = image.info.get("icc_profile")
                except Exception:
                    icc_profile = None

            # Color profile override if color management conversion was active
            if color_profile_mode and str(color_profile_mode).strip().lower() not in ("preserve", "preserve_(source)", "none", "untouched"):
                try:
                    from color_manager import load_target_profile
                    _, target_bytes, _ = load_target_profile(color_profile_mode, color_profile_custom)
                    if target_bytes:
                        icc_profile = target_bytes
                except Exception:
                    pass

            # Mode normalization
            if fmt in ("JPEG", "JPG"):
                if image.mode not in ("RGB", "CMYK"):
                    image = flatten_to_rgb(image)
            elif fmt in ("WEBP", "AVIF", "HEIC", "JPEG 2000", "TGA", "DDS", "QOI", "ICNS", "SGI"):
                if image.mode == "CMYK":
                    image = image.convert("RGB")
                if image.mode not in ("RGB", "RGBA"):
                    has_trans = (
                        "A" in image.getbands() or "transparency" in image.info
                    )
                    image = image.convert("RGBA" if has_trans else "RGB")
            elif fmt == "PNG":
                if image.mode == "CMYK":
                    image = image.convert("RGB")
                if effective_bit_depth == 16 and image.mode in ("I;16", "I"):
                    if image.mode != "I;16":
                        image = image.convert("I;16")
                elif image.mode not in ("RGB", "RGBA", "L", "LA"):
                    image = image.convert("RGBA")
            elif fmt == "TIFF":
                if effective_bit_depth == 16 and image.mode in ("I;16", "I"):
                    if image.mode != "I;16":
                        image = image.convert("I;16")
            elif fmt == "ICO":
                image = image.convert("RGBA")
            elif fmt == "GIF":
                image = image.convert("RGBA").convert("P", palette=Image.Palette.ADAPTIVE)
            elif fmt in ("BMP", "PPM", "PCX"):
                image = flatten_to_rgb(image)
            elif fmt == "XBM":
                image = image.convert("1")

            # Smart target file size solver / quality-target mode
            chosen_quality = quality
            solvable = fmt in ("WEBP", "JPEG", "AVIF", "HEIC") and not lossless
            if solvable and (target_ssim or (target_kb and target_kb > 0)):
                fmt_target = (
                    "WEBP" if fmt == "WEBP" else
                    ("AVIF" if fmt == "AVIF" else ("HEIF" if fmt == "HEIC" else "JPEG"))
                )
                solver_kwargs = {"method": 6} if fmt == "WEBP" else {}
                if target_ssim:
                    chosen_quality, achieved = solve_quality_for_ssim(
                        image, target_ssim, fmt=fmt_target, save_kwargs=solver_kwargs
                    )
                    note = f"quality {chosen_quality} for SSIM {achieved:.3f}"
                    if achieved < target_ssim:
                        note = f"best SSIM {achieved:.3f} < target {target_ssim:.2f} at quality {chosen_quality}"
                else:
                    target_bytes = target_kb * 1024
                    chosen_quality = solve_target_size_quality(
                        image, target_bytes, fmt=fmt_target, save_kwargs=solver_kwargs
                    )
                    if min_ssim:
                        _size, achieved = _encode_and_measure(
                            image, fmt_target, chosen_quality, solver_kwargs
                        )
                        if achieved < min_ssim:
                            floor_quality, floor_ssim = solve_quality_for_ssim(
                                image, min_ssim, fmt=fmt_target, save_kwargs=solver_kwargs
                            )
                            if floor_quality > chosen_quality:
                                chosen_quality = floor_quality
                                note = (
                                    f"over target: quality raised to {floor_quality} "
                                    f"to keep SSIM ≥ {min_ssim:.2f} (got {floor_ssim:.3f})"
                                )

            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=output_directory, suffix=f".tmp{dest_ext}", delete=False
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                temp_tracker.register(temporary_path)

                if fmt == "WEBP":
                    save_options = {
                        "format": "WEBP",
                        "quality": chosen_quality,
                        "method": 6,
                        "lossless": lossless,
                    }
                    if exif_data:
                        save_options["exif"] = exif_data
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    image.save(temporary_path, **save_options)

                elif fmt == "AVIF":
                    save_options = {
                        "format": "AVIF",
                        "quality": chosen_quality,
                    }
                    if effective_bit_depth in (10, 12):
                        save_options["bit_depth"] = effective_bit_depth
                    if exif_data:
                        save_options["exif"] = exif_data
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    image.save(temporary_path, **save_options)

                elif fmt == "HEIC":
                    save_options = {
                        "format": "HEIF",
                        "quality": chosen_quality,
                    }
                    if effective_bit_depth in (10, 12):
                        save_options["bit_depth"] = effective_bit_depth
                    if exif_data:
                        save_options["exif"] = exif_data
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    image.save(temporary_path, **save_options)

                elif fmt in ("JPEG", "JPG"):
                    save_options = {
                        "format": "JPEG",
                        "quality": chosen_quality,
                        "optimize": True,
                        "progressive": True,
                    }
                    if exif_data:
                        save_options["exif"] = exif_data
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    image.save(temporary_path, **save_options)

                elif fmt == "PNG":
                    save_options = {
                        "format": "PNG",
                        "optimize": True,
                        "compress_level": 9,
                    }
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    image.save(temporary_path, **save_options)

                elif fmt == "ICO":
                    # Generate multi-resolution icon (16, 32, 48, 64, 128, 256)
                    image.save(
                        temporary_path,
                        format="ICO",
                        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
                    )

                elif fmt == "TIFF":
                    save_options = {"format": "TIFF", "compression": "tiff_deflate"}
                    if icc_profile:
                        save_options["icc_profile"] = icc_profile
                    image.save(temporary_path, **save_options)

                elif fmt == "JXL":
                    save_options = {
                        "format": "JXL",
                        "quality": quality,
                        "lossless": lossless,
                        "effort": 7,
                    }
                    image.save(temporary_path, **save_options)

                elif fmt == "PDF":
                    pdf_img = flatten_to_rgb(image)
                    pdf_img.save(temporary_path, format="PDF", resolution=100.0)

                else:
                    image.save(temporary_path, format=pillow_format)

                os.replace(temporary_path, output_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                    temp_tracker.unregister(temporary_path)

        output_size = output_path.stat().st_size
        return ConversionResult(
            source_path,
            output_path,
            original_size,
            output_size,
            format_saved_percentage(original_size, output_size),
            "Completed",
            width=width,
            height=height,
            note=note,
        )
    except Exception as error:
        return ConversionResult(
            source_path, None, original_size, None, "-", "Failed", str(error)
        )


def estimate_image_output_size(
    source_path: Path,
    **conversion_options: object,
) -> int:
    """Run an exact conversion in an isolated temporary directory and return bytes.

    This deliberately reuses ``convert_image`` rather than maintaining a
    second approximation pipeline that can drift from real output behavior.
    Callers should debounce it and run it outside the UI thread.
    """
    options = dict(conversion_options)
    options.pop("overwrite", None)
    options.pop("reserved_paths", None)
    with tempfile.TemporaryDirectory(prefix="shadow-estimate-") as directory:
        result = convert_image(
            source_path,
            Path(directory),
            overwrite=True,
            **options,
        )
        if result.status != "Completed" or result.output_size is None:
            raise ValueError(result.error or "Unable to estimate output size")
        return result.output_size


def combine_images_to_pdf(images: list[Path], output_pdf_path: Path) -> Path:
    """Combine a list of images into a single multi-page compressed PDF."""
    if not images:
        raise ValueError("No images provided to combine into PDF")
    opened_images: list[Image.Image] = []
    for p in images:
        img = Image.open(p)
        if img.mode != "RGB":
            img = flatten_to_rgb(img)
        opened_images.append(img)
    first = opened_images[0]
    rest = opened_images[1:] if len(opened_images) > 1 else []
    first.save(output_pdf_path, format="PDF", save_all=True, append_images=rest)
    for img in opened_images:
        img.close()
    return output_pdf_path
