"""Objective image-quality metrics in pure Pillow (no numpy).

SSIM uses 8x8 non-overlapping block statistics on luma (the "uniform
window" variant), computed with Pillow's float-image ops via ImageMath and
Image.reduce so the per-pixel work stays in C. ~10 ms per comparison at
512 px; agrees with the Gaussian-window form to within a few thousandths
on photographic content.
"""
from __future__ import annotations

import math

from PIL import Image, ImageMath

_C1 = (0.01 * 255) ** 2
_C2 = (0.03 * 255) ** 2


def _pixels(image: Image.Image) -> list[float]:
    getter = getattr(image, "get_flattened_data", None)
    return list(getter()) if getter else list(image.getdata())


def _mul(a: Image.Image, b: Image.Image) -> Image.Image:
    return ImageMath.lambda_eval(lambda d: d["a"] * d["b"], a=a, b=b)


def block_ssim(a: Image.Image, b: Image.Image, block: int = 8) -> float:
    """Structural similarity in [0, 1] using 8x8 block statistics on luma."""
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)
    w, h = a.size
    if w < block or h < block:
        block = max(1, min(w, h))
    x = a.convert("L").convert("F")
    y = b.convert("L").convert("F")
    mx, my = x.reduce(block), y.reduce(block)
    exx, eyy, exy = _mul(x, x).reduce(block), _mul(y, y).reduce(block), _mul(x, y).reduce(block)
    ssim_map = ImageMath.lambda_eval(
        lambda d: (
            (2 * d["mx"] * d["my"] + _C1) * (2 * (d["exy"] - d["mx"] * d["my"]) + _C2)
        )
        / (
            (d["mx"] * d["mx"] + d["my"] * d["my"] + _C1)
            * ((d["exx"] - d["mx"] * d["mx"]) + (d["eyy"] - d["my"] * d["my"]) + _C2)
        ),
        mx=mx, my=my, exx=exx, eyy=eyy, exy=exy,
    )
    values = _pixels(ssim_map)
    if not values:
        return 1.0
    return max(0.0, min(1.0, sum(values) / len(values)))


def psnr(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)
    x = a.convert("L").convert("F")
    y = b.convert("L").convert("F")
    diff = ImageMath.lambda_eval(lambda d: (d["a"] - d["b"]) * (d["a"] - d["b"]), a=x, b=y)
    values = _pixels(diff)
    mse = sum(values) / len(values) if values else 0.0
    return math.inf if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))


def downscaled(image: Image.Image, max_edge: int = 1024) -> Image.Image:
    if max(image.size) <= max_edge:
        return image
    copy = image.copy()
    copy.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return copy


def ssim_downscaled(a: Image.Image, b: Image.Image, max_edge: int = 1024) -> float:
    """SSIM on working copies capped at max_edge, for interactive use on large photos."""
    return block_ssim(downscaled(a, max_edge), downscaled(b, max_edge))
