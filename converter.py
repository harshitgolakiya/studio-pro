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
    ".avif", ".avifs", ".heic", ".heif", ".hif", ".gif",
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

LOSSY_IMAGE_FORMATS = {"WEBP", "AVIF", "HEIC", "JPEG"}


def normalize_output_format(value: str) -> str:
    """Return a canonical IMAGE_OUTPUT_FORMATS key for a UI/API value."""
    fmt = value.upper().strip()
    aliases = {
        "JPG": "JPEG",
        "JPE": "JPEG",
        "JFIF": "JPEG",
        "HEIF": "HEIC",
        "HIF": "HEIC",
        "JP2": "JPEG 2000",
        "JPEG2000": "JPEG 2000",
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


def apply_image_transformations(
    image: Image.Image,
    rotate_angle: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
    aspect_ratio: str | None = None,
    corner_radius: int = 0,
    grayscale: bool = False,
) -> Image.Image:
    """Apply rotate, flip, aspect ratio crop, rounded corners, and grayscale transformations."""
    im = image
    if rotate_angle in (90, 180, 270):
        if rotate_angle == 90:
            im = im.transpose(Image.Transpose.ROTATE_270)
        elif rotate_angle == 180:
            im = im.transpose(Image.Transpose.ROTATE_180)
        elif rotate_angle == 270:
            im = im.transpose(Image.Transpose.ROTATE_90)
    elif rotate_angle != 0:
        im = im.rotate(-rotate_angle, expand=True, resample=Image.Resampling.BICUBIC)

    if flip_h:
        im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip_v:
        im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    # Aspect ratio center crop
    if aspect_ratio and ":" in aspect_ratio:
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
                    im = im.crop((left, 0, left + new_w, cur_h))
                elif cur_ratio < target_ratio:
                    new_h = max(1, int(round(cur_w / target_ratio)))
                    top = (cur_h - new_h) // 2
                    im = im.crop((0, top, cur_w, top + new_h))
        except Exception:
            pass

    # Grayscale filter
    if grayscale:
        has_alpha = "A" in im.getbands() or "transparency" in im.info
        if has_alpha:
            rgba = im.convert("RGBA")
            a = rgba.getchannel("A")
            gray = rgba.convert("L")
            im = Image.merge("RGBA", (gray, gray, gray, a))
        else:
            im = im.convert("L").convert("RGB")

    # Rounded corners (creates alpha mask)
    if corner_radius > 0:
        w, h = im.size
        rad = min(corner_radius, min(w, h) // 2)
        if rad > 0:
            im = im.convert("RGBA")
            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle([(0, 0), (w, h)], radius=rad, fill=255)
            if "A" in im.getbands():
                orig_alpha = im.getchannel("A")
                combined_mask = ImageChops.multiply(mask, orig_alpha)
                im.putalpha(combined_mask)
            else:
                im.putalpha(mask)

    return im


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
    target_dims: tuple[int, int] | None = None,
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
) -> Image.Image:
    f = frame.copy()
    if rotate_angle or flip_h or flip_v or aspect_ratio or corner_radius or grayscale:
        f = apply_image_transformations(
            f,
            rotate_angle=rotate_angle,
            flip_h=flip_h,
            flip_v=flip_v,
            aspect_ratio=aspect_ratio,
            corner_radius=corner_radius,
            grayscale=grayscale,
        )
    if target_dims:
        f = f.resize(target_dims, Image.Resampling.LANCZOS)
    if watermark_logo_path and Path(watermark_logo_path).is_file():
        f = apply_image_watermark(
            f,
            logo_path=watermark_logo_path,
            position=watermark_position,
            scale_pct=watermark_scale_pct,
            opacity=watermark_opacity,
        )
    elif watermark_text.strip():
        f = apply_text_watermark(
            f,
            text=watermark_text,
            position=watermark_position,
            opacity=watermark_opacity,
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
) -> ConversionResult:
    """Convert and optimize image with format conversion, resizing, watermarking, and target size solver."""
    original_size = None
    width = None
    height = None
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

        with Image.open(source_path) as image:
            is_animated = bool(getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1)

            # Proportional downscaling dimensions
            target_dims = None
            orig_w, orig_h = image.size
            if scale_percent is not None and 1 <= scale_percent < 100:
                new_w = max(1, int(round(orig_w * (scale_percent / 100.0))))
                new_h = max(1, int(round(orig_h * (scale_percent / 100.0))))
                target_dims = (new_w, new_h)
            elif (max_width and orig_w > max_width) or (
                max_height and orig_h > max_height
            ):
                target_w = max_width or orig_w
                target_h = max_height or orig_h
                ratio = min(target_w / orig_w, target_h / orig_h)
                new_w = max(1, int(round(orig_w * ratio)))
                new_h = max(1, int(round(orig_h * ratio)))
                target_dims = (new_w, new_h)

            if is_animated and fmt in ("WEBP", "GIF"):
                frames: list[Image.Image] = []
                durations: list[int] = []
                loop = image.info.get("loop", 0)

                for frame in ImageSequence.Iterator(image):
                    pf = _process_frame_image(
                        frame,
                        target_dims=target_dims,
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
                    if temporary_path and temporary_path.exists():
                        temporary_path.unlink()

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

            # Apply user geometric & artistic transformations
            image = apply_image_transformations(
                image,
                rotate_angle=rotate_angle,
                flip_h=flip_h,
                flip_v=flip_v,
                aspect_ratio=aspect_ratio,
                corner_radius=corner_radius,
                grayscale=grayscale,
            )

            if target_dims:
                image = image.resize(target_dims, Image.Resampling.LANCZOS)

            # Watermarking (Logo or Text)
            if watermark_logo_path and Path(watermark_logo_path).is_file():
                image = apply_image_watermark(
                    image,
                    logo_path=watermark_logo_path,
                    position=watermark_position,
                    scale_pct=watermark_scale_pct,
                    opacity=watermark_opacity,
                )
            elif watermark_text.strip():
                image = apply_text_watermark(
                    image,
                    text=watermark_text,
                    position=watermark_position,
                    opacity=watermark_opacity,
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

            # Mode normalization
            if fmt in ("JPEG", "JPG"):
                if image.mode != "RGB":
                    image = flatten_to_rgb(image)
            elif fmt in ("WEBP", "AVIF", "HEIC", "JPEG 2000", "TGA", "DDS", "QOI", "ICNS", "SGI"):
                if image.mode not in ("RGB", "RGBA"):
                    has_trans = (
                        "A" in image.getbands() or "transparency" in image.info
                    )
                    image = image.convert("RGBA" if has_trans else "RGB")
            elif fmt == "PNG":
                if image.mode not in ("RGB", "RGBA", "L", "LA"):
                    image = image.convert("RGBA")
            elif fmt == "ICO":
                image = image.convert("RGBA")
            elif fmt == "GIF":
                image = image.convert("RGBA").convert("P", palette=Image.Palette.ADAPTIVE)
            elif fmt in ("BMP", "PPM", "PCX"):
                image = flatten_to_rgb(image)
            elif fmt == "XBM":
                image = image.convert("1")

            # Smart target file size solver
            chosen_quality = quality
            if target_kb and target_kb > 0 and fmt in ("WEBP", "JPEG", "AVIF", "HEIC"):
                target_bytes = target_kb * 1024
                fmt_target = (
                    "WEBP" if fmt == "WEBP" else
                    ("AVIF" if fmt == "AVIF" else ("HEIF" if fmt == "HEIC" else "JPEG"))
                )
                chosen_quality = solve_target_size_quality(
                    image,
                    target_bytes,
                    fmt=fmt_target,
                    save_kwargs={"method": 6} if fmt == "WEBP" else {},
                )

            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=output_directory, suffix=f".tmp{dest_ext}", delete=False
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)

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
                    image.save(temporary_path, format="TIFF", compression="tiff_deflate")

                elif fmt == "PDF":
                    pdf_img = flatten_to_rgb(image)
                    pdf_img.save(temporary_path, format="PDF", resolution=100.0)

                else:
                    image.save(temporary_path, format=pillow_format)

                os.replace(temporary_path, output_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

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
