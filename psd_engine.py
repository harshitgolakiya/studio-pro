"""Adobe Photoshop PSD layer selection and compositing engine.

Provides:
- Layer enumeration with visibility, opacity, blend modes, and bounding boxes.
- Multi-mode compositing: pre-merged composite, visible layers only, all layers,
  or user-selected layer subsets.
- High-fidelity extraction of individual layers with coordinate positioning.
- Seamless fallback to Pillow PSD decoding when psd-tools is absent.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, BinaryIO, Sequence, Union

from PIL import Image

try:
    import psd_tools
    from psd_tools import PSDImage
    from psd_tools.api.layers import Layer
    _HAS_PSD_TOOLS = True
except ImportError:
    psd_tools = None
    PSDImage = None
    Layer = None
    _HAS_PSD_TOOLS = False


def is_psd_available() -> bool:
    """Return True if advanced PSD parsing and compositing are available."""
    return _HAS_PSD_TOOLS


def _open_psd(source: Union[bytes, BinaryIO, str, Path]) -> Any:
    if not is_psd_available():
        raise RuntimeError("psd-tools is not installed. Advanced PSD compositing requires psd-tools.")

    if isinstance(source, (str, Path)):
        return PSDImage.open(str(source))
    elif isinstance(source, (bytes, bytearray)):
        return PSDImage.open(io.BytesIO(source))
    elif hasattr(source, "read"):
        data = source.read()
        return PSDImage.open(io.BytesIO(data))
    else:
        raise ValueError(f"Unsupported source type for PSD: {type(source)}")


def get_psd_layer_info(source: Union[bytes, BinaryIO, str, Path]) -> list[dict[str, Any]]:
    """Return a list of layer metadata dictionaries for a PSD document."""
    if not is_psd_available():
        return []

    try:
        psd = _open_psd(source)
        layers_info: list[dict[str, Any]] = []

        # Enumerate all layers (flattened list of layers and groups)
        all_layers = list(psd.descendants())
        for idx, layer in enumerate(all_layers):
            opacity_val = getattr(layer, "opacity", 255)
            opacity_norm = round(float(opacity_val) / 255.0, 3) if opacity_val is not None else 1.0
            bbox_tuple = getattr(layer, "bbox", (0, 0, 0, 0))
            if hasattr(bbox_tuple, "x1"):
                bbox = (bbox_tuple.x1, bbox_tuple.y1, bbox_tuple.x2, bbox_tuple.y2)
            else:
                bbox = tuple(bbox_tuple) if bbox_tuple else (0, 0, 0, 0)

            layers_info.append({
                "index": idx,
                "name": str(getattr(layer, "name", f"Layer {idx}")),
                "visible": bool(getattr(layer, "visible", True)),
                "opacity": opacity_norm,
                "blend_mode": str(getattr(layer, "blend_mode", "normal")),
                "bbox": bbox,
                "kind": str(getattr(layer, "kind", "pixel")),
                "is_group": bool(getattr(layer, "is_group", False)),
                "has_mask": bool(getattr(layer, "has_mask", False)),
            })
        return layers_info
    except Exception:
        return []


def get_psd_metadata(source: Union[bytes, BinaryIO, str, Path]) -> dict[str, Any]:
    """Return document-level metadata for a PSD file."""
    if not is_psd_available():
        return {"layers_count": 0, "color_mode": "RGB", "depth": 8}

    try:
        psd = _open_psd(source)
        layers = list(psd.descendants())
        visible_count = sum(1 for layer in layers if getattr(layer, "visible", True))
        return {
            "width": psd.width,
            "height": psd.height,
            "depth": getattr(psd, "depth", 8),
            "color_mode": str(getattr(psd, "color_mode", "RGB")),
            "channels": getattr(psd, "channels", 3),
            "total_layers": len(layers),
            "visible_layers": visible_count,
            "hidden_layers": len(layers) - visible_count,
            "has_preview": getattr(psd, "has_preview", True),
        }
    except Exception:
        return {"layers_count": 0, "color_mode": "RGB", "depth": 8}


def composite_psd(
    source: Union[bytes, BinaryIO, str, Path],
    composite_mode: str = "merged",
    layer_indices: Sequence[int] | None = None,
    keep_canvas_size: bool = True,
) -> Image.Image:
    """Composite a PSD document into a PIL Image.

    Args:
        source: File path, bytes, or file-like stream of PSD.
        composite_mode:
            - 'merged': Use the pre-flattened image cached in the PSD file.
            - 'visible': Recomposite only visible layers.
            - 'all': Make all layers visible and recomposite.
            - 'selected': Recomposite only the specified `layer_indices`.
        layer_indices: Indices of specific layers to composite when mode is 'selected'.
        keep_canvas_size: If True, place single selected layer at original document canvas position.
    """
    mode_clean = str(composite_mode).lower().strip()

    # Fallback to standard Pillow if psd-tools is absent
    if not is_psd_available():
        if isinstance(source, (str, Path)):
            return Image.open(source).convert("RGBA")
        elif hasattr(source, "read"):
            return Image.open(source).convert("RGBA")
        else:
            return Image.open(io.BytesIO(source)).convert("RGBA")

    psd = _open_psd(source)

    if mode_clean == "merged":
        # Check if pre-flattened composite exists
        try:
            merged_im = psd.topil()
            if merged_im is not None:
                return merged_im
        except Exception:
            pass
        # If topil() returns None or fails, composite dynamically
        return psd.composite()

    all_descendants = list(psd.descendants())

    if mode_clean == "all":
        # Force all layers to visible
        for layer in all_descendants:
            if hasattr(layer, "visible"):
                layer.visible = True
        return psd.composite(ignore_preview=True)

    elif mode_clean == "visible":
        return psd.composite(ignore_preview=True)

    elif mode_clean == "selected":
        if not layer_indices:
            # Nothing selected, fallback to merged
            return psd.composite()

        target_set = set(layer_indices)

        # Single layer fast path
        if len(target_set) == 1:
            target_idx = next(iter(target_set))
            if 0 <= target_idx < len(all_descendants):
                single_layer = all_descendants[target_idx]
                try:
                    layer_im = single_layer.composite()
                    if layer_im is not None:
                        if not keep_canvas_size:
                            return layer_im
                        # Place onto canvas matching PSD document dimensions
                        canvas = Image.new("RGBA", (psd.width, psd.height), (0, 0, 0, 0))
                        bbox = getattr(single_layer, "bbox", None)
                        if bbox is not None:
                            left = getattr(bbox, "x1", bbox[0] if isinstance(bbox, (list, tuple)) else 0)
                            top = getattr(bbox, "y1", bbox[1] if isinstance(bbox, (list, tuple)) else 0)
                            canvas.paste(layer_im, (left, top), layer_im)
                        else:
                            canvas.paste(layer_im, (0, 0), layer_im)
                        return canvas
                except Exception:
                    pass

        # Multiple selected layers
        for idx, layer in enumerate(all_descendants):
            if hasattr(layer, "visible"):
                layer.visible = (idx in target_set)

        return psd.composite(ignore_preview=True)

    else:
        # Default / unrecognized mode
        return psd.composite()
