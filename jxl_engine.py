"""JPEG XL (JXL) image codec engine and Pillow plugin integration.

Provides:
- High-efficiency lossy and mathematically lossless JPEG XL encoding/decoding.
- Support for RGB, RGBA, Grayscale, and 16-bit channel depth.
- Transparent Pillow `JxlImageFile` plugin registration.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, Union

import numpy as np
from PIL import Image, ImageFile

try:
    import imagecodecs
    _HAS_IMAGECODECS = hasattr(imagecodecs, "jpegxl_encode") and hasattr(imagecodecs, "jpegxl_decode")
except ImportError:
    imagecodecs = None
    _HAS_IMAGECODECS = False

# JPEG XL Magic Signatures
# 1. Bare codestream: FF 0A
JXL_CODESTREAM_SIGNATURE = b"\xFF\x0A"
# 2. ISOBMFF container signature box: 00 00 00 0C 4A 58 4C 20 0D 0A 87 0A
JXL_CONTAINER_SIGNATURE = b"\x00\x00\x00\x0CJXL \x0D\x0A\x87\x0A"


def is_jxl_available() -> bool:
    """Return True if JPEG XL encoding and decoding are supported."""
    return _HAS_IMAGECODECS


def encode_jxl(
    image: Image.Image,
    quality: int = 80,
    lossless: bool = False,
    effort: int = 7,
) -> bytes:
    """Encode a PIL Image to JPEG XL bytes.

    Args:
        image: PIL Image instance to encode.
        quality: Compression quality 1-100 (ignored if lossless=True).
        lossless: When True, perform mathematically lossless compression.
        effort: Encoder effort 1-9 (default 7).
    """
    if not is_jxl_available():
        raise RuntimeError("JPEG XL encoding is unavailable: imagecodecs not installed or missing jpegxl support.")

    # Normalize image mode
    if image.mode in ("P", "1"):
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    elif image.mode not in ("L", "LA", "RGB", "RGBA", "I;16", "I"):
        image = image.convert("RGBA" if image.mode in ("CMYK", "YCbCr") else "RGB")

    arr = np.ascontiguousarray(np.array(image))

    # Clamp quality
    clamped_q = max(1, min(100, int(quality)))
    clamped_effort = max(1, min(9, int(effort)))

    encoded = imagecodecs.jpegxl_encode(
        arr,
        level=clamped_q if not lossless else 100,
        lossless=lossless,
        effort=clamped_effort,
    )
    return bytes(encoded)


def decode_jxl(source: Union[bytes, BinaryIO, str, Path]) -> Image.Image:
    """Decode JPEG XL bytes, file path, or stream into a PIL Image."""
    if not is_jxl_available():
        raise RuntimeError("JPEG XL decoding is unavailable: imagecodecs not installed or missing jpegxl support.")

    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            data = f.read()
    elif hasattr(source, "read"):
        data = source.read()
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        raise ValueError(f"Unsupported source type for JXL decoding: {type(source)}")

    arr = imagecodecs.jpegxl_decode(data)
    if not isinstance(arr, np.ndarray):
        raise ValueError("Failed to decode JPEG XL: decoded output is not a numpy array.")

    # Convert array to PIL Image
    if arr.ndim == 2:
        mode = "L" if arr.dtype == np.uint8 else ("I;16" if arr.dtype == np.uint16 else "I")
        return Image.fromarray(arr, mode=mode)
    elif arr.ndim == 3:
        channels = arr.shape[2]
        if channels == 1:
            return Image.fromarray(arr[:, :, 0], mode="L")
        elif channels == 2:
            return Image.fromarray(arr, mode="LA")
        elif channels == 3:
            return Image.fromarray(arr, mode="RGB")
        elif channels == 4:
            return Image.fromarray(arr, mode="RGBA")
        else:
            return Image.fromarray(arr[:, :, :4], mode="RGBA")
    else:
        raise ValueError(f"Unsupported JPEG XL array dimensions: {arr.shape}")


def is_jxl_header(header: bytes) -> bool:
    """Check if binary header matches JPEG XL codestream or container signature."""
    if len(header) < 2:
        return False
    if header.startswith(JXL_CODESTREAM_SIGNATURE):
        return True
    if len(header) >= 12 and header.startswith(JXL_CONTAINER_SIGNATURE):
        return True
    return False


class JxlImageFile(ImageFile.ImageFile):
    """Pillow ImagePlugin implementation for JPEG XL (.jxl)."""

    format = "JXL"
    format_description = "JPEG XL image"

    def _open(self) -> None:
        header = self.fp.read(16)
        self.fp.seek(0)

        filename = getattr(self, "filename", "") or ""
        ext = Path(filename).suffix.lower() if filename else ""

        if not (is_jxl_header(header) or ext == ".jxl"):
            raise SyntaxError("Not a JPEG XL file")

        if not is_jxl_available():
            raise SyntaxError("JPEG XL codec not available")

        data = self.fp.read()
        self.fp.seek(0)
        im = decode_jxl(data)

        self._mode = im.mode
        self._size = im.size
        self.im = im.im
        self.readonly = 1

    def load(self):
        return Image.Image.load(self)


def _save_jxl(im: Image.Image, fp: BinaryIO, filename: str) -> None:
    quality = im.encoderinfo.get("quality", 80)
    lossless = im.encoderinfo.get("lossless", False)
    effort = im.encoderinfo.get("effort", 7)
    data = encode_jxl(im, quality=quality, lossless=lossless, effort=effort)
    fp.write(data)


def register_jxl_opener() -> None:
    """Register JPEG XL opener and saver with Pillow."""
    Image.register_open(JxlImageFile.format, JxlImageFile, is_jxl_header)
    Image.register_save(JxlImageFile.format, _save_jxl)
    Image.register_extension(JxlImageFile.format, ".jxl")
    Image.register_mime(JxlImageFile.format, "image/jxl")


# Auto-register on import
register_jxl_opener()
