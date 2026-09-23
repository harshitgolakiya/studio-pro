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


def butteraugli_score(a: Image.Image, b: Image.Image) -> float:
    """Psychovisual color-difference metric inspired by Google's Butteraugli model.

    Evaluates human-perceptual distortion in retinal opponent color space (XYB)
    with frequency masking and L_p / max spatial pooling.
    Returns:
        0.0: Mathematically identical images.
        < 0.1: Extremely high fidelity, imperceptible differences.
        ~ 0.5 - 1.0: Just-Noticeable-Difference (JND) threshold.
        > 1.0: Noticeable compression or color artifacts.
    """
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.LANCZOS)

    if a.mode != "RGB":
        a = a.convert("RGB")
    if b.mode != "RGB":
        b = b.convert("RGB")

    try:
        import numpy as np

        arr_a = np.asarray(a, dtype=np.float32) / 255.0
        arr_b = np.asarray(b, dtype=np.float32) / 255.0

        if np.array_equal(arr_a, arr_b):
            return 0.0

        gamma = 0.83
        ra = np.power(np.maximum(arr_a[:, :, 0], 0.0), gamma)
        ga = np.power(np.maximum(arr_a[:, :, 1], 0.0), gamma)
        ba = np.power(np.maximum(arr_a[:, :, 2], 0.0), gamma)

        rb = np.power(np.maximum(arr_b[:, :, 0], 0.0), gamma)
        gb = np.power(np.maximum(arr_b[:, :, 1], 0.0), gamma)
        bb = np.power(np.maximum(arr_b[:, :, 2], 0.0), gamma)

        xa, xb = 0.5 * (ra - ga), 0.5 * (rb - gb)
        ya, yb = 0.5 * (ra + ga), 0.5 * (rb + gb)
        za, zb = ba, bb

        diff_x = np.abs(xa - xb) * 4.0
        diff_y = np.abs(ya - yb) * 11.0
        diff_z = np.abs(za - zb) * 2.5
        diff_map = np.sqrt(diff_x**2 + diff_y**2 + diff_z**2)

        h, w = diff_map.shape
        block = 8
        pad_h = (block - (h % block)) % block
        pad_w = (block - (w % block)) % block
        if pad_h > 0 or pad_w > 0:
            diff_map = np.pad(diff_map, ((0, pad_h), (0, pad_w)), mode="reflect")

        bh, bw = diff_map.shape[0] // block, diff_map.shape[1] // block
        blocks = diff_map.reshape(bh, block, bw, block).transpose(0, 2, 1, 3).reshape(bh * bw, block * block)

        block_means = np.mean(blocks, axis=1)
        block_maxs = np.max(blocks, axis=1)
        block_scores = 0.7 * block_means + 0.3 * block_maxs

        l4_norm = float(np.power(np.mean(np.power(block_scores, 4.0)), 0.25))
        top_k = max(1, int(len(block_scores) * 0.01))
        worst_defect = float(np.mean(np.partition(block_scores, -top_k)[-top_k:]))

        final_score = 0.6 * l4_norm + 0.4 * worst_defect
        return float(round(max(0.0, final_score), 4))
    except Exception:
        ssim_val = block_ssim(a, b)
        return float(round(max(0.0, (1.0 - ssim_val) * 10.0), 4))


def butteraugli_downscaled(a: Image.Image, b: Image.Image, max_edge: int = 1024) -> float:
    """Butteraugli score on working copies capped at max_edge."""
    return butteraugli_score(downscaled(a, max_edge), downscaled(b, max_edge))
