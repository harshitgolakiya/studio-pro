from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def apply_text_watermark(
    image: Image.Image,
    text: str,
    position: str = "bottom-right",
    opacity: float = 0.7,
    font_size: int = 24,
) -> Image.Image:
    """Overlay a clean semi-transparent text watermark onto an image."""
    if not text.strip():
        return image

    orig_mode = image.mode
    base = image.convert("RGBA")

    watermark_layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(watermark_layer)

    try:
        font = ImageFont.truetype("arial.ttf", size=font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding = 24
    w, h = base.size

    pos_lower = position.lower()
    if pos_lower == "bottom-right":
        x = w - text_w - padding
        y = h - text_h - padding
    elif pos_lower == "bottom-left":
        x = padding
        y = h - text_h - padding
    elif pos_lower == "top-right":
        x = w - text_w - padding
        y = padding
    elif pos_lower == "top-left":
        x = padding
        y = padding
    else:  # center
        x = (w - text_w) // 2
        y = (h - text_h) // 2

    alpha_int = max(0, min(255, int(opacity * 255)))
    shadow_alpha = max(0, int(alpha_int * 0.45))

    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, shadow_alpha))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha_int))

    combined = Image.alpha_composite(base, watermark_layer)

    if orig_mode != "RGBA" and "A" not in orig_mode:
        return combined.convert(orig_mode)
    return combined


def apply_image_watermark(
    image: Image.Image,
    logo_path: str | Path,
    position: str = "bottom-right",
    scale_pct: float = 0.20,
    opacity: float = 0.8,
) -> Image.Image:
    """Overlay a custom PNG or image logo watermark onto an image with scaling and opacity."""
    logo_file = Path(logo_path)
    if not logo_file.is_file():
        return image

    try:
        with Image.open(logo_file) as logo_raw:
            logo = logo_raw.convert("RGBA")
    except Exception:
        return image

    orig_mode = image.mode
    base = image.convert("RGBA")
    w, h = base.size

    # Scale logo relative to base image width
    target_w = max(16, int(w * max(0.05, min(0.60, scale_pct))))
    aspect = logo.height / max(1, logo.width)
    target_h = max(16, int(target_w * aspect))
    logo_resized = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Apply opacity to alpha channel
    clamped_opacity = max(0.05, min(1.0, opacity))
    if clamped_opacity < 1.0:
        r, g, b, a = logo_resized.split()
        a = a.point(lambda p: int(p * clamped_opacity))
        logo_resized = Image.merge("RGBA", (r, g, b, a))

    padding = 24
    pos_lower = position.lower()
    if pos_lower == "bottom-right":
        x = w - target_w - padding
        y = h - target_h - padding
    elif pos_lower == "bottom-left":
        x = padding
        y = h - target_h - padding
    elif pos_lower == "top-right":
        x = w - target_w - padding
        y = padding
    elif pos_lower == "top-left":
        x = padding
        y = padding
    else:  # center
        x = (w - target_w) // 2
        y = (h - target_h) // 2

    # Paste using alpha channel mask
    base.paste(logo_resized, (x, y), logo_resized)

    if orig_mode != "RGBA" and "A" not in orig_mode:
        return base.convert(orig_mode)
    return base
