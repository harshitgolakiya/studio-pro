from __future__ import annotations

from dataclasses import dataclass
import io
import math
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import ExifTags, Image, ImageChops, ImageDraw, ImageTk

from converter import ConversionResult
from loss_audit import LossWarning, audit_conversion, display_to_source, format_probe, pixel_probe
from metrics import block_ssim, psnr
from optimizer import CODECS, ALPHA_CODECS
from utils import format_file_size, open_file_or_folder, reveal_in_file_manager

_SEVERITY_COLOURS = {
    "high": ("#b91c1c", "#fca5a5"),
    "medium": ("#b45309", "#fde68a"),
    "info": ("#667085", "#98a2b3"),
}


@dataclass
class VariantResult:
    codec: str
    quality: int
    size_bytes: int
    ssim: float
    psnr: float
    encode_ms: float
    image: Image.Image
    estimated_full_bytes: int
    error: str | None = None


VARIANT_PRESETS: dict[str, list[tuple[str, int]]] = {
    "Modern Web": [("WEBP", 80), ("AVIF", 65), ("JPEG", 80), ("HEIC", 70)],
    "Next-Gen Codecs": [("AVIF", 60), ("WEBP", 75), ("HEIC", 65)],
    "WebP Quality Ladder": [("WEBP", 90), ("WEBP", 75), ("WEBP", 50), ("WEBP", 30)],
    "High Fidelity": [("WEBP", 90), ("AVIF", 85), ("JPEG", 90), ("HEIC", 85)],
    "Aggressive Compression": [("AVIF", 45), ("WEBP", 50), ("JPEG", 65), ("HEIC", 50)],
    "Custom": [("WEBP", 80), ("AVIF", 65), ("JPEG", 80)],
}


def generate_variant(
    source: Image.Image,
    codec: str,
    quality: int,
    max_edge: int = 800,
) -> VariantResult:
    """Encode an in-memory variant, decode it, and compute perceptual quality metrics."""
    work = source.copy()
    if max(work.size) > max_edge:
        work.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    codec_upper = codec.upper()
    if codec_upper == "JPEG":
        if work.mode in ("RGBA", "LA", "PA") or "transparency" in work.info:
            bg = Image.new("RGB", work.size, (255, 255, 255))
            mask = work.split()[-1] if work.mode in ("RGBA", "LA") else None
            bg.paste(work.convert("RGB"), mask=mask)
            work = bg
        elif work.mode != "RGB":
            work = work.convert("RGB")
    elif work.mode not in ("RGB", "RGBA"):
        work = work.convert("RGBA" if "transparency" in work.info else "RGB")

    buf = io.BytesIO()
    start_t = time.perf_counter()
    try:
        if codec_upper in CODECS:
            kwargs = CODECS[codec_upper](quality)
            work.save(buf, **kwargs)
        elif codec_upper == "PNG":
            work.save(buf, format="PNG", optimize=True)
        else:
            work.save(buf, format=codec_upper, quality=quality)
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        buf.seek(0)
        decoded = Image.open(buf)
        decoded.load()
    except Exception as exc:
        return VariantResult(
            codec=codec_upper,
            quality=quality,
            size_bytes=0,
            ssim=0.0,
            psnr=0.0,
            encode_ms=0.0,
            image=work,
            estimated_full_bytes=0,
            error=str(exc),
        )

    size = buf.getbuffer().nbytes
    full_pixels = source.width * source.height
    work_pixels = max(1, work.width * work.height)
    ratio = full_pixels / work_pixels
    est_full_bytes = int(round(size * ratio))

    v_ssim = block_ssim(work, decoded)
    v_psnr = psnr(work, decoded)

    return VariantResult(
        codec=codec_upper,
        quality=quality,
        size_bytes=size,
        ssim=v_ssim,
        psnr=v_psnr,
        encode_ms=elapsed_ms,
        image=decoded,
        estimated_full_bytes=est_full_bytes,
        error=None,
    )


def calculate_comparison_metrics(
    original: Image.Image,
    converted: Image.Image,
    max_pixels: int = 2_000_000,
) -> dict[str, float | bool]:
    """Calculate fast, deterministic visual-difference metrics.

    Very large images are sampled to avoid freezing the UI. Both images are
    aligned to the original canvas and compared as RGBA so alpha changes are
    included instead of silently ignored.
    """
    width, height = original.size
    pixel_count = max(1, width * height)
    scale = min(1.0, math.sqrt(max_pixels / pixel_count))
    sample_size = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )

    original_rgba = original.convert("RGBA")
    converted_rgba = converted.convert("RGBA")
    if original_rgba.size != sample_size:
        original_rgba = original_rgba.resize(sample_size, Image.Resampling.LANCZOS)
    if converted_rgba.size != sample_size:
        converted_rgba = converted_rgba.resize(sample_size, Image.Resampling.LANCZOS)

    difference = ImageChops.difference(original_rgba, converted_rgba)
    histogram = difference.histogram()
    sample_values = sample_size[0] * sample_size[1] * len(difference.getbands())
    squared_error = sum((index % 256) ** 2 * count for index, count in enumerate(histogram))
    absolute_error = sum((index % 256) * count for index, count in enumerate(histogram))
    mse = squared_error / max(1, sample_values)
    mae = absolute_error / max(1, sample_values)
    rmse = math.sqrt(mse)
    psnr = math.inf if mse == 0 else 20 * math.log10(255.0 / rmse)
    similarity = max(0.0, min(100.0, (1.0 - rmse / 255.0) * 100.0))

    return {
        "psnr": psnr,
        "mae": mae,
        "similarity": similarity,
        "sampled": scale < 1.0,
    }


class ImagePreviewDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        source_path: Path,
        result: ConversionResult | None = None,
        on_apply: Callable[[str, int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(f"Image Inspection & Diff - {source_path.name}")
        self.geometry("1100x740")
        self.minsize(920, 600)
        self.transient(parent)

        self.source_path = source_path
        self.result = result
        self.on_apply = on_apply
        self.output_path = (
            self.result.output_path
            if (self.result and self.result.output_path and self.result.output_path.exists())
            else None
        )

        self.view_mode = tk.StringVar(
            value="Split Slider" if self.output_path else "Multi-Variant"
        )
        self.split_pct = 0.50  # 50% split position
        self.zoom_factor = 1.0

        self.orig_pil: Image.Image | None = None
        self.conv_pil: Image.Image | None = None
        self.disp_orig: Image.Image | None = None
        self.disp_conv: Image.Image | None = None
        self.disp_size: tuple[int, int] = (600, 400)
        self.tk_canvas_img: ImageTk.PhotoImage | None = None
        self._active_variant_label: str | None = None

        # Multi-variant comparison state
        self._variant_preset = tk.StringVar(value="Modern Web")
        self._variant_slots: list[tuple[str, int]] = list(VARIANT_PRESETS["Modern Web"])
        self._variant_results: dict[int, VariantResult] = {}
        self._variant_worker: threading.Thread | None = None
        self._variant_generation_id: int = 0

        self._load_source_images()
        self.loss_warnings: list[LossWarning] = audit_conversion(self.source_path, self.output_path)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_content_area()
        self._build_footer()

    def _load_source_images(self) -> None:
        try:
            if self.source_path.exists():
                with Image.open(self.source_path) as im:
                    self.orig_pil = im.convert("RGBA")
        except Exception:
            self.orig_pil = None

        try:
            if self.output_path and self.output_path.exists():
                with Image.open(self.output_path) as im:
                    self.conv_pil = im.convert("RGBA")
        except Exception:
            self.conv_pil = None

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=24, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", fill="y")

        ctk.CTkLabel(
            title_frame,
            text=self.source_path.name,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w")

        orig_size_str = format_file_size(self.source_path.stat().st_size) if self.source_path.exists() else "0 B"
        self._header_info_label = ctk.CTkLabel(
            title_frame,
            text=f"Original: {orig_size_str}",
            font=ctk.CTkFont(size=12),
            text_color=("#667085", "#98a2b3"),
        )
        self._header_info_label.pack(anchor="w")

        self.metrics_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        self.metrics_frame.pack(anchor="w", pady=(6, 0))
        self._refresh_header_metrics()

        # Headline losses (full list lives in the EXIF & Details view).
        serious = [w for w in self.loss_warnings if w.severity in ("high", "medium")]
        for warning in serious[:3]:
            ctk.CTkLabel(
                title_frame,
                text=f"⚠ {warning.title}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_SEVERITY_COLOURS[warning.severity],
            ).pack(anchor="w", pady=(4 if warning is serious[0] else 0, 0))
        if len(serious) > 3:
            ctk.CTkLabel(
                title_frame,
                text=f"+ {len(serious) - 3} more in EXIF & Details",
                font=ctk.CTkFont(size=10),
                text_color=_SEVERITY_COLOURS["info"],
            ).pack(anchor="w")

        modes = ["Split Slider", "Side-by-Side", "Multi-Variant", "Difference Map", "EXIF & Details"] if (self.output_path or self.conv_pil) else ["Multi-Variant", "Side-by-Side", "EXIF & Details"]
        self.mode_selector = ctk.CTkSegmentedButton(
            header,
            values=modes,
            variable=self.view_mode,
            command=self._on_mode_change,
        )
        self.mode_selector.pack(side="right", padx=(10, 0))

    def _ensure_split_modes_available(self) -> None:
        full_modes = ["Split Slider", "Side-by-Side", "Multi-Variant", "Difference Map", "EXIF & Details"]
        if hasattr(self, "mode_selector") and self.mode_selector.winfo_exists():
            self.mode_selector.configure(values=full_modes)

    def _refresh_header_metrics(self) -> None:
        if not hasattr(self, "metrics_frame") or not self.metrics_frame.winfo_exists():
            return
        for child in self.metrics_frame.winfo_children():
            child.destroy()

        orig_size_str = format_file_size(self.source_path.stat().st_size) if self.source_path.exists() else "0 B"
        if self._active_variant_label:
            info = f"Original: {orig_size_str}  ➔  Active Variant: {self._active_variant_label}"
        elif self.result and self.result.saved:
            info = f"Original: {orig_size_str}  ➔  Output: {self.result.output_size_text} ({self.result.saved} saved)"
        else:
            info = f"Original: {orig_size_str}"

        if hasattr(self, "_header_info_label") and self._header_info_label.winfo_exists():
            self._header_info_label.configure(text=info)

        if self.orig_pil is not None and self.conv_pil is not None:
            metrics = calculate_comparison_metrics(self.orig_pil, self.conv_pil)
            psnr_val = metrics["psnr"]
            psnr_text = "∞ dB" if math.isinf(float(psnr_val)) else f"{float(psnr_val):.1f} dB"
            sample_note = " · sampled" if metrics["sampled"] else ""
            for label, value in (
                ("PSNR", psnr_text),
                ("Similarity", f"{float(metrics['similarity']):.1f}%"),
                ("Mean error", f"{float(metrics['mae']):.2f}{sample_note}"),
            ):
                chip = ctk.CTkFrame(
                    self.metrics_frame,
                    fg_color=("#E8F7F4", "#17312E"),
                    corner_radius=6,
                )
                chip.pack(side="left", padx=(0, 6))
                ctk.CTkLabel(
                    chip,
                    text=f"{label}  {value}",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color=("#0E756B", "#70E1D4"),
                ).pack(padx=8, pady=4)

    def _build_content_area(self) -> None:
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.grid(row=1, column=0, padx=24, pady=8, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        self._render_active_view()

    def _on_mode_change(self, _val: str) -> None:
        for child in self.content_frame.winfo_children():
            child.destroy()
        self._render_active_view()

    def _render_active_view(self) -> None:
        mode = self.view_mode.get()
        if mode == "Split Slider" and self.orig_pil and self.conv_pil:
            self._render_split_slider_view()
        elif mode == "Difference Map" and self.orig_pil and self.conv_pil:
            self._render_diff_map_view()
        elif mode == "Multi-Variant" and self.orig_pil:
            self._render_multi_variant_view()
        elif mode == "EXIF & Details":
            self._render_details_view()
        else:
            self._render_side_by_side_view()

    def _prepare_display_images(self, max_w: int = 740, max_h: int = 440) -> None:
        if not self.orig_pil:
            return
        w, h = self.orig_pil.size
        base_ratio = min(max_w / w, max_h / h, 1.0)
        eff_ratio = base_ratio * self.zoom_factor
        disp_w = max(1, int(w * eff_ratio))
        disp_h = max(1, int(h * eff_ratio))
        self.disp_size = (disp_w, disp_h)

        self.disp_orig = self.orig_pil.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        if self.conv_pil:
            self.disp_conv = self.conv_pil.resize((disp_w, disp_h), Image.Resampling.LANCZOS)

    def _render_split_slider_view(self) -> None:
        container = ctk.CTkFrame(
            self.content_frame,
            corner_radius=10,
            fg_color=("#ffffff", "#191c20"),
            border_width=1,
            border_color=("#eaecf0", "#344054"),
        )
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        # Instructions banner & zoom controls
        top_bar = ctk.CTkFrame(container, fg_color="transparent")
        top_bar.grid(row=0, column=0, padx=16, pady=(10, 4), sticky="ew")

        ctk.CTkLabel(
            top_bar,
            text="◀ ORIGINAL",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#17A594",
        ).pack(side="left")

        ctk.CTkLabel(
            top_bar,
            text="Drag line horizontally to inspect compression quality",
            font=ctk.CTkFont(size=11),
            text_color=("#667085", "#98a2b3"),
        ).pack(side="left", padx=16)

        ctk.CTkLabel(
            top_bar,
            text="COMPRESSED ▶",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#16a34a",
        ).pack(side="right")

        # Zoom Controls
        zoom_bar = ctk.CTkFrame(top_bar, fg_color="transparent")
        zoom_bar.pack(side="right", padx=(0, 16))

        ctk.CTkButton(
            zoom_bar,
            text="−",
            width=24,
            height=22,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._zoom_out,
        ).pack(side="left", padx=2)

        self.zoom_lbl = ctk.CTkLabel(
            zoom_bar,
            text=f"{int(self.zoom_factor * 100)}%",
            width=40,
            font=ctk.CTkFont(size=11),
        )
        self.zoom_lbl.pack(side="left")

        ctk.CTkButton(
            zoom_bar,
            text="+",
            width=24,
            height=22,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._zoom_in,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            zoom_bar,
            text="Fit",
            width=32,
            height=22,
            font=ctk.CTkFont(size=10),
            command=self._zoom_fit,
        ).pack(side="left", padx=2)

        self._prepare_display_images(max_w=740, max_h=440)
        disp_w, disp_h = self.disp_size

        self.canvas = tk.Canvas(
            container,
            width=disp_w,
            height=disp_h,
            bg="#0f1115",
            highlightthickness=0,
            cursor="sb_h_double_arrow",
        )
        self.canvas.grid(row=1, column=0, padx=16, pady=(4, 4))

        self.canvas.bind("<B1-Motion>", self._on_slider_drag)
        self.canvas.bind("<Button-1>", self._on_slider_drag)
        self.canvas.bind("<Motion>", self._on_probe_motion)

        self.probe_lbl = ctk.CTkLabel(
            container,
            text=format_probe(None),
            font=ctk.CTkFont(family="Menlo" if sys.platform == "darwin" else "Consolas", size=11),
            text_color=("#667085", "#98a2b3"),
        )
        self.probe_lbl.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="w")

        self._draw_split_canvas()

    def _on_probe_motion(self, event: tk.Event) -> None:
        """Pixel inspector: source coordinates and RGBA of both images under the pointer."""
        if self.orig_pil is None or not hasattr(self, "probe_lbl"):
            return
        point = display_to_source(int(event.x), int(event.y), self.disp_size, self.orig_pil.size)
        probe = pixel_probe(self.orig_pil, self.conv_pil, *point) if point else None
        self.probe_lbl.configure(text=format_probe(probe))

    def _zoom_in(self) -> None:
        if self.zoom_factor < 2.5:
            self.zoom_factor = min(2.5, round(self.zoom_factor + 0.25, 2))
            self._update_zoom()

    def _zoom_out(self) -> None:
        if self.zoom_factor > 0.5:
            self.zoom_factor = max(0.5, round(self.zoom_factor - 0.25, 2))
            self._update_zoom()

    def _zoom_fit(self) -> None:
        self.zoom_factor = 1.0
        self._update_zoom()

    def _update_zoom(self) -> None:
        if hasattr(self, "zoom_lbl"):
            self.zoom_lbl.configure(text=f"{int(self.zoom_factor * 100)}%")
        self._prepare_display_images(max_w=740, max_h=440)
        disp_w, disp_h = self.disp_size
        if hasattr(self, "canvas") and self.canvas.winfo_exists():
            self.canvas.configure(width=disp_w, height=disp_h)
            self._draw_split_canvas()

    def _on_slider_drag(self, event: tk.Event) -> None:
        disp_w, _ = self.disp_size
        pct = max(0.01, min(0.99, event.x / max(1, disp_w)))
        self.split_pct = pct
        self._draw_split_canvas()

    def _draw_split_canvas(self) -> None:
        if not self.disp_orig or not self.disp_conv:
            return
        disp_w, disp_h = self.disp_size
        split_x = max(1, min(disp_w - 1, int(disp_w * self.split_pct)))

        # Composite original (left) and converted (right)
        comp = Image.new("RGBA", (disp_w, disp_h))
        crop_left = self.disp_orig.crop((0, 0, split_x, disp_h))
        comp.paste(crop_left, (0, 0))

        crop_right = self.disp_conv.crop((split_x, 0, disp_w, disp_h))
        comp.paste(crop_right, (split_x, 0))

        # Draw divider line
        draw = ImageDraw.Draw(comp)
        draw.line([(split_x, 0), (split_x, disp_h)], fill=(255, 255, 255, 220), width=2)
        # Center grip circle
        cy = disp_h // 2
        draw.ellipse([(split_x - 12, cy - 12), (split_x + 12, cy + 12)], fill=(255, 255, 255, 240), outline=(30, 30, 30, 200), width=2)
        draw.line([(split_x - 4, cy), (split_x - 1, cy)], fill=(40, 40, 40), width=2)
        draw.line([(split_x + 1, cy), (split_x + 4, cy)], fill=(40, 40, 40), width=2)

        self.tk_canvas_img = ImageTk.PhotoImage(comp)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_canvas_img)

    def _render_diff_map_view(self) -> None:
        container = ctk.CTkFrame(
            self.content_frame,
            corner_radius=10,
            fg_color=("#ffffff", "#191c20"),
            border_width=1,
            border_color=("#eaecf0", "#344054"),
        )
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            container,
            text="Pixel Difference Map (Amplified x10 to highlight compression artifacts)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#d97706", "#f59e0b"),
        ).grid(row=0, column=0, padx=16, pady=(10, 4), sticky="w")

        self._prepare_display_images(max_w=740, max_h=440)
        disp_w, disp_h = self.disp_size

        # Compute difference
        diff = ImageChops.difference(
            self.disp_orig.convert("RGB"),
            self.disp_conv.convert("RGB"),
        )
        # Amplify difference for visual clarity
        diff_amplified = diff.point(lambda p: min(255, p * 10))

        diff_canvas = tk.Canvas(
            container,
            width=disp_w,
            height=disp_h,
            bg="#000000",
            highlightthickness=0,
        )
        diff_canvas.grid(row=1, column=0, padx=16, pady=(4, 16))

        self.tk_canvas_img = ImageTk.PhotoImage(diff_amplified)
        diff_canvas.create_image(0, 0, anchor="nw", image=self.tk_canvas_img)

    def _render_multi_variant_view(self) -> None:
        container = ctk.CTkFrame(
            self.content_frame,
            corner_radius=10,
            fg_color=("#ffffff", "#191c20"),
            border_width=1,
            border_color=("#eaecf0", "#344054"),
        )
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        # Top controls
        top_bar = ctk.CTkFrame(container, fg_color="transparent")
        top_bar.grid(row=0, column=0, padx=16, pady=(12, 8), sticky="ew")

        ctk.CTkLabel(
            top_bar,
            text="Preset:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))

        preset_menu = ctk.CTkOptionMenu(
            top_bar,
            values=list(VARIANT_PRESETS.keys()),
            variable=self._variant_preset,
            command=self._on_preset_selected,
            width=180,
            height=28,
        )
        preset_menu.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(
            top_bar,
            text="Slots:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))

        self.slot_count_var = tk.StringVar(value=str(len(self._variant_slots)))
        slot_menu = ctk.CTkOptionMenu(
            top_bar,
            values=["2", "3", "4"],
            variable=self.slot_count_var,
            command=self._on_slot_count_changed,
            width=65,
            height=28,
        )
        slot_menu.pack(side="left", padx=(0, 14))

        self.refresh_btn = ctk.CTkButton(
            top_bar,
            text="⟳ Re-encode",
            width=100,
            height=28,
            fg_color="#16a394",
            command=self._trigger_variant_generation,
        )
        self.refresh_btn.pack(side="left", padx=(0, 14))

        self.variant_status_lbl = ctk.CTkLabel(
            top_bar,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("#667085", "#98a2b3"),
        )
        self.variant_status_lbl.pack(side="left")

        # Scrollable area for cards
        self.cards_scroll = ctk.CTkScrollableFrame(
            container,
            fg_color="transparent",
            orientation="horizontal",
            height=460,
        )
        self.cards_scroll.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")

        self._render_variant_cards()
        if not self._variant_results:
            self._trigger_variant_generation()

    def _on_preset_selected(self, preset_name: str) -> None:
        if preset_name in VARIANT_PRESETS and preset_name != "Custom":
            self._variant_slots = list(VARIANT_PRESETS[preset_name])
            if hasattr(self, "slot_count_var"):
                self.slot_count_var.set(str(len(self._variant_slots)))
            self._render_variant_cards()
            self._trigger_variant_generation()

    def _on_slot_count_changed(self, count_str: str) -> None:
        try:
            count = int(count_str)
        except ValueError:
            return
        defaults = [("WEBP", 80), ("AVIF", 65), ("JPEG", 80), ("HEIC", 70)]
        if len(self._variant_slots) < count:
            while len(self._variant_slots) < count:
                idx = len(self._variant_slots) % len(defaults)
                self._variant_slots.append(defaults[idx])
        elif len(self._variant_slots) > count:
            self._variant_slots = self._variant_slots[:count]
        self._variant_preset.set("Custom")
        self._render_variant_cards()
        self._trigger_variant_generation()

    def _on_slot_codec_changed(self, slot_idx: int, new_codec: str) -> None:
        if 0 <= slot_idx < len(self._variant_slots):
            cur_q = self._variant_slots[slot_idx][1]
            self._variant_slots[slot_idx] = (new_codec, cur_q)
            self._variant_preset.set("Custom")
            self._trigger_variant_generation()

    def _on_slot_quality_changed(self, slot_idx: int, new_q_str: str) -> None:
        try:
            val = int(new_q_str)
            val = max(1, min(100, val))
        except ValueError:
            return
        if 0 <= slot_idx < len(self._variant_slots):
            cur_c = self._variant_slots[slot_idx][0]
            if self._variant_slots[slot_idx][1] != val:
                self._variant_slots[slot_idx] = (cur_c, val)
                self._variant_preset.set("Custom")
                self._trigger_variant_generation()

    def _trigger_variant_generation(self) -> None:
        if self.orig_pil is None:
            return
        self._variant_generation_id += 1
        gen_id = self._variant_generation_id

        if hasattr(self, "refresh_btn") and self.refresh_btn.winfo_exists():
            self.refresh_btn.configure(state="disabled")
        if hasattr(self, "variant_status_lbl") and self.variant_status_lbl.winfo_exists():
            self.variant_status_lbl.configure(text="Encoding variants in background...")

        source_img = self.orig_pil.copy()
        slots_to_encode = list(self._variant_slots)

        def _worker() -> None:
            results: dict[int, VariantResult] = {}
            for idx, (codec, quality) in enumerate(slots_to_encode):
                if self._variant_generation_id != gen_id:
                    return
                res = generate_variant(source_img, codec, quality, max_edge=800)
                results[idx] = res

            if self._variant_generation_id == gen_id:
                try:
                    self.after(0, lambda: self._on_variants_generated(gen_id, results))
                except Exception:
                    pass

        self._variant_worker = threading.Thread(target=_worker, daemon=True)
        self._variant_worker.start()

    def _on_variants_generated(self, gen_id: int, results: dict[int, VariantResult]) -> None:
        if self._variant_generation_id != gen_id:
            return
        self._variant_results = results
        if hasattr(self, "refresh_btn") and self.refresh_btn.winfo_exists():
            self.refresh_btn.configure(state="normal")
        if hasattr(self, "variant_status_lbl") and self.variant_status_lbl.winfo_exists():
            self.variant_status_lbl.configure(text=f"Ready · {len(results)} variants rendered")
        if self.view_mode.get() == "Multi-Variant":
            self._render_variant_cards()

    def _render_variant_cards(self) -> None:
        if not hasattr(self, "cards_scroll") or not self.cards_scroll.winfo_exists():
            return
        for child in self.cards_scroll.winfo_children():
            child.destroy()

        orig_size = self.source_path.stat().st_size if self.source_path.exists() else 0
        codec_choices = ["WEBP", "AVIF", "HEIC", "JPEG", "JPEG 2000", "PNG"]

        for idx, (codec, quality) in enumerate(self._variant_slots):
            card = ctk.CTkFrame(
                self.cards_scroll,
                width=260,
                corner_radius=10,
                fg_color=("#ffffff", "#16191d"),
                border_width=1,
                border_color=("#e2e8f0", "#2d333b"),
            )
            card.pack(side="left", padx=8, pady=8, fill="y")
            card.pack_propagate(False)

            # Slot header row
            hdr_row = ctk.CTkFrame(card, fg_color="transparent")
            hdr_row.pack(fill="x", padx=12, pady=(10, 6))

            ctk.CTkLabel(
                hdr_row,
                text=f"#{idx + 1}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("#667085", "#98a2b3"),
            ).pack(side="left", padx=(0, 6))

            codec_var = tk.StringVar(value=codec)
            c_menu = ctk.CTkOptionMenu(
                hdr_row,
                values=codec_choices,
                variable=codec_var,
                command=lambda new_c, s_idx=idx: self._on_slot_codec_changed(s_idx, new_c),
                width=100,
                height=26,
            )
            c_menu.pack(side="left", padx=(0, 8))

            if codec != "PNG":
                ctk.CTkLabel(
                    hdr_row,
                    text="q:",
                    font=ctk.CTkFont(size=11),
                    text_color=("#667085", "#98a2b3"),
                ).pack(side="left", padx=(0, 2))
                q_entry = ctk.CTkEntry(hdr_row, width=42, height=26, font=ctk.CTkFont(size=11))
                q_entry.insert(0, str(quality))
                q_entry.pack(side="left")
                q_entry.bind(
                    "<FocusOut>",
                    lambda _e, s_idx=idx, ent=q_entry: self._on_slot_quality_changed(s_idx, ent.get()),
                )
                q_entry.bind(
                    "<Return>",
                    lambda _e, s_idx=idx, ent=q_entry: self._on_slot_quality_changed(s_idx, ent.get()),
                )

            # Thumbnail area
            thumb_box = ctk.CTkFrame(
                card,
                width=236,
                height=160,
                corner_radius=8,
                fg_color=("#0f1115", "#0f1115"),
            )
            thumb_box.pack(padx=12, pady=4)
            thumb_box.pack_propagate(False)

            res = self._variant_results.get(idx)
            if res is not None:
                if res.error:
                    ctk.CTkLabel(
                        thumb_box,
                        text=f"Encode Error:\n{res.error}",
                        font=ctk.CTkFont(size=10),
                        text_color="#ef4444",
                        wraplength=210,
                    ).pack(expand=True, padx=8)
                else:
                    try:
                        thumb = res.image.copy()
                        thumb.thumbnail((230, 150), Image.Resampling.LANCZOS)
                        ctk_img = ctk.CTkImage(
                            light_image=thumb,
                            dark_image=thumb,
                            size=(thumb.width, thumb.height),
                        )
                        ctk.CTkLabel(thumb_box, text="", image=ctk_img).pack(expand=True)
                    except Exception as err:
                        ctk.CTkLabel(thumb_box, text=f"Preview error:\n{err}", text_color="gray60").pack(expand=True)
            else:
                ctk.CTkLabel(
                    thumb_box,
                    text="Rendering variant…",
                    font=ctk.CTkFont(size=11),
                    text_color="#94a3b8",
                ).pack(expand=True)

            # Metrics container
            metrics_box = ctk.CTkFrame(card, fg_color=("#f8fafc", "#121417"), corner_radius=6)
            metrics_box.pack(fill="x", padx=12, pady=6)

            if res is not None and not res.error:
                size_str = format_file_size(res.estimated_full_bytes)
                if orig_size > 0:
                    pct = ((orig_size - res.estimated_full_bytes) / orig_size) * 100.0
                    saved_text = f"-{pct:.1f}%" if pct >= 0 else f"+{abs(pct):.1f}%"
                    saved_color = ("#16a34a", "#4ade80") if pct >= 0 else ("#d97706", "#fbbf24")
                else:
                    saved_text = ""
                    saved_color = ("#64748b", "#94a3b8")

                if res.ssim >= 0.98:
                    q_badge = "Near-lossless"
                    q_color = ("#0284c7", "#38bdf8")
                elif res.ssim >= 0.94:
                    q_badge = "High fidelity"
                    q_color = ("#16a34a", "#4ade80")
                elif res.ssim >= 0.88:
                    q_badge = "Good quality"
                    q_color = ("#d97706", "#fbbf24")
                else:
                    q_badge = "Lossy"
                    q_color = ("#dc2626", "#f87171")

                psnr_txt = "∞ dB" if math.isinf(res.psnr) else f"{res.psnr:.1f} dB"

                ctk.CTkLabel(
                    metrics_box,
                    text=f"Size: {size_str}  ({saved_text})" if saved_text else f"Size: {size_str}",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=saved_color,
                    anchor="w",
                ).pack(anchor="w", padx=8, pady=(4, 1))

                ctk.CTkLabel(
                    metrics_box,
                    text=f"SSIM: {res.ssim:.3f} · {q_badge}",
                    font=ctk.CTkFont(size=10),
                    text_color=q_color,
                    anchor="w",
                ).pack(anchor="w", padx=8, pady=1)

                ctk.CTkLabel(
                    metrics_box,
                    text=f"PSNR: {psnr_txt} · {res.encode_ms:.0f} ms",
                    font=ctk.CTkFont(size=10),
                    text_color=("#64748b", "#94a3b8"),
                    anchor="w",
                ).pack(anchor="w", padx=8, pady=(1, 4))
            else:
                ctk.CTkLabel(
                    metrics_box,
                    text="Metrics unavailable" if (res and res.error) else "Computing metrics…",
                    font=ctk.CTkFont(size=10),
                    text_color=("#64748b", "#94a3b8"),
                ).pack(padx=8, pady=12)

            # Actions row
            actions_frame = ctk.CTkFrame(card, fg_color="transparent")
            actions_frame.pack(fill="x", padx=12, pady=(2, 10))

            can_act = res is not None and not res.error
            ctk.CTkButton(
                actions_frame,
                text="🔍 Split Slider",
                font=ctk.CTkFont(size=11, weight="bold"),
                height=26,
                fg_color="#16a394" if can_act else "gray50",
                state="normal" if can_act else "disabled",
                command=lambda r=res, c=codec, q=quality: self._compare_variant_in_slider(r, c, q) if r else None,
            ).pack(fill="x", pady=(0, 4))

            btn_row = ctk.CTkFrame(actions_frame, fg_color="transparent")
            btn_row.pack(fill="x")

            if self.on_apply:
                ctk.CTkButton(
                    btn_row,
                    text="✓ Apply",
                    font=ctk.CTkFont(size=10),
                    height=24,
                    fg_color=("#2563eb", "#1d4ed8") if can_act else "gray50",
                    state="normal" if can_act else "disabled",
                    command=lambda c=codec, q=quality: self._apply_variant_to_app(c, q),
                ).pack(side="left", expand=True, fill="x", padx=(0, 2))

            ctk.CTkButton(
                btn_row,
                text="💾 Save",
                font=ctk.CTkFont(size=10),
                height=24,
                fg_color="transparent",
                border_width=1,
                border_color=("#cbd5e1", "#334155"),
                text_color=("#334155", "#f1f5f9"),
                state="normal" if can_act else "disabled",
                command=lambda r=res: self._save_variant_as(r) if r else None,
            ).pack(side="left", expand=True, fill="x", padx=(2, 0))

    def _compare_variant_in_slider(self, res: VariantResult, codec: str, quality: int) -> None:
        self.conv_pil = res.image.convert("RGBA")
        self._active_variant_label = f"{codec} q{quality}"
        self._ensure_split_modes_available()
        self._refresh_header_metrics()
        self.view_mode.set("Split Slider")
        self._on_mode_change("Split Slider")

    def _apply_variant_to_app(self, codec: str, quality: int) -> None:
        if self.on_apply:
            self.on_apply(codec, quality)
            if hasattr(self, "variant_status_lbl") and self.variant_status_lbl.winfo_exists():
                self.variant_status_lbl.configure(
                    text=f"✓ Applied {codec} q{quality} to main application!"
                )

    def _save_variant_as(self, res: VariantResult) -> None:
        ext_map = {
            "WEBP": ".webp",
            "AVIF": ".avif",
            "HEIC": ".heic",
            "JPEG": ".jpg",
            "JPEG 2000": ".jp2",
            "PNG": ".png",
        }
        ext = ext_map.get(res.codec, f".{res.codec.lower()}")
        default_name = f"{self.source_path.stem}_{res.codec.lower()}_q{res.quality}{ext}"
        out_file = filedialog.asksaveasfilename(
            parent=self,
            title="Save Variant As...",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[(f"{res.codec} Image", f"*{ext}"), ("All Files", "*.*")],
        )
        if out_file:
            try:
                full_src = self.orig_pil or Image.open(self.source_path)
                full_variant = generate_variant(full_src, res.codec, res.quality, max_edge=10000)
                if full_variant.error:
                    messagebox.showerror("Save Failed", full_variant.error, parent=self)
                else:
                    full_variant.image.save(out_file)
                    messagebox.showinfo("Saved", f"Variant saved to:\n{out_file}", parent=self)
            except Exception as err:
                messagebox.showerror("Save Failed", str(err), parent=self)

    def _render_side_by_side_view(self) -> None:
        grid_box = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        grid_box.grid(row=0, column=0, sticky="nsew")
        grid_box.grid_columnconfigure((0, 1), weight=1)
        grid_box.grid_rowconfigure(0, weight=1)

        self._build_panel(
            grid_box,
            col=0,
            title="Original Image",
            image_path=self.source_path,
            is_output=False,
        )

        self._build_panel(
            grid_box,
            col=1,
            title="Converted Output",
            image_path=self.output_path,
            is_output=True,
        )

    def _build_panel(
        self,
        parent: ctk.CTkFrame,
        col: int,
        title: str,
        image_path: Path | None,
        is_output: bool,
    ) -> None:
        card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            border_width=1,
            border_color=("#eaecf0", "#344054"),
            fg_color=("#ffffff", "#191c20"),
        )
        card.grid(row=0, column=col, padx=8, pady=4, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        panel_title = title
        if is_output and self._active_variant_label and (not image_path or not image_path.exists()):
            panel_title = f"Variant: {self._active_variant_label}"

        ctk.CTkLabel(
            card,
            text=panel_title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#1d2939", "#f2f4f7"),
        ).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        preview_area = ctk.CTkFrame(card, fg_color=("#f8fafc", "#121417"), corner_radius=8)
        preview_area.grid(row=1, column=0, padx=14, pady=6, sticky="nsew")
        preview_area.grid_rowconfigure(0, weight=1)
        preview_area.grid_columnconfigure(0, weight=1)

        info_text = ""
        if image_path and image_path.exists():
            try:
                with Image.open(image_path) as pil_img:
                    w, h = pil_img.size
                    mode = pil_img.mode
                    fmt = pil_img.format or image_path.suffix.upper().replace(".", "")

                    max_w, max_h = 320, 260
                    ratio = min(max_w / w, max_h / h, 1.0)
                    thumb_w = max(1, int(w * ratio))
                    thumb_h = max(1, int(h * ratio))

                    preview_img = pil_img.copy()
                    preview_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(
                        light_image=preview_img,
                        dark_image=preview_img,
                        size=(thumb_w, thumb_h),
                    )
                    ctk.CTkLabel(preview_area, text="", image=ctk_img).grid(row=0, column=0)

                size_str = format_file_size(image_path.stat().st_size)
                if is_output and self.result:
                    info_text = f"{w} × {h} px  •  {fmt}  •  {size_str}  ({self.result.saved} saved)"
                else:
                    info_text = f"{w} × {h} px  •  {fmt} ({mode})  •  {size_str}"
            except Exception as err:
                ctk.CTkLabel(
                    preview_area,
                    text=f"Cannot preview image:\n{err}",
                    text_color="gray60",
                ).grid(row=0, column=0)
        elif is_output and self.conv_pil:
            try:
                w, h = self.conv_pil.size
                max_w, max_h = 320, 260
                ratio = min(max_w / w, max_h / h, 1.0)
                thumb_w = max(1, int(w * ratio))
                thumb_h = max(1, int(h * ratio))

                preview_img = self.conv_pil.copy()
                preview_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                ctk_img = ctk.CTkImage(
                    light_image=preview_img,
                    dark_image=preview_img,
                    size=(thumb_w, thumb_h),
                )
                ctk.CTkLabel(preview_area, text="", image=ctk_img).grid(row=0, column=0)
                v_label = self._active_variant_label or "Variant Preview"
                info_text = f"{w} × {h} px  •  {v_label}"
            except Exception as err:
                ctk.CTkLabel(
                    preview_area,
                    text=f"Cannot preview variant:\n{err}",
                    text_color="gray60",
                ).grid(row=0, column=0)
        else:
            msg = "Not yet converted" if is_output else "Image not found"
            ctk.CTkLabel(preview_area, text=msg, text_color="gray60").grid(row=0, column=0)

        if info_text:
            ctk.CTkLabel(
                card,
                text=info_text,
                font=ctk.CTkFont(size=11),
                text_color=("#667085", "#98a2b3"),
            ).grid(row=2, column=0, padx=16, pady=(4, 12), sticky="w")
        else:
            ctk.CTkLabel(card, text="").grid(row=2, column=0, pady=4)

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=24, pady=(8, 16), sticky="ew")

        if self.output_path:
            ctk.CTkButton(
                footer,
                text="Open Converted File",
                command=lambda: open_file_or_folder(self.output_path),
                width=140,
                height=32,
            ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            footer,
            text="Reveal in Explorer",
            command=lambda: reveal_in_file_manager(self.output_path or self.source_path),
            width=130,
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=("#d0d5dd", "#475467"),
            text_color=("#344054", "#f2f4f7"),
        ).pack(side="left")

        ctk.CTkButton(
            footer,
            text="Close",
            command=self.destroy,
            width=90,
            height=32,
        ).pack(side="right")

    def _render_details_view(self) -> None:
        container = ctk.CTkScrollableFrame(
            self.content_frame,
            corner_radius=10,
            fg_color=("#ffffff", "#191c20"),
            border_width=1,
            border_color=("#eaecf0", "#344054"),
        )
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(
            container,
            text="Technical Metadata & EXIF Audit",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("#1d2939", "#f2f4f7"),
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(12, 10), sticky="w")

        # Original Details
        self._build_metadata_card(container, col=0, title="Original File", path=self.source_path)

        # Output Details
        self._build_metadata_card(container, col=1, title="Converted Output", path=self.output_path)

        self._build_loss_card(container)

    def _build_loss_card(self, parent: ctk.CTkFrame) -> None:
        card = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=("#f8fafc", "#121417"),
            border_width=1,
            border_color=("#e2e8f0", "#2d333b"),
        )
        card.grid(row=2, column=0, columnspan=2, padx=8, pady=(8, 4), sticky="ew")
        ctk.CTkLabel(
            card,
            text="What this conversion changed or discarded",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        if not self.output_path:
            message = "Convert this file to audit what was lost."
        elif not self.loss_warnings:
            message = "Nothing notable: transparency, animation, bit depth, colour profile and resolution all carried over."
        else:
            message = ""
        if message:
            ctk.CTkLabel(card, text=message, font=ctk.CTkFont(size=11), text_color=_SEVERITY_COLOURS["info"]).pack(anchor="w", padx=12, pady=(0, 10))
            return
        for warning in self.loss_warnings:
            ctk.CTkLabel(
                card,
                text=f"⚠ {warning.title}" if warning.severity != "info" else f"• {warning.title}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_SEVERITY_COLOURS[warning.severity],
            ).pack(anchor="w", padx=12, pady=(4, 0))
            ctk.CTkLabel(
                card,
                text=warning.detail,
                font=ctk.CTkFont(size=11),
                text_color=("#475467", "#cbd5e1"),
                wraplength=860,
                justify="left",
            ).pack(anchor="w", padx=24, pady=(0, 2))
        ctk.CTkFrame(card, fg_color="transparent", height=6).pack()

    def _build_metadata_card(
        self, parent: ctk.CTkFrame, col: int, title: str, path: Path | None
    ) -> None:
        card = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=("#f8fafc", "#121417"),
            border_width=1,
            border_color=("#e2e8f0", "#2d333b"),
        )
        card.grid(row=1, column=col, padx=8, pady=4, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#17A594" if col == 0 else "#16a34a",
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 6), sticky="w")

        if not path or not path.exists():
            ctk.CTkLabel(
                card, text="File not generated or missing", text_color="gray60"
            ).grid(row=1, column=0, padx=12, pady=8)
            return

        props: list[tuple[str, str]] = []
        try:
            props.append(("File Name", path.name))
            props.append(("File Size", format_file_size(path.stat().st_size)))
            with Image.open(path) as im:
                props.append(("Resolution", f"{im.width} × {im.height} px"))
                props.append(("Color Mode", im.mode))
                props.append(("Format", im.format or path.suffix.upper().strip(".")))
                has_icc = "Yes" if "icc_profile" in im.info else "No"
                props.append(("ICC Profile", has_icc))

                exif = im.getexif()
                if exif:
                    for tag_id, val in exif.items():
                        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                        if tag_name in (
                            "Make",
                            "Model",
                            "Software",
                            "DateTime",
                            "Artist",
                            "LensModel",
                            "ISOSpeedRatings",
                            "FNumber",
                            "ExposureTime",
                        ):
                            props.append((tag_name, str(val)))
                else:
                    props.append(("EXIF Data", "None / Stripped"))
        except Exception as e:
            props.append(("Status", f"Error reading: {e}"))

        for idx, (k, v) in enumerate(props, start=1):
            ctk.CTkLabel(
                card,
                text=f"{k}:",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#667085", "#98a2b3"),
                anchor="w",
            ).grid(row=idx, column=0, padx=(12, 6), pady=2, sticky="w")
            ctk.CTkLabel(
                card, text=str(v), font=ctk.CTkFont(size=11), anchor="w"
            ).grid(row=idx, column=1, padx=(0, 12), pady=2, sticky="w")
