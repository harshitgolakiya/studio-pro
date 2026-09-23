from __future__ import annotations

import logging
from typing import Any

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit(
        "Missing required dependency: customtkinter. Please run: python -m pip install -r requirements.txt"
    ) from exc

# Patch CustomTkinter performance bottlenecks during appearance mode switching:
# 1. CTkTabview._draw recursively called tab.configure(...) which forced every descendant
#    widget across all tabs to re-execute configure() and redraw, causing massive UI freezes.
# 2. CTkOptionMenu._draw called self._canvas.update_idletasks() mid-draw, triggering synchronous
#    geometry recalculation storms during batch appearance mode updates.
# 3. AppearanceModeTracker.set_appearance_mode("system") previously failed to detect and notify
#    callbacks immediately upon switching to System theme.
try:
    from customtkinter.windows.widgets.appearance_mode import AppearanceModeTracker

    def _tabview_fast_draw(self, no_color_updates: bool = False):
        super(ctk.CTkTabview, self)._draw(no_color_updates)
        if not self._canvas.winfo_exists():
            return
        requires_recoloring = self._draw_engine.draw_rounded_rect_with_border(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(
                self._current_height - self._outer_spacing - self._outer_button_overhang
            ),
            self._apply_widget_scaling(self._corner_radius),
            self._apply_widget_scaling(self._border_width),
        )
        if no_color_updates is False or requires_recoloring:
            if self._fg_color == "transparent":
                target_fg = self._apply_appearance_mode(self._bg_color)
            else:
                target_fg = self._apply_appearance_mode(self._fg_color)
            self._canvas.itemconfig("inner_parts", fill=target_fg, outline=target_fg)
            self._canvas.itemconfig(
                "border_parts",
                fill=self._apply_appearance_mode(self._border_color),
                outline=self._apply_appearance_mode(self._border_color),
            )
            bg_color = self._apply_appearance_mode(self._bg_color)
            self._canvas.configure(bg=bg_color)
            tk.Frame.configure(self, bg=bg_color)
            for tab in self._tab_dict.values():
                if tab._canvas.winfo_exists():
                    tab._canvas.configure(bg=target_fg)
                    tk.Frame.configure(tab, bg=target_fg)

    ctk.CTkTabview._draw = _tabview_fast_draw

    def _optionmenu_fast_draw(self, no_color_updates: bool = False):
        super(ctk.CTkOptionMenu, self)._draw(no_color_updates)
        left_section_width = self._current_width - self._current_height
        requires_recoloring = self._draw_engine.draw_rounded_rect_with_border_vertical_split(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(self._current_height),
            self._apply_widget_scaling(self._corner_radius),
            0,
            self._apply_widget_scaling(left_section_width),
        )
        requires_recoloring_2 = self._draw_engine.draw_dropdown_arrow(
            self._apply_widget_scaling(self._current_width - (self._current_height / 2)),
            self._apply_widget_scaling(self._current_height / 2),
            self._apply_widget_scaling(self._current_height / 3),
        )
        if no_color_updates is False or requires_recoloring or requires_recoloring_2:
            self._canvas.configure(bg=self._apply_appearance_mode(self._bg_color))
            self._canvas.itemconfig(
                "inner_parts_left",
                outline=self._apply_appearance_mode(self._fg_color),
                fill=self._apply_appearance_mode(self._fg_color),
            )
            self._canvas.itemconfig(
                "inner_parts_right",
                outline=self._apply_appearance_mode(self._button_color),
                fill=self._apply_appearance_mode(self._button_color),
            )
            if self._state == tk.DISABLED:
                self._text_label.configure(fg=self._apply_appearance_mode(self._text_color_disabled))
                self._canvas.itemconfig(
                    "dropdown_arrow",
                    fill=self._apply_appearance_mode(self._text_color_disabled),
                )
            else:
                self._text_label.configure(fg=self._apply_appearance_mode(self._text_color))
                self._canvas.itemconfig(
                    "dropdown_arrow",
                    fill=self._apply_appearance_mode(self._text_color),
                )
            self._text_label.configure(bg=self._apply_appearance_mode(self._fg_color))
        # Note: self._canvas.update_idletasks() omitted intentionally to avoid UI stalls

    ctk.CTkOptionMenu._draw = _optionmenu_fast_draw

    def _baseclass_fast_set_appearance_mode(self, mode_string):
        super(ctk.CTkBaseClass, self)._set_appearance_mode(mode_string)
        self._draw()

    ctk.CTkBaseClass._set_appearance_mode = _baseclass_fast_set_appearance_mode

    _orig_set_appearance_mode = AppearanceModeTracker.set_appearance_mode.__func__

    @classmethod
    def _patched_set_appearance_mode(cls, mode_string: str):
        if mode_string.lower() == "system":
            cls.appearance_mode_set_by = "system"
            new_mode = cls.detect_appearance_mode()
            if new_mode != cls.appearance_mode:
                cls.appearance_mode = new_mode
                cls.update_callbacks()
        else:
            _orig_set_appearance_mode(cls, mode_string)

    AppearanceModeTracker.set_appearance_mode = _patched_set_appearance_mode
except Exception:
    pass


from app_bootstrap import ensure_runtime_dependencies_noisy

# No-op in a packaged build (see app_bootstrap.py) -- only auto-installs
# missing pip packages for a source/dev run. Must stay that way: in a frozen
# exe, sys.executable IS the app itself, so "installing" a package by
# shelling out to it would just relaunch the whole GUI as a subprocess.
try:
    ensure_runtime_dependencies_noisy()
except RuntimeError as exc:
    message = str(exc)
    print(message, file=sys.stderr)
    raise SystemExit(message) from exc

from font_loader import BODY_FONT, DISPLAY_FONT, load_bundled_fonts

# Must happen before any CTkFont()/widget is created -- font family
# resolution happens at creation time, not lazily.
load_bundled_fonts()

try:
    from drag_drop import hook_dropfiles, unhook_dropfiles

    HAS_DRAG_DROP = True
except ImportError:
    HAS_DRAG_DROP = False

from command_palette import CommandPalette, PaletteAction
from converter import (
    DEFAULT_OPERATION_ORDER,
    IMAGE_OUTPUT_FORMATS,
    OPERATION_LABELS,
    normalize_operation_order,
    LOSSY_IMAGE_FORMATS,
    SUPPORTED_EXTENSIONS,
    RAW_EXTENSIONS,
    SVG_EXTENSIONS,
    ConversionResult,
    combine_images_to_pdf,
    convert_image,
    estimate_image_output_size,
    normalize_output_format,
)
from diagnostics import export_diagnostics, setup_logging
from doc_converter import SUPPORTED_DOCUMENT_EXTENSIONS, convert_document
from format_browser import FormatBrowserDialog, describe_format, render_capability_badges
from history import record_batch
from history_dialog import HistoryDialog
from license_dialog import LicenseDialog
from licensing import FREE_BATCH_LIMIT, is_pro_activated, is_vip_activated
from media_engine import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    convert_media_file,
    get_best_hardware_encoder,
    get_ffmpeg_path,
)
from optimizer_dialog import OptimizerDialog
from preflight import disk_preflight, find_duplicates
from preview_modal import ImagePreviewDialog
from queue_store import (
    build_state,
    clear_queue_state,
    load_queue_state,
    persistence_enabled,
    queue_state_path,
    save_queue_state,
    synthesize_result,
)
from recipe_dialog import RecipeManagerDialog
from recipes import RECIPE_FIELDS
from settings import load_settings, update_setting
from telemetry import BatchTelemetry, recommend_workers
import temp_tracker
from url_downloader_dialog import URLDownloaderDialog
from video_trimmer_dialog import VideoTrimmerDialog
from watch_folder_dialog import WatchFolderDialog
from utils import (
    build_destination_filename,
    copy_image_file_to_clipboard,
    copy_text_to_clipboard,
    export_results_to_csv,
    format_file_size,
    next_available_output_path,
    open_file_or_folder,
    play_completion_sound,
    reveal_in_file_manager,
    scan_directory_for_images,
    slugify_filename,
)

ALL_MEDIA_EXTENSIONS = (
    SUPPORTED_EXTENSIONS
    | SUPPORTED_VIDEO_EXTENSIONS
    | SUPPORTED_AUDIO_EXTENSIONS
    | SUPPORTED_DOCUMENT_EXTENSIONS
)
IMAGE_FORMAT_OPTIONS = [
    "PDF (Combined)" if fmt == "PDF" else fmt
    for fmt in IMAGE_OUTPUT_FORMATS
]

APP_BACKGROUND = ("#F3F6F8", "#090C10")
APP_SURFACE = ("#FFFFFF", "#11161D")
APP_ELEVATED = ("#E9EEF3", "#1A2029")
APP_ACCENT = "#16A394"
APP_ACCENT_DARK = "#0E756B"
APP_ACCENT_SOFT = "#D8F3EF"
APP_ACCENT_TINT = "#4DD9C8"
APP_SECONDARY = "#70E1D4"
APP_TEXT = ("#14212B", "#F4F7FA")
APP_MUTED = ("#607181", "#91A0AE")
APP_CTA = "#D4A03C"
APP_CTA_STRONG = "#E8B750"
APP_BORDER = ("#D6DFE7", "#27303B")

# Density presets map to CustomTkinter's global widget scaling, which rescales
# paddings, fonts and control heights together so the layout stays coherent.
DENSITY_SCALES = {"Compact": 0.88, "Comfortable": 1.0}


class WebPCompressorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.log = setup_logging()
        stale = temp_tracker.cleanup_stale()
        if stale:
            self.log.info("removed %d stale temp file(s) from an interrupted batch", len(stale))
        self.duplicate_of: dict[Path, Path] = {}

        self.title("Shadow Media Studio Pro")
        self.geometry("1180x860")
        self.minsize(980, 720)
        self._apply_window_icon()
        self._show_setup_status_if_needed()
        self.after(200, self._show_missing_runtime_warning_if_needed)

        self.selected_files: list[Path] = []
        self.output_directory = tk.StringVar(
            value=self.settings.get("last_output_directory", "")
        )
        self.save_in_source_folder = tk.BooleanVar(
            value=self.settings.get("save_in_source_folder", False)
        )
        self.target_format = tk.StringVar(
            value=self.settings.get("default_format", "WEBP")
        )
        self.quality = tk.IntVar(
            value=self.settings.get("default_quality", 80)
        )
        self.quality_text = tk.StringVar(value=str(self.quality.get()))
        self.overwrite = tk.BooleanVar(value=False)
        self.lossless = tk.BooleanVar(value=False)
        self.preserve_metadata = tk.BooleanVar(value=False)
        self.strip_metadata = tk.BooleanVar(
            value=self.settings.get("strip_metadata", False)
        )
        self.play_sound = tk.BooleanVar(
            value=self.settings.get("play_sound", True)
        )
        self.slugify_names = tk.BooleanVar(value=False)

        # Smart Sizer (Target Size)
        self.enable_target_size = tk.BooleanVar(value=False)
        self.target_size_val = tk.StringVar(value="200")
        self.target_size_unit = tk.StringVar(value="KB")
        # Perceptual-quality controls (SSIM 0-1): a floor for the size solver
        # and a standalone quality-target mode.
        self.protect_quality = tk.BooleanVar(value=False)
        self.min_ssim_text = tk.StringVar(value="0.95")
        self.enable_quality_target = tk.BooleanVar(value=False)
        self.target_ssim_text = tk.StringVar(value="0.95")
        # Processing stack order (comma-separated step names, see converter).
        self.operation_order = tk.StringVar(value=",".join(DEFAULT_OPERATION_ORDER))

        # Resizing
        self.enable_resize = tk.BooleanVar(
            value=self.settings.get("enable_resize", False)
        )
        self.max_dimension_text = tk.StringVar(
            value=self.settings.get("max_dimension", "1920")
        )
        self.scale_percent_text = tk.StringVar(
            value=self.settings.get("scale_percent", "75")
        )
        self.resize_condition = tk.StringVar(
            value=self.settings.get("resize_condition", "Always")
        )

        # Transformations & Enhancements
        self.rotate_angle = tk.StringVar(value="0°")
        self.flip_h = tk.BooleanVar(value=False)
        self.flip_v = tk.BooleanVar(value=False)
        self.aspect_ratio = tk.StringVar(value="Original")
        self.enable_rounded = tk.BooleanVar(value=False)
        self.corner_radius = tk.StringVar(value="20")
        self.grayscale = tk.BooleanVar(value=False)
        self.normalize_audio = tk.BooleanVar(value=False)
        self.color_profile_mode = tk.StringVar(
            value=self.settings.get("color_profile_mode", "Preserve (Source)")
        )
        self.color_profile_custom = tk.StringVar(
            value=self.settings.get("color_profile_custom", "")
        )
        self.rendering_intent = tk.StringVar(
            value=self.settings.get("rendering_intent", "Relative Colorimetric")
        )
        self.bit_depth = tk.StringVar(
            value=self.settings.get("bit_depth", "Auto (Match Codec)")
        )
        self.hdr_tone_mapping = tk.StringVar(
            value=self.settings.get("hdr_tone_mapping", "None / Direct")
        )
        self.hdr_exposure = tk.StringVar(
            value=str(self.settings.get("hdr_exposure", "0.0"))
        )
        self.raw_white_balance = tk.StringVar(
            value=self.settings.get("raw_white_balance", "Camera As Shot")
        )
        self.raw_exposure = tk.StringVar(
            value=str(self.settings.get("raw_exposure", "0.0"))
        )
        self.raw_demosaic = tk.StringVar(
            value=self.settings.get("raw_demosaic", "Auto (High Quality)")
        )
        self.svg_scale = tk.StringVar(
            value=self.settings.get("svg_scale", "1.0x (Default)")
        )
        self.svg_background = tk.StringVar(
            value=self.settings.get("svg_background", "Transparent")
        )
        self.psd_composite_mode = tk.StringVar(
            value=self.settings.get("psd_composite_mode", "merged")
        )
        self.psd_layer_index = tk.StringVar(
            value=str(self.settings.get("psd_layer_index", "-1"))
        )

        # Batch Renaming
        self.filename_prefix = tk.StringVar(value="")
        self.filename_suffix = tk.StringVar(value="")

        # Preset Optimization Profile
        self.preset_profile = tk.StringVar(value="Manual / Custom")
        self._current_smart_category: str | None = None

        # Search & Filter
        self.search_filter = tk.StringVar(value="")

        # Sorting
        self.sort_column = "filename"
        self.sort_desc = False

        # Watermarking
        self.enable_watermark = tk.BooleanVar(
            value=self.settings.get("enable_watermark", False)
        )
        self.watermark_text = tk.StringVar(
            value=self.settings.get("watermark_text", "")
        )
        self.watermark_type = tk.StringVar(
            value=self.settings.get("watermark_type", "Text")
        )
        self.watermark_logo_path = tk.StringVar(
            value=self.settings.get("watermark_logo_path", "")
        )
        self.watermark_position = tk.StringVar(
            value=self.settings.get("watermark_position", "bottom-right")
        )
        self.watermark_condition = tk.StringVar(
            value=self.settings.get("watermark_condition", "Always")
        )

        self.status_text = tk.StringVar(value="Ready to convert")
        self.estimate_text = tk.StringVar(value="Add an image to estimate output size")
        self.progress_value = tk.DoubleVar(value=0)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.conversion_running = False
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()  # set = paused; workers wait between items
        self.row_ids: dict[Path, str] = {}
        self.row_results: dict[Path, ConversionResult] = {}
        self.file_overrides: dict[Path, dict[str, object]] = {}
        self.copied_file_override: dict[str, object] | None = None
        self._override_undo: list[dict[Path, dict[str, object]]] = []
        self._override_redo: list[dict[Path, dict[str, object]]] = []
        self._queue_undo: list[tuple[list[Path], dict[Path, dict[str, object]]]] = []
        self._queue_redo: list[tuple[list[Path], dict[Path, dict[str, object]]]] = []
        self._recipe_undo: list[dict[str, Any]] = []
        self._recipe_redo: list[dict[str, Any]] = []
        self.last_results: list[ConversionResult] = []
        self.image_count_text = tk.StringVar(value="0 items")
        self.total_size_text = tk.StringVar(value="")
        self.active_watcher: object | None = None
        self._estimate_after_id: str | None = None
        self._estimate_generation = 0

        self._apply_density(self.settings.get("density", "Comfortable"))
        self._build_interface()
        self._setup_estimate_traces()
        self._setup_drag_and_drop()
        self._setup_context_menu()
        self._bind_shortcuts()
        self.after(100, self._process_events)
        self._load_cli_arguments()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

        self.queue_state_file = queue_state_path()
        self._queue_persistence_enabled = persistence_enabled()
        self._queue_save_job: str | None = None
        if self._queue_persistence_enabled and len(sys.argv) <= 1:
            self.after(300, self._offer_queue_restore)

        # A fast/large resize (dragging the window edge, or restoring from
        # maximized) can outrun Tk's redraw, leaving stale widgets from the
        # old layout visibly overlapping the new one until something forces
        # a repaint. Debounced so this doesn't fire on every pixel of a drag.
        self._resize_redraw_job: str | None = None
        self.bind("<Configure>", self._on_window_configure)

    def _on_window_configure(self, _event: tk.Event) -> None:
        if _event.widget != self:
            return
        if self._resize_redraw_job is not None:
            self.after_cancel(self._resize_redraw_job)
        self._resize_redraw_job = self.after(120, self._force_redraw_after_resize)

    def _force_redraw_after_resize(self) -> None:
        self._resize_redraw_job = None
        try:
            # update_idletasks() alone recomputes widget geometry but does not
            # reliably force CTk's canvas-drawn rounded-corner frames to
            # repaint stale pixels left over from the pre-resize layout.
            # update() also flushes pending expose/redraw events.
            self.update()
        except Exception:
            pass

    def _load_cli_arguments(self) -> None:
        if len(sys.argv) > 1:
            cli_paths: list[Path] = []
            for arg in sys.argv[1:]:
                p = Path(arg).resolve()
                if p.is_dir():
                    cli_paths.extend(
                        scan_directory_for_images(
                            p, ALL_MEDIA_EXTENSIONS, recursive=True
                        )
                    )
                elif p.is_file() and p.suffix.lower() in ALL_MEDIA_EXTENSIONS:
                    cli_paths.append(p)
            if cli_paths:
                self.after(200, lambda: self._ingest_image_paths(cli_paths))

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-a>", lambda _e: self._select_all_rows())
        self.bind("<Control-A>", lambda _e: self._select_all_rows())
        self.bind("<Delete>", lambda _e: self._remove_selected())
        self.bind("<Control-o>", lambda _e: self._add_files())
        self.bind("<Control-O>", lambda _e: self._add_files())
        self.bind("<Alt-Up>", lambda _e: self._move_selected_up())
        self.bind("<Alt-Down>", lambda _e: self._move_selected_down())
        self.bind("<Control-Return>", lambda _e: self._start_conversion())
        self.bind("<Control-k>", lambda _e: self._open_command_palette())
        self.bind("<Control-K>", lambda _e: self._open_command_palette())
        self.bind("<Control-Shift-P>", lambda _e: self._open_command_palette())
        self.bind("<Control-z>", lambda _e: self._undo_editor_change())
        self.bind("<Control-y>", lambda _e: self._redo_editor_change())

    @staticmethod
    def _resource_path(relative_path: str) -> Path:
        base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return base_path / relative_path

    def _apply_window_icon(self) -> None:
        icon_path = self._resource_path("assets/icon.ico")
        if icon_path.exists():
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

    def _show_setup_status_if_needed(self) -> None:
        try:
            from app_bootstrap import get_setup_guidance_message
            guidance = get_setup_guidance_message()
            if "Everything looks ready" not in guidance:
                self.status_text = tk.StringVar(value=guidance)
        except Exception:
            pass

    def _show_missing_runtime_warning_if_needed(self) -> None:
        try:
            from app_bootstrap import get_setup_guidance_message
            guidance = get_setup_guidance_message()
            if "Everything looks ready" in guidance:
                return
            messagebox.showwarning(
                "Setup required",
                guidance + "\n\nThis is needed for video/audio conversion and URL download features.",
            )
        except Exception:
            pass

    def _build_interface(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.configure(fg_color=APP_BACKGROUND)

        # Top navigation shell
        header = ctk.CTkFrame(self, fg_color=APP_BACKGROUND, corner_radius=0, height=72)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, padx=(28, 12), pady=14, sticky="w")

        logo_badge = ctk.CTkLabel(
            brand,
            text="S",
            width=36,
            height=36,
            corner_radius=11,
            fg_color=APP_ACCENT,
            text_color="#ffffff",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        logo_badge.pack(side="left")

        brand_copy = ctk.CTkFrame(brand, fg_color="transparent")
        brand_copy.pack(side="left", padx=(11, 0))
        ctk.CTkLabel(
            brand_copy,
            text="Shadow Media Studio Pro",
            font=ctk.CTkFont(family=DISPLAY_FONT, size=19, weight="bold"),
            text_color=APP_TEXT,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_copy,
            text="Convert · optimize · automate",
            font=ctk.CTkFont(size=10),
            text_color=APP_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(0, 1))

        # Header Right Actions
        header_right = ctk.CTkFrame(header, fg_color="transparent")
        header_right.grid(row=0, column=2, padx=(0, 28), sticky="e")

        is_vip = is_vip_activated()
        is_pro = is_pro_activated()
        if is_vip:
            badge_text = "VIP MASTER"
            badge_color = APP_CTA
            badge_text_color = "#171308"
        elif is_pro:
            badge_text = "PRO LIFETIME"
            badge_color = "#16a34a"
            badge_text_color = "#ffffff"
        else:
            badge_text = "FREE TRIAL"
            badge_color = "#eab308"
            badge_text_color = "#171308"

        self.license_badge = ctk.CTkButton(
            header_right,
            text=badge_text,
            width=96,
            height=24,
            corner_radius=6,
            fg_color=badge_color,
            hover_color=badge_color,
            text_color=badge_text_color,
            font=ctk.CTkFont(size=9, weight="bold"),
            command=self._open_license_manager,
        )
        self.license_badge.pack(side="left", padx=(0, 10))

        self.license_btn_header = ctk.CTkButton(
            header_right,
            text="VIP Key" if is_vip else ("License" if is_pro else "Upgrade to Pro"),
            command=self._open_license_manager,
            width=105 if is_pro else 120,
            height=30,
            corner_radius=7,
            fg_color=APP_ACCENT if not is_pro else "transparent",
            border_width=0 if not is_pro else 1,
            border_color=APP_BORDER,
            text_color=APP_TEXT if not is_pro else APP_MUTED,
            font=ctk.CTkFont(weight="bold" if not is_pro else "normal"),
        )
        self.license_btn_header.pack(side="left", padx=(0, 10))

        self.history_button = ctk.CTkButton(
            header_right,
            text="History",
            command=self._open_history,
            width=78,
            height=30,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
        )
        self.history_button.pack(side="left", padx=(0, 8))

        self.density_menu = ctk.CTkOptionMenu(
            header_right,
            values=list(DENSITY_SCALES),
            command=self._change_density,
            width=112,
            height=30,
            corner_radius=7,
        )
        self.density_menu.set(self.settings.get("density", "Comfortable"))
        self.density_menu.pack(side="left", padx=(0, 8))

        self.theme_menu = ctk.CTkOptionMenu(
            header_right,
            values=["System", "Dark", "Light"],
            command=self._change_appearance_mode,
            width=90,
            height=30,
            corner_radius=7,
        )
        self.theme_menu.set(self.settings.get("theme", "System"))
        self.theme_menu.pack(side="left")

        ctk.CTkFrame(self, fg_color=APP_BORDER, height=1, corner_radius=0).grid(
            row=0, column=0, sticky="sew"
        )

        # Use the entire working canvas. The old layout intentionally pinned
        # every card to a narrow left column and left a large dead zone.
        content_shell = ctk.CTkFrame(self, fg_color="transparent")
        content_shell.grid(row=1, column=0, sticky="nsew")
        content_shell.grid_rowconfigure(0, weight=1)
        content_shell.grid_columnconfigure(0, weight=1)

        content_inner = ctk.CTkFrame(content_shell, fg_color="transparent")
        content_inner.grid(row=0, column=0, sticky="nsew")
        content_inner.grid_rowconfigure(0, weight=1)
        content_inner.grid_columnconfigure(0, weight=1)

        # Workspace Container
        workspace = ctk.CTkFrame(content_inner, fg_color="transparent")
        workspace.grid(row=0, column=0, padx=32, pady=(18, 10), sticky="nsew")
        workspace.grid_rowconfigure(1, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        # List Header / Action Bar
        list_header = ctk.CTkFrame(workspace, fg_color=APP_SURFACE, corner_radius=12, border_width=1, border_color=APP_BORDER)
        list_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        list_header.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            list_header,
            text="Media Queue",
            font=ctk.CTkFont(family=DISPLAY_FONT, size=16, weight="bold"),
            text_color=APP_TEXT,
        ).grid(row=0, column=0, padx=(14, 0), pady=(12, 6), sticky="w")

        info_box = ctk.CTkFrame(list_header, fg_color="transparent")
        info_box.grid(row=0, column=1, padx=(10, 0), pady=(12, 6), sticky="w")
        ctk.CTkLabel(
            info_box,
            textvariable=self.image_count_text,
            text_color=APP_MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            info_box,
            textvariable=self.total_size_text,
            text_color=APP_MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(4, 0))

        # Filter entry centered/right
        self.filter_entry = ctk.CTkEntry(
            list_header,
            textvariable=self.search_filter,
            placeholder_text="Filter by filename…",
            width=210,
            height=32,
            corner_radius=8,
        )
        self.filter_entry.grid(row=0, column=3, padx=(0, 8), pady=(12, 6), sticky="e")
        self.filter_entry.bind("<KeyRelease>", self._apply_filter)

        actions = ctk.CTkFrame(list_header, fg_color="transparent")
        actions.grid(row=1, column=0, columnspan=5, padx=14, pady=(6, 12), sticky="e")

        self.move_up_button = ctk.CTkButton(
            actions,
            text="▲",
            command=self._move_selected_up,
            width=28,
            height=28,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
            state="disabled",
        )
        self.move_up_button.pack(side="left", padx=(0, 2))

        self.move_down_button = ctk.CTkButton(
            actions,
            text="▼",
            command=self._move_selected_down,
            width=28,
            height=28,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
            state="disabled",
        )
        self.move_down_button.pack(side="left", padx=(0, 6))

        self.preview_button = ctk.CTkButton(
            actions,
            text="Preview",
            command=self._open_selected_preview,
            width=68,
            height=28,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
            state="disabled",
        )
        self.preview_button.pack(side="left", padx=(0, 4))

        self.optimize_button = ctk.CTkButton(
            actions,
            text="Optimize",
            command=self._open_selected_optimizer,
            width=74,
            height=28,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
            state="disabled",
        )
        self.optimize_button.pack(side="left", padx=(0, 4))

        self.remove_button = ctk.CTkButton(
            actions,
            text="Remove",
            command=self._remove_selected,
            width=68,
            height=28,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
            state="disabled",
        )
        self.remove_button.pack(side="left", padx=(0, 4))

        self.clear_button = ctk.CTkButton(
            actions,
            text="Clear",
            command=self._clear_all,
            width=58,
            height=28,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
            state="disabled",
        )
        self.clear_button.pack(side="left", padx=(0, 8))

        self.watch_folder_button = ctk.CTkButton(
            actions,
            text="📁 Auto-Watch",
            command=self._open_watch_folder_dialog,
            width=96,
            height=28,
            corner_radius=7,
            fg_color=APP_ELEVATED,
            hover_color=APP_ACCENT,
            text_color=APP_TEXT,
        )
        self.watch_folder_button.pack(side="left", padx=(0, 4))

        self.vip_downloader_button = ctk.CTkButton(
            actions,
            text="⚡ Download URL" if is_vip else "🔒 Download URL",
            command=self._open_url_downloader,
            width=120,
            height=28,
            corner_radius=7,
            fg_color=APP_CTA if is_vip else APP_ELEVATED,
            hover_color=APP_CTA_STRONG if is_vip else APP_ACCENT,
            text_color=APP_TEXT,
            font=ctk.CTkFont(weight="bold" if is_vip else "normal"),
        )
        self.vip_downloader_button.pack(side="left", padx=(0, 4))

        self.add_folder_button = ctk.CTkButton(
            actions,
            text="📁 Add Folder",
            command=self._add_folder,
            width=92,
            height=28,
            corner_radius=7,
            fg_color=APP_ELEVATED,
            hover_color=APP_ACCENT,
            text_color=APP_TEXT,
        )
        self.add_folder_button.pack(side="left", padx=(0, 4))

        self.add_button = ctk.CTkButton(
            actions,
            text="+ Add Media",
            command=self._add_files,
            width=96,
            height=28,
            corner_radius=7,
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            text_color=APP_TEXT,
            font=ctk.CTkFont(weight="bold"),
        )
        self.add_button.pack(side="left")

        # Empty State
        self.empty_state = ctk.CTkFrame(
            workspace,
            corner_radius=18,
            border_width=1,
            border_color=APP_BORDER,
            fg_color=APP_SURFACE,
        )
        self.empty_state.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.empty_state.grid_columnconfigure(0, weight=1)
        self.empty_state.grid_rowconfigure(0, weight=1)

        empty_content = ctk.CTkFrame(self.empty_state, fg_color="transparent")
        empty_content.grid(row=0, column=0)

        ctk.CTkLabel(
            empty_content,
            text="＋",
            width=48,
            height=48,
            corner_radius=14,
            fg_color=(APP_ACCENT_SOFT, "#1e293b"),
            text_color=(APP_ACCENT, APP_ACCENT_TINT),
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(pady=(12, 6))

        ctk.CTkLabel(
            empty_content,
            text="Build your conversion queue",
            font=ctk.CTkFont(family=DISPLAY_FONT, size=18, weight="bold"),
            text_color=APP_TEXT,
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            empty_content,
            text="Drop files or folders anywhere · 48 image extensions · video, audio and documents",
            text_color=APP_MUTED,
            font=ctk.CTkFont(size=11),
            wraplength=820,
        ).pack(pady=(0, 10))

        empty_buttons = ctk.CTkFrame(empty_content, fg_color="transparent")
        empty_buttons.pack(pady=(0, 12))
        ctk.CTkButton(
            empty_buttons,
            text="＋ Add files",
            command=self._add_files,
            width=120,
            height=32,
            corner_radius=8,
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            text_color="white",
            font=ctk.CTkFont(weight="bold", size=12),
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            empty_buttons,
            text="Add folder",
            command=self._add_folder,
            width=120,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
            text_color=("#334155", "#f1f5f9"),
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=5)

        # Table Frame
        self.table_frame = ctk.CTkFrame(
            workspace,
            corner_radius=16,
            fg_color=APP_SURFACE,
            border_width=1,
            border_color=APP_BORDER,
        )
        self.table_frame.grid_columnconfigure(0, weight=1)
        self.table_frame.grid_rowconfigure(0, weight=1)

        self.table_style = ttk.Style(self)
        self.table_style.theme_use("clam")
        self._apply_table_theme()

        columns = ("filename", "original", "output", "saved", "status")
        self.table = ttk.Treeview(
            self.table_frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "filename": "Filename",
            "original": "Original Size",
            "output": "Output Size",
            "saved": "Saved",
            "status": "Status",
        }
        widths = {
            "filename": 0,
            "original": 125,
            "output": 125,
            "saved": 105,
            "status": 145,
        }
        for column in columns:
            self.table.heading(
                column,
                text=headings[column],
                command=lambda c=column: self._sort_table_by_column(c),
            )
            self.table.column(
                column,
                width=widths[column],
                minwidth=90 if column != "filename" else 180,
                stretch=column == "filename",
                anchor="w",
            )
        self.table.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        scrollbar = ttk.Scrollbar(
            self.table_frame, orient="vertical", command=self.table.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind(
            "<<TreeviewSelect>>", lambda _event: self._update_button_states()
        )
        self.table.bind("<Double-1>", self._on_double_click_row)
        self.table_frame.grid_remove()

        # Studio Settings Tabview (Modern Segmented Creative Suite Controls)
        self.settings_tabview = ctk.CTkTabview(
            content_inner,
            corner_radius=12,
            fg_color=APP_SURFACE,
            border_width=1,
            border_color=APP_BORDER,
            segmented_button_fg_color=APP_SURFACE,
            segmented_button_selected_color=APP_ACCENT,
            segmented_button_selected_hover_color=APP_ACCENT_TINT,
            segmented_button_unselected_color=APP_ELEVATED,
            segmented_button_unselected_hover_color="#2A2E38",
            text_color=APP_TEXT,
            height=38,
        )
        self.settings_tabview.grid(row=1, column=0, padx=32, pady=(0, 8), sticky="ew")

        tab_format = self.settings_tabview.add("Format & Presets")
        tab_transform = self.settings_tabview.add("Edit & Transform")
        tab_naming = self.settings_tabview.add("Renaming & Safety")
        tab_watermark = self.settings_tabview.add("Watermark")

        # ==========================================
        # TAB 1: FORMAT & PRESETS
        # ==========================================
        self.smart_header_frame = ctk.CTkFrame(tab_format, fg_color="transparent")
        self.smart_header_frame.pack(fill="x", pady=(2, 6))

        self.smart_badge = ctk.CTkLabel(
            self.smart_header_frame,
            text="✨ Smart Settings: Auto-Detect Ready",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#e2e8f0", "#1e293b"),
            text_color=("#334155", "#94a3b8"),
            corner_radius=6,
            height=26,
            padx=10,
        )
        self.smart_badge.pack(side="left")

        self.smart_info_label = ctk.CTkLabel(
            self.smart_header_frame,
            text="Select or drop media to auto-tune options",
            font=ctk.CTkFont(size=11),
            text_color=("#64748b", "#94a3b8"),
        )
        self.smart_info_label.pack(side="left", padx=(8, 0))

        self.estimate_label = ctk.CTkLabel(
            self.smart_header_frame,
            textvariable=self.estimate_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#0E756B", "#70E1D4"),
        )
        self.estimate_label.pack(side="right", padx=(10, 0))

        self.smart_trim_btn = ctk.CTkButton(
            self.smart_header_frame,
            text="✂️ Cut / Trim Clip",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=26,
            width=116,
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            command=self._open_selected_trimmer,
        )

        fmt_row0 = ctk.CTkFrame(tab_format, fg_color="transparent")
        fmt_row0.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            fmt_row0,
            text="Target Format:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#0f172a", "#f8fafc"),
        ).pack(side="left", padx=(0, 6))

        format_options = [
            *IMAGE_FORMAT_OPTIONS,
            "Video: WebM",
            "Video: MP4",
            "Video -> Animated WebP",
            "Video -> GIF",
            "Video -> Audio (MP3)",
            "Audio: MP3",
            "Audio: AAC",
            "Audio: Opus",
        ]
        self.format_menu = ctk.CTkOptionMenu(
            fmt_row0,
            values=format_options,
            variable=self.target_format,
            command=self._format_changed,
            width=165,
            height=28,
            corner_radius=6,
        )
        self.format_menu.pack(side="left", padx=(0, 6))
        self.format_browse_button = ctk.CTkButton(
            fmt_row0,
            text="Browse…",
            width=78,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=APP_ELEVATED,
            hover_color=APP_BORDER,
            text_color=APP_TEXT,
            command=self._open_format_browser,
        )
        self.format_browse_button.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(
            fmt_row0,
            text="Profile:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#0f172a", "#f8fafc"),
        ).pack(side="left", padx=(0, 6))

        preset_profiles = [
            "Manual / Custom",
            "🌐 Next-Gen AVIF (75%)",
            "⚡ Web Banner (1920px 80%)",
            "🛍️ E-Commerce (1000px 85%)",
            "📱 Avatar 1:1 (PNG)",
            "💬 Discord 24MB Video",
            "📧 Email Doc (≤5MB)",
            "📄 PDF Binder",
        ]
        self.preset_menu = ctk.CTkOptionMenu(
            fmt_row0,
            values=preset_profiles,
            variable=self.preset_profile,
            command=self._apply_preset_profile,
            width=175,
            height=28,
            corner_radius=6,
        )
        self.preset_menu.pack(side="left", padx=(0, 6))
        self.recipes_button = ctk.CTkButton(
            fmt_row0,
            text="Recipes…",
            width=82,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=APP_ELEVATED,
            hover_color=APP_BORDER,
            text_color=APP_TEXT,
            command=self._open_recipe_manager,
        )
        self.recipes_button.pack(side="left", padx=(0, 12))

        for name, q_val in (
            ("Balanced", 80),
            ("High", 90),
            ("Compact", 60),
            ("Lossless", 80),
        ):
            ctk.CTkButton(
                fmt_row0,
                text=name,
                width=65,
                height=26,
                corner_radius=6,
                font=ctk.CTkFont(size=11),
                fg_color=("gray92", "#22262d"),
                hover_color=("gray85", "#2c313a"),
                text_color=("#334155", "#f1f5f9"),
                command=lambda q=q_val, l=(name == "Lossless"): self._apply_preset(
                    q, l
                ),
            ).pack(side="left", padx=2)

        self.format_capability_frame = ctk.CTkFrame(tab_format, fg_color="transparent")
        self.format_capability_frame.pack(fill="x", pady=(0, 5))
        self._update_format_capabilities(self.target_format.get())

        # Sizing / Constraints Row
        size_row = ctk.CTkFrame(tab_format, fg_color="transparent")
        size_row.pack(fill="x", pady=(2, 2))

        ssim_row = ctk.CTkFrame(tab_format, fg_color="transparent")
        ssim_row.pack(fill="x", pady=(0, 2), after=size_row)
        ctk.CTkCheckBox(
            ssim_row,
            text="Protect quality: keep SSIM ≥",
            variable=self.protect_quality,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self.min_ssim_entry = ctk.CTkEntry(
            ssim_row, width=50, height=24, textvariable=self.min_ssim_text, justify="center"
        )
        self.min_ssim_entry.pack(side="left", padx=(4, 20))
        ctk.CTkCheckBox(
            ssim_row,
            text="Quality target instead of slider: SSIM",
            variable=self.enable_quality_target,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self.target_ssim_entry = ctk.CTkEntry(
            ssim_row, width=50, height=24, textvariable=self.target_ssim_text, justify="center"
        )
        self.target_ssim_entry.pack(side="left", padx=(4, 6))
        ctk.CTkLabel(
            ssim_row,
            text="(lossy image formats; 0.95 ≈ visually lossless, 0.90 = clearly compressed)",
            font=ctk.CTkFont(size=10),
            text_color=APP_MUTED,
        ).pack(side="left")

        ctk.CTkCheckBox(
            size_row,
            text="Target size solver:",
            variable=self.enable_target_size,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self.target_size_entry = ctk.CTkEntry(
            size_row, width=54, height=24, textvariable=self.target_size_val, justify="center"
        )
        self.target_size_entry.pack(side="left", padx=4)
        ctk.CTkOptionMenu(
            size_row,
            values=["KB", "MB"],
            variable=self.target_size_unit,
            width=62,
            height=24,
            corner_radius=5,
        ).pack(side="left", padx=(0, 20))

        ctk.CTkCheckBox(
            size_row,
            text="Resize max px:",
            variable=self.enable_resize,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self.max_dim_entry = ctk.CTkEntry(
            size_row, width=56, height=24, textvariable=self.max_dimension_text, justify="center"
        )
        self.max_dim_entry.pack(side="left", padx=(4, 12))

        ctk.CTkLabel(
            size_row,
            text="Scale %:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.scale_entry = ctk.CTkEntry(
            size_row, width=48, height=24, textvariable=self.scale_percent_text, justify="center"
        )
        self.scale_entry.pack(side="left")

        # Quality Row (Direct input box positioned after Scale %)
        self.quality_row = ctk.CTkFrame(size_row, fg_color="transparent")
        self.quality_row.pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            self.quality_row,
            text="Quality:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))

        self.quality_slider = None

        self.quality_entry = ctk.CTkEntry(
            self.quality_row,
            width=48,
            height=24,
            textvariable=self.quality_text,
            justify="center",
            corner_radius=5,
        )
        self.quality_entry.pack(side="left")
        self.quality_entry.bind(
            "<FocusOut>", lambda _event: self._sync_quality_from_entry()
        )
        self.quality_entry.bind(
            "<Return>", lambda _event: self._sync_quality_from_entry()
        )
        self.quality_entry.bind(
            "<KeyRelease>", lambda _event: self._on_quality_key_release()
        )

        self.when_label = ctk.CTkLabel(
            size_row,
            text="When:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        )
        self.when_label.pack(side="left", padx=(10, 4))
        self.resize_cond_menu = ctk.CTkOptionMenu(
            size_row,
            values=["Always", "Only if larger", "Only above 4K", "Only above 2K"],
            variable=self.resize_condition,
            width=115,
            height=24,
            corner_radius=5,
            font=ctk.CTkFont(size=10),
        )
        self.resize_cond_menu.pack(side="left")

        # ==========================================
        # TAB 2: EDIT & TRANSFORM
        # ==========================================
        tr_row0 = ctk.CTkFrame(tab_transform, fg_color="transparent")
        tr_row0.pack(fill="x", pady=(4, 6))

        ctk.CTkLabel(
            tr_row0,
            text="Rotate:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 6))
        self.rotate_menu = ctk.CTkOptionMenu(
            tr_row0,
            values=["0°", "90° CW", "180°", "270° CW"],
            variable=self.rotate_angle,
            width=88,
            height=26,
            corner_radius=6,
        )
        self.rotate_menu.pack(side="left", padx=(0, 16))

        ctk.CTkCheckBox(tr_row0, text="Flip Horizontal", variable=self.flip_h, font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 12))
        ctk.CTkCheckBox(tr_row0, text="Flip Vertical", variable=self.flip_v, font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(
            tr_row0,
            text="Aspect Ratio Crop:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 6))
        self.aspect_menu = ctk.CTkOptionMenu(
            tr_row0,
            values=["Original", "1:1", "16:9", "4:3", "9:16"],
            variable=self.aspect_ratio,
            width=96,
            height=26,
            corner_radius=6,
        )
        self.aspect_menu.pack(side="left")

        tr_row1 = ctk.CTkFrame(tab_transform, fg_color="transparent")
        tr_row1.pack(fill="x", pady=(4, 2))

        ctk.CTkCheckBox(tr_row1, text="Rounded Corners:", variable=self.enable_rounded, font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
        self.corner_entry = ctk.CTkEntry(tr_row1, width=44, height=24, textvariable=self.corner_radius, justify="center")
        self.corner_entry.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(tr_row1, text="px radius", font=ctk.CTkFont(size=11), text_color=("#64748b", "#94a3b8")).pack(side="left", padx=(0, 18))

        ctk.CTkCheckBox(tr_row1, text="Grayscale (Monochrome B&W)", variable=self.grayscale, font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 18))
        ctk.CTkCheckBox(tr_row1, text="Broadcast Audio Loudnorm (EBU R128)", variable=self.normalize_audio, font=ctk.CTkFont(size=11)).pack(side="left")

        # Color Management Row
        tr_row_color = ctk.CTkFrame(tab_transform, fg_color="transparent")
        tr_row_color.pack(fill="x", pady=(5, 4))

        ctk.CTkLabel(
            tr_row_color,
            text="Color Profile:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 6))
        self.color_profile_menu = ctk.CTkOptionMenu(
            tr_row_color,
            values=[
                "Preserve (Source)",
                "Convert to sRGB (Web Standard)",
                "Convert to Display P3 (Wide Gamut)",
                "Convert to Adobe RGB",
                "Convert to CMYK (Print)",
                "Custom Profile...",
            ],
            variable=self.color_profile_mode,
            command=self._on_color_profile_mode_changed,
            width=210,
            height=26,
            corner_radius=6,
        )
        self.color_profile_menu.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(
            tr_row_color,
            text="Intent:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.rendering_intent_menu = ctk.CTkOptionMenu(
            tr_row_color,
            values=[
                "Relative Colorimetric",
                "Perceptual",
                "Saturation",
                "Absolute Colorimetric",
            ],
            variable=self.rendering_intent,
            width=145,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.rendering_intent_menu.pack(side="left", padx=(0, 10))

        self.custom_icc_btn = ctk.CTkButton(
            tr_row_color,
            text="Choose ICC...",
            width=88,
            height=26,
            corner_radius=6,
            command=self._browse_custom_icc_profile,
            font=ctk.CTkFont(size=11),
        )
        if "Custom" in self.color_profile_mode.get():
            self.custom_icc_btn.pack(side="left")

        # HDR & High Bit-Depth Row
        tr_row_hdr = ctk.CTkFrame(tab_transform, fg_color="transparent")
        tr_row_hdr.pack(fill="x", pady=(2, 4))
        ctk.CTkLabel(
            tr_row_hdr,
            text="Bit Depth:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 6))
        self.bit_depth_menu = ctk.CTkOptionMenu(
            tr_row_hdr,
            values=[
                "Auto (Match Codec)",
                "8-bit (Standard)",
                "10-bit (HDR / AVIF & HEIC)",
                "12-bit (Cinema / AVIF & HEIC)",
                "16-bit (Deep Color / TIFF & PNG)",
            ],
            variable=self.bit_depth,
            width=190,
            height=26,
            corner_radius=6,
        )
        self.bit_depth_menu.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(
            tr_row_hdr,
            text="Tone Map:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.hdr_tone_menu = ctk.CTkOptionMenu(
            tr_row_hdr,
            values=[
                "None / Direct",
                "ACES Filmic (Cinematic)",
                "Reinhard (Smooth)",
                "Exposure Boost",
                "HLG to SDR (ITU-R BT.2100)",
                "PQ to SDR (SMPTE ST 2084)",
            ],
            variable=self.hdr_tone_mapping,
            width=180,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.hdr_tone_menu.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            tr_row_hdr,
            text="EV:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.hdr_exposure_entry = ctk.CTkEntry(
            tr_row_hdr,
            textvariable=self.hdr_exposure,
            width=48,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.hdr_exposure_entry.pack(side="left")

        # Camera RAW Development Row
        tr_row_raw = ctk.CTkFrame(tab_transform, fg_color="transparent")
        tr_row_raw.pack(fill="x", pady=(2, 4))
        ctk.CTkLabel(
            tr_row_raw,
            text="Camera RAW:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            tr_row_raw,
            text="WB:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.raw_wb_menu = ctk.CTkOptionMenu(
            tr_row_raw,
            values=[
                "Camera As Shot",
                "Auto WB",
                "Daylight (5500K)",
                "Cloudy (6500K)",
                "Tungsten (3200K)",
                "Fluorescent (4000K)",
            ],
            variable=self.raw_white_balance,
            width=140,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.raw_wb_menu.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            tr_row_raw,
            text="Demosaic:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.raw_demosaic_menu = ctk.CTkOptionMenu(
            tr_row_raw,
            values=[
                "Auto (High Quality)",
                "AHD (Adaptive Homogeneity)",
                "Bilinear (Balanced)",
                "Half-Size (Fast Draft)",
            ],
            variable=self.raw_demosaic,
            width=165,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.raw_demosaic_menu.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            tr_row_raw,
            text="EV:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.raw_exposure_entry = ctk.CTkEntry(
            tr_row_raw,
            textvariable=self.raw_exposure,
            width=48,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.raw_exposure_entry.pack(side="left")

        # Vector SVG Rasterization Row
        tr_row_svg = ctk.CTkFrame(tab_transform, fg_color="transparent")
        tr_row_svg.pack(fill="x", pady=(2, 4))
        ctk.CTkLabel(
            tr_row_svg,
            text="Vector SVG:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            tr_row_svg,
            text="Scale:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.svg_scale_menu = ctk.CTkOptionMenu(
            tr_row_svg,
            values=[
                "1.0x (Default)",
                "1.5x",
                "2.0x (Retina)",
                "3.0x",
                "4.0x (Ultra HD)",
                "8.0x (Max Detail)",
            ],
            variable=self.svg_scale,
            width=140,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.svg_scale_menu.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            tr_row_svg,
            text="Background:",
            font=ctk.CTkFont(size=11),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 4))
        self.svg_bg_menu = ctk.CTkOptionMenu(
            tr_row_svg,
            values=[
                "Transparent",
                "White (#FFFFFF)",
                "Black (#000000)",
            ],
            variable=self.svg_background,
            width=145,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
        )
        self.svg_bg_menu.pack(side="left")

        stack_header = ctk.CTkFrame(tab_transform, fg_color="transparent")
        stack_header.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(
            stack_header,
            text="Processing stack",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            stack_header,
            text="runs left to right · use ◀ ▶ to reorder · dimmed steps are switched off",
            font=ctk.CTkFont(size=10),
            text_color=APP_MUTED,
        ).pack(side="left")
        ctk.CTkButton(
            stack_header,
            text="Reset order",
            width=84,
            height=22,
            corner_radius=5,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            border_width=1,
            border_color=APP_BORDER,
            text_color=APP_MUTED,
            command=self._reset_operation_order,
        ).pack(side="right")
        self.stack_frame = ctk.CTkFrame(tab_transform, fg_color="transparent")
        self.stack_frame.pack(fill="x", pady=(2, 2))
        self._render_stack()

        # ==========================================
        # TAB 3: RENAMING & SAFETY
        # ==========================================
        nm_row0 = ctk.CTkFrame(tab_naming, fg_color="transparent")
        nm_row0.pack(fill="x", pady=(4, 6))

        ctk.CTkLabel(
            nm_row0,
            text="Filename Pattern:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#334155", "#cbd5e1"),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(nm_row0, text="Prefix:", font=ctk.CTkFont(size=11), text_color=("#64748b", "#94a3b8")).pack(side="left", padx=(0, 4))
        self.prefix_entry = ctk.CTkEntry(nm_row0, width=70, height=26, textvariable=self.filename_prefix, placeholder_text="web_")
        self.prefix_entry.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            nm_row0,
            text="[filename]",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=(APP_ACCENT, APP_ACCENT_TINT),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(nm_row0, text="Suffix:", font=ctk.CTkFont(size=11), text_color=("#64748b", "#94a3b8")).pack(side="left", padx=(0, 4))
        self.suffix_entry = ctk.CTkEntry(nm_row0, width=70, height=26, textvariable=self.filename_suffix, placeholder_text="_opt")
        self.suffix_entry.pack(side="left", padx=(0, 16))

        nm_row1 = ctk.CTkFrame(tab_naming, fg_color="transparent")
        nm_row1.pack(fill="x", pady=(4, 2))

        ctk.CTkCheckBox(
            nm_row1,
            text="SEO Slugify Names (e.g. my-clean-product.webp)",
            variable=self.slugify_names,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 16))

        ctk.CTkCheckBox(
            nm_row1,
            text="Overwrite existing files",
            variable=self.overwrite,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 16))

        ctk.CTkCheckBox(
            nm_row1,
            text="Strip EXIF & Camera GPS Metadata",
            variable=self.strip_metadata,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")

        # ==========================================
        # TAB 4: WATERMARK
        # ==========================================
        wm_row0 = ctk.CTkFrame(tab_watermark, fg_color="transparent")
        wm_row0.pack(fill="x", pady=(6, 4))

        ctk.CTkCheckBox(
            wm_row0,
            text="Enable Watermark",
            variable=self.enable_watermark,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 12))

        self.watermark_type_menu = ctk.CTkOptionMenu(
            wm_row0,
            values=["Text", "Logo PNG"],
            variable=self.watermark_type,
            width=100,
            height=26,
            command=self._on_watermark_type_changed,
        )
        self.watermark_type_menu.pack(side="left", padx=(0, 8))

        self.watermark_entry = ctk.CTkEntry(
            wm_row0,
            width=160,
            height=26,
            textvariable=self.watermark_text,
            placeholder_text="© Copyright Text",
        )
        self.browse_logo_btn = ctk.CTkButton(
            wm_row0,
            text="Browse Logo...",
            width=110,
            height=26,
            command=self._browse_logo,
        )
        if self.watermark_type.get() == "Logo PNG":
            self.browse_logo_btn.pack(side="left", padx=(0, 12))
        else:
            self.watermark_entry.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(
            wm_row0,
            text="Position:",
            font=ctk.CTkFont(size=11),
            text_color=("#64748b", "#94a3b8"),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkOptionMenu(
            wm_row0,
            values=["bottom-right", "bottom-left", "top-right", "top-left", "center"],
            variable=self.watermark_position,
            width=125,
            height=26,
        ).pack(side="left")

        ctk.CTkLabel(
            wm_row0,
            text="When:",
            font=ctk.CTkFont(size=11),
            text_color=("#64748b", "#94a3b8"),
        ).pack(side="left", padx=(10, 4))
        ctk.CTkOptionMenu(
            wm_row0,
            values=["Always", "Only if ≥ 800px", "Only if ≥ 1200px"],
            variable=self.watermark_condition,
            width=125,
            height=26,
        ).pack(side="left")

        # Output Folder Selector Frame
        output = ctk.CTkFrame(content_inner, fg_color=APP_SURFACE, corner_radius=12, border_width=1, border_color=APP_BORDER)
        output.grid(row=2, column=0, padx=32, pady=(0, 10), sticky="ew")
        output.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            output,
            text="Output destination",
            text_color=APP_MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=(14, 10), pady=(10, 4), sticky="w")

        self.output_entry = ctk.CTkEntry(
            output,
            textvariable=self.output_directory,
            height=28,
            placeholder_text="Choose destination folder",
            corner_radius=6,
        )
        self.output_entry.grid(row=0, column=1, pady=(10, 4), sticky="ew")

        self.browse_button = ctk.CTkButton(
            output,
            text="Browse...",
            command=self._choose_output_directory,
            width=84,
            height=28,
            corner_radius=6,
            fg_color=APP_ELEVATED,
            hover_color=APP_ACCENT,
            text_color=APP_TEXT,
        )
        self.browse_button.grid(row=0, column=2, padx=(8, 14), pady=(10, 4))

        self.same_folder_checkbox = ctk.CTkCheckBox(
            output,
            text="Save in original file's parent folder",
            variable=self.save_in_source_folder,
            command=self._save_in_source_folder_toggled,
            checkbox_width=16,
            checkbox_height=16,
            border_width=2,
            corner_radius=4,
            font=ctk.CTkFont(size=11),
        )
        self.same_folder_checkbox.grid(
            row=1, column=1, columnspan=2, sticky="w", pady=(2, 10)
        )

        # Footer Frame
        footer = ctk.CTkFrame(content_inner, fg_color="transparent")
        footer.grid(row=3, column=0, padx=32, pady=(0, 20), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(footer, variable=self.progress_value, height=6)
        self.progress.grid(
            row=0, column=0, columnspan=5, sticky="ew", pady=(0, 6)
        )

        ctk.CTkLabel(
            footer,
            textvariable=self.status_text,
            anchor="w",
            text_color=APP_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(0, 8))

        # Footer Buttons
        self.export_csv_button = ctk.CTkButton(
            footer,
            text="Export report",
            command=self._export_csv_report,
            width=135,
            height=38,
            corner_radius=9,
            fg_color="transparent",
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
            text_color=("#334155", "#f1f5f9"),
            state="disabled",
        )
        self.export_csv_button.grid(row=2, column=0, sticky="w")

        self.open_button = ctk.CTkButton(
            footer,
            text="Open Folder",
            command=self._open_output_folder,
            width=120,
            height=38,
            corner_radius=9,
            fg_color="transparent",
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
            text_color=("#334155", "#f1f5f9"),
            state="disabled",
        )
        self.open_button.grid(row=2, column=2, padx=(0, 8))

        self.run_controls = ctk.CTkFrame(footer, fg_color="transparent")
        self.pause_button = ctk.CTkButton(
            self.run_controls,
            text="Pause",
            command=self._toggle_pause,
            width=80,
            height=34,
            corner_radius=7,
            fg_color="transparent",
            border_width=1,
            border_color=("#cbd5e1", "#334155"),
            text_color=("#334155", "#f1f5f9"),
            state="disabled",
        )
        self.pause_button.pack(side="left", padx=(0, 6))
        self.cancel_button = ctk.CTkButton(
            self.run_controls,
            text="Cancel",
            command=self._cancel_conversion,
            width=86,
            height=34,
            corner_radius=7,
            state="disabled",
        )
        self.cancel_button.pack(side="left")

        self.retry_button = ctk.CTkButton(
            footer,
            text="Retry failed",
            command=self._retry_failed,
            width=110,
            height=38,
            corner_radius=9,
            fg_color="transparent",
            border_width=1,
            border_color=("#f0b4a8", "#7f1d1d"),
            text_color=("#b91c1c", "#fca5a5"),
        )

        self.convert_button = ctk.CTkButton(
            footer,
            text="Convert to WebP",
            command=self._start_conversion,
            width=220,
            height=44,
            corner_radius=10,
            fg_color=APP_ACCENT,
            hover_color=APP_ACCENT_DARK,
            font=ctk.CTkFont(family=DISPLAY_FONT, weight="bold", size=14),
        )
        self.convert_button.grid(row=2, column=4)

        self._update_image_summary()
        self._lossless_changed()

    def _open_license_manager(self) -> None:
        existing = getattr(self, "_license_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus()
            return
        self._license_dialog = LicenseDialog(self, on_status_changed=self._refresh_license_status)
        self._license_dialog.focus()

    def _refresh_license_status(self) -> None:
        is_vip = is_vip_activated()
        is_pro = is_pro_activated()
        if is_vip:
            badge_text = "VIP MASTER"
            badge_color = APP_CTA
            badge_text_color = "#171308"
            self.vip_downloader_button.configure(
                text="⚡ Download URL",
                fg_color=APP_CTA,
                hover_color=APP_CTA_STRONG,
                text_color="#171308",
                font=ctk.CTkFont(weight="bold"),
            )
        elif is_pro:
            badge_text = "PRO LIFETIME"
            badge_color = "#16a34a"
            badge_text_color = "#ffffff"
            self.vip_downloader_button.configure(
                text="🔒 Download URL",
                fg_color=("gray88", "gray25"),
                hover_color=("gray80", "gray32"),
                text_color=("#344054", "#f2f4f7"),
                font=ctk.CTkFont(weight="normal"),
            )
        else:
            badge_text = "FREE TRIAL"
            badge_color = "#eab308"
            badge_text_color = "#171308"
            self.vip_downloader_button.configure(
                text="🔒 Download URL",
                fg_color=("gray88", "gray25"),
                hover_color=("gray80", "gray32"),
                text_color=("#344054", "#f2f4f7"),
                font=ctk.CTkFont(weight="normal"),
            )
        self.license_badge.configure(
            text=badge_text, fg_color=badge_color, hover_color=badge_color, text_color=badge_text_color
        )
        if hasattr(self, "license_btn_header"):
            btn_txt = "VIP Key" if is_vip else ("License" if is_pro else "Upgrade to Pro")
            self.license_btn_header.configure(text=btn_txt)

    def _open_url_downloader(self) -> None:
        if not is_vip_activated():
            res = messagebox.askyesno(
                "VIP Power Feature",
                "Media Stream URL Downloading (YouTube, Vimeo, etc.) is a VIP Power Feature.\n\n"
                "Would you like to open the License Manager to enter your VIP Master Key?"
            )
            if res:
                self._open_license_manager()
            return

        out_dir = None
        if self.output_directory.get().strip():
            p = Path(self.output_directory.get().strip())
            if p.is_dir():
                out_dir = p

        existing = getattr(self, "_url_downloader_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus()
            return

        self._url_downloader_dialog = URLDownloaderDialog(
            parent=self,
            default_output_dir=out_dir,
            on_download_complete=self._on_download_completed_file,
        )
        self._url_downloader_dialog.focus()

    def _on_download_completed_file(self, file_path: Path) -> None:
        self._ingest_image_paths([file_path])

    def _open_watch_folder_dialog(self) -> None:
        existing = getattr(self, "_watch_folder_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus()
            return

        self._watch_folder_dialog = WatchFolderDialog(
            parent=self,
            watcher=self.active_watcher,
            on_watcher_changed=self._on_watcher_changed,
        )
        self._watch_folder_dialog.focus()

    def _on_watcher_changed(self, watcher: object | None) -> None:
        self.active_watcher = watcher
        is_running = bool(watcher and getattr(watcher, "is_running", False))
        if is_running:
            self.watch_folder_button.configure(
                text="🟢 Watching...",
                fg_color="#059669",
                hover_color="#047857",
                text_color="#ffffff",
            )
        else:
            self.watch_folder_button.configure(
                text="📁 Auto-Watch",
                fg_color=("gray88", "gray25"),
                hover_color=("gray80", "gray32"),
                text_color=("#344054", "#f2f4f7"),
            )

    def _on_app_close(self) -> None:
        if HAS_DRAG_DROP:
            try:
                unhook_dropfiles(self)
            except Exception:
                pass
        if self.active_watcher and hasattr(self.active_watcher, "stop"):
            try:
                self.active_watcher.stop()
            except Exception:
                pass
        self._save_queue_now()
        self.destroy()

    # -- queue persistence ------------------------------------------------

    def _schedule_queue_save(self) -> None:
        if not self._queue_persistence_enabled:
            return
        if self._queue_save_job is not None:
            self.after_cancel(self._queue_save_job)
        self._queue_save_job = self.after(500, self._save_queue_now)

    def _save_queue_now(self) -> None:
        self._queue_save_job = None
        if not self._queue_persistence_enabled:
            return
        try:
            if not self.selected_files:
                clear_queue_state(self.queue_state_file)
                return
            state = build_state(
                self.selected_files,
                self.row_results,
                self.output_directory.get(),
                self.file_overrides,
            )
            save_queue_state(state, self.queue_state_file)
        except Exception:
            pass

    def _confirm_queue_restore(self, count: int, dropped: int) -> bool:
        from tkinter import messagebox

        note = f" ({dropped} file{'s' if dropped != 1 else ''} no longer exist and were skipped)" if dropped else ""
        return messagebox.askyesno(
            "Restore previous session?",
            f"Shadow closed with {count} item{'s' if count != 1 else ''} still in the queue{note}.\n\n"
            "Restore them now?",
            parent=self,
        )

    def _offer_queue_restore(self) -> None:
        if self.selected_files:
            return
        state = load_queue_state(self.queue_state_file)
        if state is None:
            clear_queue_state(self.queue_state_file)
            return
        if not self._confirm_queue_restore(len(state.items), state.dropped):
            clear_queue_state(self.queue_state_file)
            return

        if state.output_directory and not self.output_directory.get().strip():
            self.output_directory.set(state.output_directory)
        self._ingest_image_paths([item.path for item in state.items])
        for item in state.items:
            if item.overrides:
                self.file_overrides[item.path] = dict(item.overrides)
            result = synthesize_result(item)
            if result is not None:
                self._display_result(result)
        completed = sum(1 for i in state.items if i.status == "Completed")
        self.status_text.set(
            f"Restored {len(state.items)} item{'s' if len(state.items) != 1 else ''} from your previous session"
            + (f" ({completed} already completed)" if completed else "")
        )
        self._schedule_queue_save()


    def _set_quality_visibility(self, visible: bool) -> None:
        if not hasattr(self, "quality_row") or self.quality_row is None:
            return
        if visible:
            if hasattr(self, "when_label") and self.when_label.winfo_exists():
                self.quality_row.pack(side="left", padx=(10, 0), before=self.when_label)
            else:
                self.quality_row.pack(side="left", padx=(10, 0))
        else:
            self.quality_row.pack_forget()

    def _format_changed(self, new_format: str) -> None:
        fmt = new_format.upper()
        self._update_format_capabilities(new_format)
        if "ANIMATED WEBP" in fmt:
            self.convert_button.configure(text="Convert to Animated WebP")
            self._set_quality_visibility(True)
        elif "WEBP" in fmt:
            self.convert_button.configure(text="Convert to WebP")
            self._set_quality_visibility(True)
        elif "AVIF" in fmt:
            self.convert_button.configure(text="Convert to AVIF")
            self._set_quality_visibility(True)
        elif "DOCUMENT: MD" in fmt:
            self.convert_button.configure(text="Convert to Markdown")
            self._set_quality_visibility(False)
        elif "DOCUMENT: DOCX" in fmt:
            self.convert_button.configure(text="Convert to Word (.docx)")
            self._set_quality_visibility(False)
        elif "DOCUMENT: PDF" in fmt:
            self.convert_button.configure(text="Convert to PDF")
            self._set_quality_visibility(False)
        elif "DOCUMENT: HTML" in fmt:
            self.convert_button.configure(text="Convert to HTML")
            self._set_quality_visibility(False)
        elif "DOCUMENT: TXT" in fmt:
            self.convert_button.configure(text="Convert to Plain Text")
            self._set_quality_visibility(False)
        elif fmt == "PDF (COMBINED)":
            self.convert_button.configure(text="Combine into PDF")
            self._set_quality_visibility(False)
        elif "PDF" in fmt:
            self.convert_button.configure(text="Combine into PDF")
            self._set_quality_visibility(False)
        elif "VIDEO: MP4" in fmt or fmt == "MP4":
            self.convert_button.configure(text="Compress Video (MP4)")
            self._set_quality_visibility(False)
        elif "VIDEO: WEBM" in fmt or fmt == "WEBM":
            self.convert_button.configure(text="Compress Video (WebM)")
            self._set_quality_visibility(False)
        elif "GIF" in fmt:
            self.convert_button.configure(text="Convert to GIF")
            self._set_quality_visibility(False)
        elif "MP3" in fmt:
            self.convert_button.configure(text="Convert to MP3 Audio")
            self._set_quality_visibility(False)
        elif "AAC" in fmt:
            self.convert_button.configure(text="Convert to AAC Audio")
            self._set_quality_visibility(False)
        elif "OPUS" in fmt:
            self.convert_button.configure(text="Convert to Opus Audio")
            self._set_quality_visibility(False)
        elif "WAV" in fmt:
            self.convert_button.configure(text="Convert to WAV Audio")
            self._set_quality_visibility(False)
        elif "PNG" in fmt:
            self.convert_button.configure(text="Convert to PNG")
            self._set_quality_visibility(False)
        elif "JPEG" in fmt or "JPG" in fmt:
            self.convert_button.configure(text="Convert to JPEG")
            self._set_quality_visibility(True)
        elif "ICO" in fmt:
            self.convert_button.configure(text="Convert to ICO")
            self._set_quality_visibility(False)
        elif normalize_output_format(new_format) in IMAGE_OUTPUT_FORMATS:
            image_fmt = normalize_output_format(new_format)
            self.convert_button.configure(text=f"Convert to {image_fmt}")
            if image_fmt in LOSSY_IMAGE_FORMATS:
                self._set_quality_visibility(True)
            else:
                self._set_quality_visibility(False)
        elif "VIDEO" in fmt:
            self.convert_button.configure(text="Process Video")
            self._set_quality_visibility(False)
        elif "AUDIO" in fmt:
            self.convert_button.configure(text="Convert Audio")
            self._set_quality_visibility(False)
        else:
            self.convert_button.configure(text=f"Convert to {fmt}")
            self._set_quality_visibility(True)

    def _open_format_browser(self) -> None:
        options = list(self.format_menu.cget("values"))
        FormatBrowserDialog(self, options, self.target_format.get(), self._select_format_from_browser)

    def _select_format_from_browser(self, label: str) -> None:
        self.target_format.set(label)
        self._format_changed(label)

    def _update_format_capabilities(self, raw_format: str) -> None:
        frame = getattr(self, "format_capability_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()

        entry = describe_format(raw_format)
        if not entry.badges and not entry.description:
            ctk.CTkLabel(
                frame,
                text="Media pipeline options adapt automatically to the selected input.",
                font=ctk.CTkFont(size=10),
                text_color=APP_MUTED,
            ).pack(side="left")
            return

        ctk.CTkLabel(
            frame,
            text=f"{entry.category}  ·  {entry.description}",
            font=ctk.CTkFont(size=10),
            text_color=APP_MUTED,
        ).pack(side="left", padx=(0, 10))
        render_capability_badges(frame, entry.badges)

    def _adapt_settings_to_selection(self) -> None:
        """Dynamically adapt UI format menus, presets, and conversion controls based on current selection or queue contents."""
        target_path: Path | None = None
        sel = self.table.selection()
        if sel:
            item_id = sel[0]
            target_path = next((p for p, r in self.row_ids.items() if r == item_id), None)
        elif self.selected_files:
            target_path = self.selected_files[0]

        if target_path is None:
            category = "ready"
        else:
            ext = target_path.suffix.lower()
            if ext == ".gif":
                category = "gif"
            elif ext in SUPPORTED_VIDEO_EXTENSIONS:
                category = "video"
            elif ext in SUPPORTED_AUDIO_EXTENSIONS:
                category = "audio"
            elif ext in SUPPORTED_DOCUMENT_EXTENSIONS:
                category = "document"
            elif ext in SUPPORTED_EXTENSIONS:
                category = "image"
            else:
                category = "image"

        # Update info text
        if target_path and target_path.exists():
            size_str = format_file_size(target_path.stat().st_size)
            if sel and len(sel) > 1:
                self.smart_info_label.configure(
                    text=f"{len(sel)} items selected (active: {target_path.name})"
                )
            else:
                self.smart_info_label.configure(
                    text=f"Selected: {target_path.name} ({size_str})"
                )
        elif target_path:
            self.smart_info_label.configure(text=f"Selected: {target_path.name}")
        else:
            self.smart_info_label.configure(text="Select or drop media to auto-tune options")

        if category == self._current_smart_category:
            return

        self._current_smart_category = category

        if category == "video":
            self.smart_badge.configure(
                text="🎬 Smart Video Mode (Hardware GPU Accelerated)",
                fg_color=("#dbeafe", "#1e3a5f"),
                text_color=("#1d4ed8", "#93c5fd"),
            )
            self.smart_trim_btn.pack(side="right", padx=(0, 4))
            video_formats = [
                "Video: MP4",
                "Video: WebM",
                "Video -> Animated WebP",
                "Video -> GIF",
                "Extract Audio: MP3",
                "Extract Audio: AAC",
                "Extract Audio: Opus",
                "Extract Audio: WAV",
            ]
            self.format_menu.configure(values=video_formats)
            if self.target_format.get() not in video_formats:
                self.target_format.set("Video: MP4")

            video_presets = [
                "Manual / Custom",
                "💬 Discord 24MB Video",
                "📱 Mobile 720p Optimized",
                "⚡ Fast Web Streaming (WebM)",
                "🎞️ Short Clip -> Animated WebP",
                "🎵 Extract Studio Audio (320k MP3)",
            ]
            self.preset_menu.configure(values=video_presets)
            self.preset_profile.set("Manual / Custom")
            self.target_size_unit.set("MB")

        elif category == "audio":
            self.smart_badge.configure(
                text="🎵 Smart Audio Mode",
                fg_color=("#ecfdf5", "#064e3b"),
                text_color=("#047857", "#6ee7b7"),
            )
            self.smart_trim_btn.pack_forget()
            audio_formats = [
                "Audio: MP3",
                "Audio: AAC",
                "Audio: Opus",
                "Audio: WAV",
            ]
            self.format_menu.configure(values=audio_formats)
            if self.target_format.get() not in audio_formats:
                self.target_format.set("Audio: MP3")

            audio_presets = [
                "Manual / Custom",
                "🎙️ Studio Master (320 kbps)",
                "📻 High Fidelity (192 kbps)",
                "📱 Standard Audio (128 kbps)",
                "💬 Voice Note (64 kbps Opus)",
            ]
            self.preset_menu.configure(values=audio_presets)
            self.preset_profile.set("Manual / Custom")
            self.target_size_unit.set("MB")

        elif category == "gif":
            self.smart_badge.configure(
                text="🎞️ Smart Animated GIF Mode (80-90% Reduction)",
                fg_color=("#fef3c7", "#78350f"),
                text_color=("#b45309", "#fde68a"),
            )
            self.smart_trim_btn.pack_forget()
            gif_formats = [
                "Video -> Animated WebP",
                "WEBP",
                "Video -> GIF",
                "PNG",
                "JPEG",
            ]
            self.format_menu.configure(values=gif_formats)
            if self.target_format.get() not in gif_formats:
                self.target_format.set("Video -> Animated WebP")

            gif_presets = [
                "Manual / Custom",
                "⚡ Lightweight Animated WebP",
                "🌐 High Quality Animated WebP (90%)",
                "💬 Discord Sticker (<8MB)",
            ]
            self.preset_menu.configure(values=gif_presets)
            self.preset_profile.set("Manual / Custom")
            self.target_size_unit.set("KB")

        elif category == "document":
            self.smart_badge.configure(
                text="📝 Smart Document Mode (Markdown Converter)",
                fg_color=("#e0f2fe", "#0c4a6e"),
                text_color=("#0369a1", "#7dd3fc"),
            )
            self.smart_trim_btn.pack_forget()
            document_formats = [
                "Document: MD",
                "Document: DOCX",
                "Document: PDF",
                "Document: HTML",
                "Document: TXT",
            ]
            self.format_menu.configure(values=document_formats)
            if self.target_format.get() not in document_formats:
                self.target_format.set("Document: MD")

            document_presets = [
                "Manual / Custom",
                "📝 Extract to Markdown",
                "📄 Markdown -> Word (.docx)",
                "🌐 Markdown -> HTML",
            ]
            self.preset_menu.configure(values=document_presets)
            self.preset_profile.set("Manual / Custom")

        elif category == "image":
            self.smart_badge.configure(
                text="🖼️ Smart Image Mode",
                fg_color=(APP_ACCENT_SOFT, "#123A36"),
                text_color=(APP_ACCENT, APP_ACCENT_TINT),
            )
            self.smart_trim_btn.pack_forget()
            image_formats = IMAGE_FORMAT_OPTIONS
            self.format_menu.configure(values=image_formats)
            if self.target_format.get() not in image_formats:
                self.target_format.set("WEBP")

            image_presets = [
                "Manual / Custom",
                "🌐 Next-Gen AVIF (75%)",
                "⚡ Web Banner (1920px 80%)",
                "🛍️ E-Commerce (1000px 85%)",
                "📱 Avatar 1:1 (PNG)",
                "📧 Email Doc (≤5MB)",
                "📄 PDF Binder",
            ]
            self.preset_menu.configure(values=image_presets)
            self.preset_profile.set("Manual / Custom")
            self.target_size_unit.set("KB")

        else:  # ready / empty queue
            self.smart_badge.configure(
                text="✨ Smart Settings: Auto-Detect Ready",
                fg_color=("#e2e8f0", "#1e293b"),
                text_color=("#334155", "#94a3b8"),
            )
            self.smart_trim_btn.pack_forget()
            all_formats = [
                *IMAGE_FORMAT_OPTIONS,
                "Video: WebM",
                "Video: MP4",
                "Video -> Animated WebP",
                "Video -> GIF",
                "Audio: MP3",
                "Audio: AAC",
                "Audio: Opus",
                "Document: MD",
                "Document: DOCX",
                "Document: PDF",
                "Document: HTML",
                "Document: TXT",
            ]
            self.format_menu.configure(values=all_formats)
            self.target_format.set("WEBP")
            self.preset_menu.configure(
                values=[
                    "Manual / Custom",
                    "🌐 Next-Gen AVIF (75%)",
                    "⚡ Web Banner (1920px 80%)",
                    "🛍️ E-Commerce (1000px 85%)",
                    "📱 Avatar 1:1 (PNG)",
                    "💬 Discord 24MB Video",
                    "📧 Email Doc (≤5MB)",
                    "📄 PDF Binder",
                ]
            )
            self.preset_profile.set("Manual / Custom")
            self.target_size_unit.set("KB")

        self._format_changed(self.target_format.get())

    def _on_watermark_type_changed(self, new_type: str) -> None:
        update_setting("watermark_type", new_type)
        if new_type == "Logo PNG":
            self.watermark_entry.pack_forget()
            self.browse_logo_btn.pack(side="left", padx=(2, 10))
        else:
            self.browse_logo_btn.pack_forget()
            self.watermark_entry.pack(side="left", padx=(2, 10))

    def _browse_logo(self) -> None:
        file_selected = filedialog.askopenfilename(
            title="Select Logo Image",
            filetypes=[("PNG / WebP Images", "*.png *.webp *.jpg *.jpeg"), ("All Files", "*.*")],
        )
        if file_selected:
            self.watermark_logo_path.set(file_selected)
            update_setting("watermark_logo_path", file_selected)
            self.status_text.set(f"Logo selected: {Path(file_selected).name}")

    def _apply_table_theme(self) -> None:
        dark_mode = ctk.get_appearance_mode().lower() == "dark"
        table_bg = "#11161d" if dark_mode else "#ffffff"
        head_bg = "#1a2029" if dark_mode else "#f2f4f7"
        fg = "#f4f7fa" if dark_mode else "#14212b"
        sel_bg = "#123B36" if dark_mode else "#CFF4EE"
        sel_fg = "#ffffff" if dark_mode else "#0B3B35"

        self.table_style.configure(
            "Treeview",
            rowheight=34,
            font=(BODY_FONT, 10),
            borderwidth=0,
            background=table_bg,
            fieldbackground=table_bg,
            foreground=fg,
        )
        self.table_style.configure(
            "Treeview.Heading",
            font=(BODY_FONT, 10, "bold"),
            relief="flat",
            background=head_bg,
            foreground=fg,
        )
        self.table_style.map(
            "Treeview.Heading",
            background=[("active", head_bg)],
        )
        self.table_style.map(
            "Treeview",
            background=[("selected", sel_bg)],
            foreground=[("selected", sel_fg)],
        )

    def _change_appearance_mode(self, new_mode: str) -> None:
        # Defer execution slightly so the OptionMenu popup menu dismisses and ungrabs cleanly
        self.after(20, lambda: self._apply_appearance_mode_change(new_mode))

    def _apply_appearance_mode_change(self, new_mode: str) -> None:
        ctk.set_appearance_mode(new_mode)
        update_setting("theme", new_mode)
        self._apply_table_theme()

    def _apply_density(self, density: str) -> None:
        ctk.set_widget_scaling(DENSITY_SCALES.get(density, 1.0))

    def _change_density(self, density: str) -> None:
        if density not in DENSITY_SCALES:
            density = "Comfortable"
        self._apply_density(density)
        update_setting("density", density)
        if hasattr(self, "density_menu"):
            self.density_menu.set(density)
        self.after(50, self._force_redraw_after_resize)

    # -- command palette ----------------------------------------------------

    def _palette_actions(self) -> list[PaletteAction]:
        has_sel = lambda: bool(self.table.selection())
        has_files = lambda: bool(self.selected_files)
        idle = lambda: not self.conversion_running
        sel_is_video = lambda: any(
            p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
            for p, r in self.row_ids.items()
            if r in self.table.selection()
        )
        return [
            PaletteAction("Add files…", self._add_files, "Queue", "Ctrl+O", "open images import", idle),
            PaletteAction("Add folder…", self._add_folder, "Queue", "", "import directory", idle),
            PaletteAction("Select all", self._select_all_rows, "Queue", "Ctrl+A", "", has_files),
            PaletteAction("Remove selected", self._remove_selected, "Queue", "Del", "delete", lambda: has_sel() and idle()),
            PaletteAction("Clear all", self._clear_all, "Queue", "", "empty queue", lambda: has_files() and idle()),
            PaletteAction("Remove duplicate files", self._remove_duplicates, "Queue", "", "same content dedupe", lambda: idle() and bool(self._duplicate_paths())),
            PaletteAction("Move selected up", self._move_selected_up, "Queue", "Alt+↑", "reorder", has_sel),
            PaletteAction("Move selected down", self._move_selected_down, "Queue", "Alt+↓", "reorder", has_sel),
            PaletteAction("Convert", self._start_conversion, "Conversion", "Ctrl+Enter", "start run compress", lambda: has_files() and idle()),
            PaletteAction("Cancel conversion", self._cancel_conversion, "Conversion", "", "stop abort", lambda: self.conversion_running),
            PaletteAction("Pause / resume queue", self._toggle_pause, "Conversion", "", "hold wait continue", lambda: self.conversion_running),
            PaletteAction("Retry failed items", self._retry_failed, "Conversion", "", "rerun errors again", lambda: idle() and bool(self._failed_paths())),
            PaletteAction("Browse formats…", self._open_format_browser, "Conversion", "", "target output codec", idle),
            PaletteAction("Recipes…", self._open_recipe_manager, "Conversion", "", "presets save load settings", idle),
            PaletteAction("Preview & compare selected", self._open_selected_preview, "Inspect", "", "diff before after", has_sel),
            PaletteAction("Optimize selected…", self._open_selected_optimizer, "Inspect", "", "codec compare ssim pareto recommend", has_sel),
            PaletteAction("Trim selected video…", self._open_selected_trimmer, "Inspect", "", "cut clip", sel_is_video),
            PaletteAction("Choose output folder…", self._choose_output_directory, "Output", "", "destination directory", idle),
            PaletteAction("Open output folder", self._open_output_folder, "Output", "", "reveal explorer finder"),
            PaletteAction("Export CSV report…", self._export_csv_report, "Output", "", "audit results spreadsheet", lambda: bool(self.row_results)),
            PaletteAction("Watch folder…", self._open_watch_folder_dialog, "Automation", "", "auto monitor pipeline"),
            PaletteAction("Media downloader…", self._open_url_downloader, "Automation", "", "url stream vip"),
            PaletteAction("Theme: System", lambda: self._set_theme("System"), "Appearance", "", "appearance"),
            PaletteAction("Theme: Dark", lambda: self._set_theme("Dark"), "Appearance", "", "appearance"),
            PaletteAction("Theme: Light", lambda: self._set_theme("Light"), "Appearance", "", "appearance"),
            PaletteAction("Density: Compact", lambda: self._change_density("Compact"), "Appearance", "", "scaling small tight"),
            PaletteAction("Density: Comfortable", lambda: self._change_density("Comfortable"), "Appearance", "", "scaling default"),
            PaletteAction("History…", self._open_history, "Help", "", "log past conversions reproduce"),
            PaletteAction("Export diagnostics…", self._export_diagnostics_bundle, "Help", "", "support bundle logs system info"),
            PaletteAction("License…", self._open_license_manager, "Help", "", "activate pro vip key"),
        ]

    def _set_theme(self, mode: str) -> None:
        self.theme_menu.set(mode)
        self._change_appearance_mode(mode)

    def _open_history(self) -> HistoryDialog:
        return HistoryDialog(self, self._apply_recipe_settings)

    def _export_diagnostics_bundle(self) -> None:
        folder = filedialog.askdirectory(title="Save diagnostics bundle to…")
        if not folder:
            return
        try:
            out = export_diagnostics(Path(folder))
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self.status_text.set(f"Diagnostics saved: {out.name}")
        reveal_in_file_manager(out)

    def _open_command_palette(self) -> CommandPalette:
        return CommandPalette(self, self._palette_actions())

    def _apply_preset(self, quality: int, is_lossless: bool) -> None:
        if self.conversion_running:
            return
        self.lossless.set(is_lossless)
        self._lossless_changed()
        if not is_lossless:
            self.quality.set(quality)
            self.quality_text.set(str(quality))

    def _setup_drag_and_drop(self) -> None:
        if not HAS_DRAG_DROP:
            return
        try:
            hook_dropfiles(self, on_drop_files=self._on_drop_files)
        except Exception:
            pass

    def _on_drop_files(self, dropped_files: list[str | bytes]) -> None:
        if self.conversion_running:
            return
        new_paths: list[Path] = []
        for raw in dropped_files:
            try:
                if isinstance(raw, bytes):
                    try:
                        str_path = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        str_path = raw.decode("mbcs", errors="ignore")
                else:
                    str_path = str(raw)
                p = Path(str_path).resolve()
                if p.is_dir():
                    new_paths.extend(
                        scan_directory_for_images(
                            p, ALL_MEDIA_EXTENSIONS, recursive=True
                        )
                    )
                elif p.is_file() and p.suffix.lower() in ALL_MEDIA_EXTENSIONS:
                    new_paths.append(p)
            except Exception:
                continue
        if new_paths:
            self._ingest_image_paths(new_paths)
        else:
            self.status_text.set("No supported image or media files found in dropped items")

    def _setup_context_menu(self) -> None:
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(
            label="Preview & Compare", command=self._open_selected_preview
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Open Converted Output", command=self._ctx_open_converted
        )
        self.context_menu.add_command(
            label="Reveal in File Explorer", command=self._ctx_reveal_file
        )
        self.context_menu.add_command(
            label="Open Original File", command=self._ctx_open_original
        )
        self.context_menu.add_command(
            label="Cut / Trim Video Clip", command=self._open_selected_trimmer
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Copy File to Clipboard", command=self._ctx_copy_image
        )
        self.context_menu.add_command(
            label="Copy File Path", command=self._ctx_copy_path
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Remove from List", command=self._remove_selected
        )
        self.context_menu.add_command(
            label="Use Current Format & Quality for Selected",
            command=self._apply_file_override,
        )
        self.context_menu.add_command(
            label="Copy Selected File Settings",
            command=self._copy_file_override,
        )
        self.context_menu.add_command(
            label="Paste File Settings to Selected",
            command=self._paste_file_override,
        )
        self.context_menu.add_command(
            label="Undo File Settings",
            command=self._undo_file_overrides,
        )
        self.context_menu.add_command(
            label="Redo File Settings",
            command=self._redo_file_overrides,
        )
        self.context_menu.add_command(
            label="Clear Selected File Overrides",
            command=self._clear_file_overrides,
        )

        def show_menu(event: tk.Event) -> None:
            item_id = self.table.identify_row(event.y)
            if item_id:
                if item_id not in self.table.selection():
                    self.table.selection_set(item_id)
                self._update_button_states()
                path = next(
                    (p for p, r in self.row_ids.items() if r == item_id), None
                )
                res = self.row_results.get(path) if path else None
                can_open_converted = bool(
                    res
                    and res.status == "Completed"
                    and res.output_path
                    and res.output_path.exists()
                )
                is_video = bool(path and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS)
                self.context_menu.entryconfigure(
                    2, state="normal" if can_open_converted else "disabled"
                )
                self.context_menu.entryconfigure(
                    5, state="normal" if is_video else "disabled"
                )
                self.context_menu.entryconfigure(
                    7, state="normal" if can_open_converted else "disabled"
                )
                self.context_menu.tk_popup(event.x_root, event.y_root)

        self.table.bind("<Button-3>", show_menu)
        self.table.bind("<Button-2>", show_menu)

    def _on_double_click_row(self, event: tk.Event) -> None:
        item_id = self.table.identify_row(event.y)
        if item_id:
            path = next((p for p, r in self.row_ids.items() if r == item_id), None)
            if path:
                self._show_preview_dialog(path)

    def _open_selected_preview(self) -> None:
        sel = self.table.selection()
        if not sel:
            return
        item_id = sel[0]
        path = next((p for p, r in self.row_ids.items() if r == item_id), None)
        if path:
            self._show_preview_dialog(path)

    def _open_selected_optimizer(self) -> None:
        sel = self.table.selection()
        if not sel:
            return
        path = next((p for p, r in self.row_ids.items() if r == sel[0]), None)
        if path is None:
            return
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            messagebox.showinfo("Optimizer", "The optimizer compares image codecs. Select an image file to analyze.")
            return
        OptimizerDialog(self, path, self._apply_optimizer_choice)

    def _apply_optimizer_choice(self, codec: str, quality: int) -> None:
        options = list(self.format_menu.cget("values"))
        if codec not in options:
            self.format_menu.configure(values=[*options, codec])
        self.target_format.set(codec)
        self.quality.set(int(quality))
        self.quality_text.set(str(int(quality)))
        self.lossless.set(False)
        self.preset_profile.set("Manual / Custom")
        self._format_changed(codec)
        self._lossless_changed()
        self.status_text.set(f"Optimizer applied {codec} at quality {int(quality)}")

    def _open_selected_trimmer(self) -> None:
        sel = self.table.selection()
        if not sel:
            return
        item_id = sel[0]
        path = next((p for p, r in self.row_ids.items() if r == item_id), None)
        if path and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            dialog = VideoTrimmerDialog(
                self, path, on_trim_complete=lambda p: self._ingest_image_paths([p])
            )
            dialog.focus()
        else:
            messagebox.showinfo("Video Trimmer", "Please select a video file (MP4, MKV, MOV, WebM, etc.) to trim.")

    def _show_preview_dialog(self, path: Path) -> None:
        result = self.row_results.get(path)
        dialog = ImagePreviewDialog(self, path, result, on_apply=self._apply_variant_choice)
        dialog.focus()

    def _apply_variant_choice(self, codec: str, quality: int) -> None:
        self._apply_optimizer_choice(codec, quality)
        self.status_text.set(f"Applied preview variant {codec} at quality {int(quality)}")

    def _ctx_open_converted(self) -> None:
        for item_id in self.table.selection():
            path = next(
                (p for p, r in self.row_ids.items() if r == item_id), None
            )
            if path and path in self.row_results:
                out = self.row_results[path].output_path
                if out and out.exists():
                    open_file_or_folder(out)

    def _ctx_reveal_file(self) -> None:
        for item_id in self.table.selection():
            path = next(
                (p for p, r in self.row_ids.items() if r == item_id), None
            )
            if path:
                out = (
                    self.row_results[path].output_path
                    if path in self.row_results
                    else None
                )
                target = out if (out and out.exists()) else path
                reveal_in_file_manager(target)

    def _ctx_open_original(self) -> None:
        for item_id in self.table.selection():
            path = next(
                (p for p, r in self.row_ids.items() if r == item_id), None
            )
            if path and path.exists():
                open_file_or_folder(path)

    def _ctx_copy_image(self) -> None:
        for item_id in self.table.selection():
            path = next(
                (p for p, r in self.row_ids.items() if r == item_id), None
            )
            if path and path in self.row_results:
                out = self.row_results[path].output_path
                if out and out.exists():
                    if copy_image_file_to_clipboard(out):
                        self.status_text.set(f"Copied {out.name} to clipboard")

    def _ctx_copy_path(self) -> None:
        for item_id in self.table.selection():
            path = next(
                (p for p, r in self.row_ids.items() if r == item_id), None
            )
            if path:
                out = (
                    self.row_results[path].output_path
                    if path in self.row_results
                    else None
                )
                target = out if (out and out.exists()) else path
                copy_text_to_clipboard(str(target.resolve()))
                self.status_text.set(f"Copied path to clipboard: {target.name}")

    def _save_in_source_folder_toggled(self) -> None:
        use_source = self.save_in_source_folder.get()
        update_setting("save_in_source_folder", use_source)
        if use_source:
            self.output_entry.configure(state="disabled")
            self.browse_button.configure(state="disabled")
        else:
            self.output_entry.configure(state="normal")
            self.browse_button.configure(state="normal")

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select media files",
            filetypes=[
                ("All Supported Media", " ".join(f"*{ext}" for ext in ALL_MEDIA_EXTENSIONS)),
                ("Images", " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)),
                ("Camera RAW", " ".join(f"*{ext}" for ext in sorted(RAW_EXTENSIONS))),
                ("SVG Vector Graphics", " ".join(f"*{ext}" for ext in sorted(SVG_EXTENSIONS))),
                ("Videos", " ".join(f"*{ext}" for ext in SUPPORTED_VIDEO_EXTENSIONS)),
                ("Audios", " ".join(f"*{ext}" for ext in SUPPORTED_AUDIO_EXTENSIONS)),
                ("All files", "*.*"),
            ],
        )
        self._ingest_image_paths([Path(p) for p in paths])

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose media folder to import")
        if not folder:
            return
        dir_path = Path(folder).resolve()
        found = scan_directory_for_images(
            dir_path, ALL_MEDIA_EXTENSIONS, recursive=True
        )
        if not found:
            messagebox.showinfo(
                "No supported media",
                f"No supported images or media files were found in:\n{dir_path}",
            )
            return
        self._ingest_image_paths(found)

    def _ingest_image_paths(self, paths: list[Path]) -> None:
        for raw_path in paths:
            path = raw_path.resolve()
            if (
                path not in self.selected_files
                and path.suffix.lower() in ALL_MEDIA_EXTENSIONS
            ):
                self.selected_files.append(path)
                self.row_ids[path] = self.table.insert(
                    "",
                    "end",
                    values=(
                        path.name,
                        (
                            format_file_size(path.stat().st_size)
                            if path.exists()
                            else "-"
                        ),
                        "-",
                        "-",
                        "Ready",
                    ),
                )

        if not self.output_directory.get().strip() and self.selected_files:
            self.output_directory.set(str(self.selected_files[0].parent))

        self._flag_duplicates()

        if self.selected_files:
            self.empty_state.grid_remove()
            self.table_frame.grid()
        else:
            self.empty_state.grid()
            self.table_frame.grid_remove()

        self._update_image_summary()
        self._update_button_states()
        self._schedule_queue_save()

    def _flag_duplicates(self) -> None:
        """Mark rows whose content matches an earlier queue item."""
        self.duplicate_of = find_duplicates(self.selected_files)
        for path, original in self.duplicate_of.items():
            row_id = self.row_ids.get(path)
            if row_id and path not in self.row_results:
                vals = list(self.table.item(row_id)["values"])
                vals[-1] = f"Duplicate of {original.name}"
                self.table.item(row_id, values=vals)
        if self.duplicate_of:
            n = len(self.duplicate_of)
            self.status_text.set(f"{n} duplicate file{'s' if n != 1 else ''} in the queue (same content, different name)")

    def _duplicate_paths(self) -> list[Path]:
        return [p for p in self.selected_files if p in self.duplicate_of]

    def _remove_duplicates(self) -> None:
        dupes = set(self._duplicate_paths())
        if not dupes:
            self.status_text.set("No duplicate files in the queue")
            return
        self._remember_queue_state()
        for path in list(dupes):
            row_id = self.row_ids.pop(path, None)
            if row_id:
                self.table.delete(row_id)
            self.selected_files.remove(path)
            self.row_results.pop(path, None)
        self.duplicate_of = {}
        if not self.selected_files:
            self.empty_state.grid()
            self.table_frame.grid_remove()
        self._update_image_summary()
        self._update_button_states()
        self._schedule_queue_save()
        self.status_text.set(f"Removed {len(dupes)} duplicate file{'s' if len(dupes) != 1 else ''}")

    def _remove_selected(self) -> None:
        if not self.table.selection():
            return
        self._remember_queue_state()
        for item_id in self.table.selection():
            path = next(
                (p for p, r in self.row_ids.items() if r == item_id), None
            )
            if path is not None:
                self.selected_files.remove(path)
                del self.row_ids[path]
                self.row_results.pop(path, None)
                self.file_overrides.pop(path, None)
            self.table.delete(item_id)
        if not self.selected_files:
            self.empty_state.grid()
            self.table_frame.grid_remove()
        self._update_image_summary()
        self._update_button_states()
        self._schedule_queue_save()

    def _clear_all(self) -> None:
        if self.selected_files:
            self._remember_queue_state()
        self.selected_files.clear()
        self.row_ids.clear()
        self.row_results.clear()
        self.file_overrides.clear()
        self.table.delete(*self.table.get_children())
        self.empty_state.grid()
        self.table_frame.grid_remove()
        self._update_image_summary()
        self._update_button_states()
        self._schedule_queue_save()

    def _selected_paths(self) -> list[Path]:
        return [
            path
            for item_id in self.table.selection()
            for path, row_id in self.row_ids.items()
            if row_id == item_id
        ]

    def _apply_file_override(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        self._remember_override_state()
        override = dict(self._collect_recipe_settings())
        for path in paths:
            self.file_overrides[path] = dict(override)
            row_id = self.row_ids.get(path)
            if row_id and path not in self.row_results:
                values = list(self.table.item(row_id)["values"])
                values[-1] = "Ready - Override"
                self.table.item(row_id, values=values)
        self.status_text.set(f"Applied full recipe override to {len(paths)} file(s)")

    def _clear_file_overrides(self) -> None:
        paths = self._selected_paths()
        if not any(path in self.file_overrides for path in paths):
            return
        self._remember_override_state()
        for path in paths:
            self.file_overrides.pop(path, None)
            row_id = self.row_ids.get(path)
            if row_id and path not in self.row_results:
                values = list(self.table.item(row_id)["values"])
                values[-1] = "Ready"
                self.table.item(row_id, values=values)
        if paths:
            self.status_text.set(f"Cleared file overrides for {len(paths)} file(s)")

    def _copy_file_override(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        self.copied_file_override = dict(
            self.file_overrides.get(
                paths[0],
                self._collect_recipe_settings(),
            )
        )
        self.status_text.set(f"Copied settings from {paths[0].name}")

    def _paste_file_override(self) -> None:
        paths = self._selected_paths()
        if not paths or self.copied_file_override is None:
            self.status_text.set("Copy file settings first")
            return
        self._remember_override_state()
        for path in paths:
            self.file_overrides[path] = dict(self.copied_file_override)
            row_id = self.row_ids.get(path)
            if row_id and path not in self.row_results:
                values = list(self.table.item(row_id)["values"])
                values[-1] = "Ready - Override"
                self.table.item(row_id, values=values)
        self.status_text.set(f"Pasted settings to {len(paths)} file(s)")

    def _remember_override_state(self) -> None:
        self._override_undo.append({path: dict(values) for path, values in self.file_overrides.items()})
        del self._override_undo[:-50]
        self._override_redo.clear()

    def _restore_override_state(self, state: dict[Path, dict[str, object]]) -> None:
        self.file_overrides = {path: dict(values) for path, values in state.items()}
        for path in self.selected_files:
            row_id = self.row_ids.get(path)
            if not row_id or path in self.row_results:
                continue
            values = list(self.table.item(row_id)["values"])
            values[-1] = "Ready - Override" if path in self.file_overrides else "Ready"
            self.table.item(row_id, values=values)

    def _undo_file_overrides(self) -> bool:
        if not self._override_undo:
            return False
        self._override_redo.append({path: dict(values) for path, values in self.file_overrides.items()})
        self._restore_override_state(self._override_undo.pop())
        self.status_text.set("Undid file settings change")
        return True

    def _redo_file_overrides(self) -> bool:
        if not self._override_redo:
            return False
        self._override_undo.append({path: dict(values) for path, values in self.file_overrides.items()})
        self._restore_override_state(self._override_redo.pop())
        self.status_text.set("Redid file settings change")
        return True

    def _remember_queue_state(self) -> None:
        state = (
            list(self.selected_files),
            {path: dict(values) for path, values in self.file_overrides.items()},
        )
        self._queue_undo.append(state)
        del self._queue_undo[:-50]
        self._queue_redo.clear()

    def _restore_queue_state(self, state: tuple[list[Path], dict[Path, dict[str, object]]]) -> None:
        files, overrides = state
        self.selected_files.clear()
        self.row_ids.clear()
        self.row_results.clear()
        self.file_overrides = {path: dict(values) for path, values in overrides.items()}
        self.table.delete(*self.table.get_children())
        self._ingest_image_paths(list(files))
        for path in files:
            row_id = self.row_ids.get(path)
            if row_id and path in self.file_overrides:
                values = list(self.table.item(row_id)["values"])
                values[-1] = "Ready - Override"
                self.table.item(row_id, values=values)

    def _undo_queue_edit(self) -> bool:
        if not self._queue_undo:
            return False
        current = (
            list(self.selected_files),
            {path: dict(values) for path, values in self.file_overrides.items()},
        )
        self._queue_redo.append(current)
        self._restore_queue_state(self._queue_undo.pop())
        return True

    def _redo_queue_edit(self) -> bool:
        if not self._queue_redo:
            return False
        current = (
            list(self.selected_files),
            {path: dict(values) for path, values in self.file_overrides.items()},
        )
        self._queue_undo.append(current)
        self._restore_queue_state(self._queue_redo.pop())
        return True

    def _undo_editor_change(self) -> None:
        if self._undo_queue_edit():
            self.status_text.set("Undid queue edit")
        elif self._undo_file_overrides():
            pass
        elif self._recipe_undo:
            self._recipe_redo.append(self._collect_recipe_settings())
            self._apply_recipe_settings(self._recipe_undo.pop(), record_history=False)
            self.status_text.set("Undid recipe change")
        else:
            self.status_text.set("Nothing to undo")

    def _redo_editor_change(self) -> None:
        if self._redo_queue_edit():
            self.status_text.set("Redid queue edit")
        elif self._redo_file_overrides():
            pass
        elif self._recipe_redo:
            self._recipe_undo.append(self._collect_recipe_settings())
            self._apply_recipe_settings(self._recipe_redo.pop(), record_history=False)
            self.status_text.set("Redid recipe change")
        else:
            self.status_text.set("Nothing to redo")

    def _select_all_rows(self) -> None:
        children = self.table.get_children()
        if children:
            self.table.selection_set(children)
            self._update_button_states()

    def _move_selected_up(self) -> None:
        sel = self.table.selection()
        if not sel:
            return
        self._remember_queue_state()
        for item_id in sel:
            idx = self.table.index(item_id)
            if idx > 0:
                self.table.move(item_id, "", idx - 1)
                path = next((p for p, r in self.row_ids.items() if r == item_id), None)
                if path and path in self.selected_files:
                    p_idx = self.selected_files.index(path)
                    if p_idx > 0:
                        self.selected_files[p_idx], self.selected_files[p_idx - 1] = (
                            self.selected_files[p_idx - 1],
                            self.selected_files[p_idx],
                        )
        self._schedule_queue_save()

    def _move_selected_down(self) -> None:
        sel = self.table.selection()
        if not sel:
            return
        self._remember_queue_state()
        children = self.table.get_children()
        for item_id in reversed(sel):
            idx = self.table.index(item_id)
            if idx < len(children) - 1:
                self.table.move(item_id, "", idx + 1)
                path = next((p for p, r in self.row_ids.items() if r == item_id), None)
                if path and path in self.selected_files:
                    p_idx = self.selected_files.index(path)
                    if p_idx < len(self.selected_files) - 1:
                        self.selected_files[p_idx], self.selected_files[p_idx + 1] = (
                            self.selected_files[p_idx + 1],
                            self.selected_files[p_idx],
                        )
        self._schedule_queue_save()

    def _apply_filter(self, _event: object = None) -> None:
        query = self.search_filter.get().strip().lower()
        for path in self.selected_files:
            row_id = self.row_ids.get(path)
            if not row_id:
                continue
            res = self.row_results.get(path)
            status_text = res.status.lower() if res else "ready"
            if not query or query in path.name.lower() or query in path.suffix.lower() or query in status_text:
                self.table.move(row_id, "", "end")
            else:
                self.table.detach(row_id)

    def _sort_table_by_column(self, col: str) -> None:
        if self.sort_column == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_column = col
            self.sort_desc = False

        def get_sort_val(p: Path):
            res = self.row_results.get(p)
            if col == "filename":
                return p.name.lower()
            elif col == "original":
                return p.stat().st_size if p.exists() else 0
            elif col == "output":
                return (res.output_size or 0) if res else 0
            elif col == "saved":
                if not res or not res.saved or res.saved == "-":
                    return -999.0
                try:
                    return float(res.saved.replace("%", "").replace(" larger", "").strip())
                except Exception:
                    return 0.0
            elif col == "status":
                return res.status if res else "Ready"
            return p.name.lower()

        self.selected_files.sort(key=get_sort_val, reverse=self.sort_desc)
        for path in self.selected_files:
            row_id = self.row_ids.get(path)
            if row_id:
                self.table.move(row_id, "", "end")

        headings = {
            "filename": "Filename",
            "original": "Original Size",
            "output": "Output Size",
            "saved": "Saved",
            "status": "Status",
        }
        indicator = " ▼" if self.sort_desc else " ▲"
        for c, label in headings.items():
            text = f"{label}{indicator}" if c == col else label
            self.table.heading(c, text=text)

    def _apply_preset_profile(self, profile_name: str) -> None:
        if profile_name == "🌐 Next-Gen AVIF (75%)":
            self.target_format.set("AVIF")
            self.quality.set(75)
            self.quality_text.set("75")
            self.enable_resize.set(False)
            self.enable_target_size.set(False)
            self.aspect_ratio.set("Original")
        elif profile_name == "⚡ Web Banner (1920px 80%)":
            self.target_format.set("WEBP")
            self.quality.set(80)
            self.quality_text.set("80")
            self.enable_resize.set(True)
            self.max_dimension_text.set("1920")
            self.enable_target_size.set(False)
            self.aspect_ratio.set("16:9")
        elif profile_name == "🛍️ E-Commerce (1000px 85%)":
            self.target_format.set("WEBP")
            self.quality.set(85)
            self.quality_text.set("85")
            self.enable_resize.set(True)
            self.max_dimension_text.set("1000")
            self.aspect_ratio.set("1:1")
        elif profile_name == "📱 Avatar 1:1 (PNG)":
            self.target_format.set("PNG")
            self.enable_resize.set(True)
            self.max_dimension_text.set("500")
            self.aspect_ratio.set("1:1")
            self.enable_rounded.set(True)
            self.corner_radius.set("50")
        elif profile_name == "💬 Discord 24MB Video":
            self.target_format.set("Video: MP4")
            self.enable_target_size.set(True)
            self.target_size_val.set("24")
            self.target_size_unit.set("MB")
        elif profile_name == "📱 Mobile 720p Optimized":
            self.target_format.set("Video: MP4")
            self.enable_resize.set(True)
            self.max_dimension_text.set("1280")
            self.enable_target_size.set(False)
        elif profile_name == "⚡ Fast Web Streaming (WebM)":
            self.target_format.set("Video: WebM")
            self.enable_resize.set(False)
            self.enable_target_size.set(False)
        elif profile_name == "🎞️ Short Clip -> Animated WebP":
            self.target_format.set("Video -> Animated WebP")
            self.quality.set(80)
            self.quality_text.set("80")
            self.enable_target_size.set(False)
        elif profile_name == "🎵 Extract Studio Audio (320k MP3)":
            self.target_format.set("Extract Audio: MP3")
            self.enable_target_size.set(False)
        elif profile_name == "⚡ Lightweight Animated WebP":
            self.target_format.set("Video -> Animated WebP")
            self.quality.set(70)
            self.quality_text.set("70")
            self.enable_target_size.set(False)
        elif profile_name == "🌐 High Quality Animated WebP (90%)":
            self.target_format.set("Video -> Animated WebP")
            self.quality.set(90)
            self.quality_text.set("90")
            self.enable_target_size.set(False)
        elif profile_name == "💬 Discord Sticker (<8MB)":
            self.target_format.set("Video -> Animated WebP")
            self.enable_target_size.set(True)
            self.target_size_val.set("8")
            self.target_size_unit.set("MB")
        elif profile_name == "🎙️ Studio Master (320 kbps)":
            self.target_format.set("Audio: MP3")
            self.enable_target_size.set(False)
        elif profile_name == "📻 High Fidelity (192 kbps)":
            self.target_format.set("Audio: MP3")
            self.enable_target_size.set(False)
        elif profile_name == "📱 Standard Audio (128 kbps)":
            self.target_format.set("Audio: MP3")
            self.enable_target_size.set(False)
        elif profile_name == "💬 Voice Note (64 kbps Opus)":
            self.target_format.set("Audio: Opus")
            self.enable_target_size.set(False)
        elif profile_name == "📧 Email Doc (≤5MB)":
            self.target_format.set("WEBP")
            self.enable_target_size.set(True)
            self.target_size_val.set("5")
            self.target_size_unit.set("MB")
        elif profile_name == "📄 PDF Binder":
            self.target_format.set("PDF (Combined)")
            self.enable_target_size.set(False)

        self._format_changed(self.target_format.get())
        self._lossless_changed()

    # -- processing stack --------------------------------------------------

    def _operation_active(self, name: str) -> bool:
        """Whether the step currently does anything, given the UI settings."""
        if name == "color":
            return not self.color_profile_mode.get().startswith("Preserve")
        if name == "tone_map":
            tm = str(self.hdr_tone_mapping.get()).strip().lower()
            try:
                ev = float(self.hdr_exposure.get())
            except (ValueError, TypeError):
                ev = 0.0
            return not (tm.startswith("none") or tm.startswith("direct")) or ev != 0.0
        if name == "rotate":
            return not self.rotate_angle.get().startswith("0")
        if name == "flip":
            return bool(self.flip_h.get() or self.flip_v.get())
        if name == "crop":
            return self.aspect_ratio.get() != "Original"
        if name == "grayscale":
            return bool(self.grayscale.get())
        if name == "rounded":
            return bool(self.enable_rounded.get())
        if name == "resize":
            return bool(self.enable_resize.get())
        if name == "watermark":
            return bool(self.enable_watermark.get())
        return False

    def _on_color_profile_mode_changed(self, value: str) -> None:
        if hasattr(self, "custom_icc_btn"):
            if "Custom" in value:
                self.custom_icc_btn.pack(side="left")
            else:
                self.custom_icc_btn.pack_forget()
        self._schedule_size_estimate()
        self._render_stack()

    def _browse_custom_icc_profile(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose ICC / ICM Color Profile",
            filetypes=[("Color Profiles (*.icc, *.icm)", "*.icc *.icm"), ("All Files (*.*)", "*.*")],
        )
        if path:
            self.color_profile_custom.set(path)
            self._schedule_size_estimate()
            self._render_stack()

    def _current_operation_order(self) -> tuple[str, ...]:
        return normalize_operation_order(self.operation_order.get())

    def _render_stack(self) -> None:
        frame = getattr(self, "stack_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        order = self._current_operation_order()
        for index, name in enumerate(order):
            active = self._operation_active(name)
            chip = ctk.CTkFrame(
                frame,
                corner_radius=7,
                fg_color=(APP_ACCENT_SOFT, "#123A36") if active else APP_ELEVATED,
            )
            chip.pack(side="left", padx=(0, 5))
            ctk.CTkButton(
                chip, text="◀", width=18, height=22, corner_radius=5,
                fg_color="transparent", hover_color=APP_BORDER, text_color=APP_MUTED,
                font=ctk.CTkFont(size=9),
                state="normal" if index > 0 else "disabled",
                command=lambda n=name: self._move_operation(n, -1),
            ).pack(side="left", padx=(2, 0))
            label_text = f"{index + 1}. {OPERATION_LABELS[name]}"
            if active and name == "color":
                c_mode = str(self.color_profile_mode.get()).strip().lower()
                if "srgb" in c_mode:
                    label_text += " (sRGB)"
                elif "p3" in c_mode:
                    label_text += " (Display P3)"
                elif "adobe" in c_mode:
                    label_text += " (Adobe RGB)"
                elif "cmyk" in c_mode:
                    label_text += " (CMYK)"
                elif "custom" in c_mode:
                    label_text += " (Custom)"
            elif active and name == "tone_map":
                tm = str(self.hdr_tone_mapping.get()).strip().lower()
                if "aces" in tm:
                    label_text += " (ACES)"
                elif "reinhard" in tm:
                    label_text += " (Reinhard)"
                elif "hlg" in tm:
                    label_text += " (HLG)"
                elif "pq" in tm:
                    label_text += " (PQ)"
                elif "exposure" in tm:
                    label_text += " (Exposure)"
                try:
                    ev = float(self.hdr_exposure.get())
                    if ev != 0.0:
                        label_text += f" ({ev:+.1f}EV)"
                except Exception:
                    pass
            elif active and name == "resize":
                r_cond = str(self.resize_condition.get()).strip().lower()
                if "4k" in r_cond:
                    label_text += " (>4K)"
                elif "2k" in r_cond:
                    label_text += " (>2K)"
                elif "larger" in r_cond:
                    label_text += " (if larger)"
            elif active and name == "watermark":
                w_cond = str(self.watermark_condition.get()).strip().lower()
                if "800" in w_cond:
                    label_text += " (≥800px)"
                elif "1200" in w_cond:
                    label_text += " (≥1200px)"

            ctk.CTkLabel(
                chip,
                text=label_text,
                font=ctk.CTkFont(size=11, weight="bold" if active else "normal"),
                text_color=(APP_ACCENT_DARK, APP_ACCENT_TINT) if active else APP_MUTED,
            ).pack(side="left", padx=4, pady=3)
            ctk.CTkButton(
                chip, text="▶", width=18, height=22, corner_radius=5,
                fg_color="transparent", hover_color=APP_BORDER, text_color=APP_MUTED,
                font=ctk.CTkFont(size=9),
                state="normal" if index < len(order) - 1 else "disabled",
                command=lambda n=name: self._move_operation(n, 1),
            ).pack(side="left", padx=(0, 2))

    def _move_operation(self, name: str, delta: int) -> None:
        order = list(self._current_operation_order())
        index = order.index(name)
        target = index + delta
        if not 0 <= target < len(order):
            return
        order[index], order[target] = order[target], order[index]
        self.operation_order.set(",".join(order))

    def _reset_operation_order(self) -> None:
        self.operation_order.set(",".join(DEFAULT_OPERATION_ORDER))

    # -- recipes ---------------------------------------------------------

    def _open_recipe_manager(self) -> None:
        RecipeManagerDialog(self, self._collect_recipe_settings, self._apply_recipe_settings)

    def _collect_recipe_settings(self) -> dict[str, Any]:
        return {key: getattr(self, key).get() for key in RECIPE_FIELDS}

    def _apply_recipe_settings(self, settings: dict[str, Any], record_history: bool = True) -> None:
        if record_history:
            self._recipe_undo.append(self._collect_recipe_settings())
            del self._recipe_undo[:-50]
            self._recipe_redo.clear()
        rc_map = {
            "always": "Always",
            "only_above_4k": "Only above 4K",
            "only_above_2k": "Only above 2K",
            "only_if_larger": "Only if larger",
        }
        wc_map = {
            "always": "Always",
            "only_if_>=_800px": "Only if ≥ 800px",
            "only_if_>=_1200px": "Only if ≥ 1200px",
            "only_if_larger": "Only if ≥ 800px",
        }
        cp_map = {
            "preserve": "Preserve (Source)",
            "srgb": "Convert to sRGB (Web Standard)",
            "display_p3": "Convert to Display P3 (Wide Gamut)",
            "adobe_rgb": "Convert to Adobe RGB",
            "cmyk": "Convert to CMYK (Print)",
            "custom": "Custom Profile...",
        }
        ri_map = {
            "relative_colorimetric": "Relative Colorimetric",
            "perceptual": "Perceptual",
            "saturation": "Saturation",
            "absolute_colorimetric": "Absolute Colorimetric",
        }
        bd_map = {
            "auto": "Auto (Match Codec)",
            "8": "8-bit (Standard)",
            "10": "10-bit (HDR / AVIF & HEIC)",
            "12": "12-bit (Cinema / AVIF & HEIC)",
            "16": "16-bit (Deep Color / TIFF & PNG)",
        }
        htm_map = {
            "none": "None / Direct",
            "aces": "ACES Filmic (Cinematic)",
            "reinhard": "Reinhard (Smooth)",
            "exposure": "Exposure Boost",
            "hlg": "HLG to SDR (ITU-R BT.2100)",
            "pq": "PQ to SDR (SMPTE ST 2084)",
        }
        rwb_map = {
            "camera": "Camera As Shot",
            "auto": "Auto WB",
            "daylight": "Daylight (5500K)",
            "cloudy": "Cloudy (6500K)",
            "tungsten": "Tungsten (3200K)",
            "fluorescent": "Fluorescent (4000K)",
        }
        rdm_map = {
            "auto": "Auto (High Quality)",
            "ahd": "AHD (Adaptive Homogeneity)",
            "bilinear": "Bilinear (Balanced)",
            "half": "Half-Size (Fast Draft)",
        }
        svg_scale_map = {
            "1": "1.0x (Default)", "1.0": "1.0x (Default)", "1.0x": "1.0x (Default)",
            "1.5": "1.5x", "1.5x": "1.5x",
            "2": "2.0x (Retina)", "2.0": "2.0x (Retina)", "2.0x": "2.0x (Retina)",
            "3": "3.0x", "3.0x": "3.0x",
            "4": "4.0x (Ultra HD)", "4.0": "4.0x (Ultra HD)", "4.0x": "4.0x (Ultra HD)",
            "8": "8.0x (Max Detail)", "8.0": "8.0x (Max Detail)", "8.0x": "8.0x (Max Detail)",
        }
        svg_bg_map = {
            "transparent": "Transparent", "none": "Transparent",
            "white": "White (#FFFFFF)", "#ffffff": "White (#FFFFFF)",
            "black": "Black (#000000)", "#000000": "Black (#000000)",
        }
        for key in RECIPE_FIELDS:
            if key in settings:
                val = settings[key]
                if key == "resize_condition":
                    val = rc_map.get(str(val).strip().lower(), val)
                elif key == "watermark_condition":
                    val = wc_map.get(str(val).strip().lower(), val)
                elif key == "color_profile_mode":
                    val = cp_map.get(str(val).strip().lower(), val)
                elif key == "rendering_intent":
                    val = ri_map.get(str(val).strip().lower(), val)
                elif key == "bit_depth":
                    val = bd_map.get(str(val).strip().lower(), val)
                elif key == "hdr_tone_mapping":
                    val = htm_map.get(str(val).strip().lower(), val)
                elif key == "raw_white_balance":
                    val = rwb_map.get(str(val).strip().lower(), val)
                elif key == "raw_demosaic":
                    val = rdm_map.get(str(val).strip().lower(), val)
                elif key == "svg_scale":
                    val = svg_scale_map.get(str(val).strip().lower().replace(" ", ""), val)
                elif key == "svg_background":
                    val = svg_bg_map.get(str(val).strip().lower(), val)
                getattr(self, key).set(val)
        if hasattr(self, "custom_icc_btn"):
            if "Custom" in self.color_profile_mode.get():
                self.custom_icc_btn.pack(side="left")
            else:
                self.custom_icc_btn.pack_forget()
        self.quality_text.set(str(self.quality.get()))
        self.preset_profile.set("Manual / Custom")
        self._format_changed(self.target_format.get())
        self._lossless_changed()
        self.status_text.set("Recipe applied")

    def _choose_output_directory(self) -> None:
        directory = filedialog.askdirectory(title="Choose output folder")
        if directory:
            self.output_directory.set(directory)
            update_setting("last_output_directory", directory)

    def _on_quality_key_release(self) -> None:
        val = self.quality_text.get().strip()
        if val.isdigit() and 1 <= int(val) <= 100:
            self.quality.set(int(val))
            self.quality_entry.configure(
                border_color=ctk.ThemeManager.theme["CTkEntry"]["border_color"]
            )
            self._schedule_size_estimate()

    def _slider_changed(self, value: float) -> None:
        self.quality_text.set(str(round(value)))
        self._schedule_size_estimate()

    def _lossless_changed(self) -> None:
        if not self.conversion_running:
            quality_state = "disabled" if self.lossless.get() else "normal"
            if getattr(self, "quality_slider", None) is not None:
                self.quality_slider.configure(state=quality_state)
            self.quality_entry.configure(state=quality_state)
        self._schedule_size_estimate()

    def _update_image_summary(self) -> None:
        count = len(self.selected_files)
        self.image_count_text.set(
            f"{count} item" if count == 1 else f"{count} items"
        )
        total_size = sum(
            path.stat().st_size for path in self.selected_files if path.exists()
        )
        self.total_size_text.set(
            f"• {format_file_size(total_size)}" if total_size else ""
        )
        self._schedule_size_estimate()

    def _setup_estimate_traces(self) -> None:
        variables = (
            self.target_format,
            self.quality_text,
            self.lossless,
            self.preserve_metadata,
            self.strip_metadata,
            self.enable_target_size,
            self.target_size_val,
            self.target_size_unit,
            self.enable_resize,
            self.max_dimension_text,
            self.scale_percent_text,
            self.resize_condition,
            self.rotate_angle,
            self.flip_h,
            self.flip_v,
            self.aspect_ratio,
            self.enable_rounded,
            self.corner_radius,
            self.grayscale,
            self.enable_watermark,
            self.watermark_type,
            self.watermark_text,
            self.watermark_logo_path,
            self.watermark_position,
            self.watermark_condition,
            self.protect_quality,
            self.min_ssim_text,
            self.enable_quality_target,
            self.target_ssim_text,
            self.operation_order,
            self.color_profile_mode,
            self.color_profile_custom,
            self.rendering_intent,
            self.bit_depth,
            self.hdr_tone_mapping,
            self.hdr_exposure,
            self.raw_white_balance,
            self.raw_exposure,
            self.raw_demosaic,
            self.svg_scale,
            self.svg_background,
        )
        for variable in variables:
            variable.trace_add("write", lambda *_args: self._schedule_size_estimate())
        self._schedule_size_estimate()

        # The stack panel mirrors which steps are switched on and their order.
        for variable in (
            self.operation_order, self.rotate_angle, self.flip_h, self.flip_v,
            self.aspect_ratio, self.grayscale, self.enable_rounded,
            self.enable_resize, self.resize_condition,
            self.enable_watermark, self.watermark_condition,
            self.color_profile_mode,
            self.hdr_tone_mapping, self.hdr_exposure,
        ):
            variable.trace_add("write", lambda *_args: self._render_stack())

    def _schedule_size_estimate(self) -> None:
        if not hasattr(self, "estimate_text"):
            return
        if self._estimate_after_id is not None:
            try:
                self.after_cancel(self._estimate_after_id)
            except Exception:
                pass
        self._estimate_generation += 1
        generation = self._estimate_generation
        self._estimate_after_id = self.after(
            450, lambda: self._start_size_estimate(generation)
        )

    def _start_size_estimate(self, generation: int) -> None:
        self._estimate_after_id = None
        if generation != self._estimate_generation or self.conversion_running:
            return

        selected_path: Path | None = None
        selection = self.table.selection() if hasattr(self, "table") else ()
        if selection:
            selected_path = next(
                (path for path, row_id in self.row_ids.items() if row_id == selection[0]),
                None,
            )
        if selected_path is None and self.selected_files:
            selected_path = self.selected_files[0]

        target_format = normalize_output_format(self.target_format.get())
        if (
            selected_path is None
            or selected_path.suffix.lower() not in SUPPORTED_EXTENSIONS
            or target_format not in IMAGE_OUTPUT_FORMATS
        ):
            self.estimate_text.set("Size estimate available for images")
            return

        try:
            quality = int(self.quality_text.get())
            if not 1 <= quality <= 100:
                raise ValueError

            max_dim = None
            scale_pct = None
            if self.enable_resize.get():
                max_text = self.max_dimension_text.get().strip()
                scale_text = self.scale_percent_text.get().strip()
                max_dim = int(max_text) if max_text else None
                scale_pct = float(scale_text) if scale_text else None

            target_kb = None
            if self.enable_target_size.get():
                target_value = float(self.target_size_val.get())
                target_kb = int(
                    target_value
                    if self.target_size_unit.get() == "KB"
                    else target_value * 1024
                )

            corner_radius = (
                int(self.corner_radius.get().strip() or "0")
                if self.enable_rounded.get()
                else 0
            )
            rotate_angle = int(self.rotate_angle.get().split("°", 1)[0].strip())
            min_ssim, target_ssim = self._quality_targets()
        except (TypeError, ValueError):
            self.estimate_text.set("Fix invalid settings to estimate size")
            return

        watermark_text = (
            self.watermark_text.get().strip()
            if self.enable_watermark.get() and self.watermark_type.get() == "Text"
            else ""
        )
        watermark_logo = (
            self.watermark_logo_path.get().strip()
            if self.enable_watermark.get() and self.watermark_type.get() == "Logo PNG"
            else ""
        )
        try:
            ev_val = float(self.hdr_exposure.get())
        except (ValueError, TypeError):
            ev_val = 0.0
        try:
            raw_ev_val = float(self.raw_exposure.get())
        except (ValueError, TypeError):
            raw_ev_val = 0.0
        try:
            svg_scale_val = float(str(self.svg_scale.get()).lower().replace("x", "").split()[0])
        except (ValueError, TypeError, IndexError):
            svg_scale_val = 1.0
        svg_bg_val = self.svg_background.get()
        options = {
            "quality": quality,
            "lossless": self.lossless.get(),
            "preserve_metadata": self.preserve_metadata.get(),
            "strip_metadata": self.strip_metadata.get(),
            "max_width": max_dim,
            "max_height": max_dim,
            "scale_percent": scale_pct,
            "target_format": target_format,
            "target_kb": target_kb,
            "watermark_text": watermark_text,
            "watermark_logo_path": watermark_logo,
            "watermark_position": self.watermark_position.get(),
            "rotate_angle": rotate_angle,
            "flip_h": self.flip_h.get(),
            "flip_v": self.flip_v.get(),
            "aspect_ratio": (
                None if self.aspect_ratio.get() == "Original" else self.aspect_ratio.get()
            ),
            "corner_radius": corner_radius,
            "grayscale": self.grayscale.get(),
            "min_ssim": min_ssim,
            "target_ssim": target_ssim,
            "operation_order": self.operation_order.get(),
            "resize_condition": self.resize_condition.get(),
            "watermark_condition": self.watermark_condition.get(),
            "color_profile_mode": self.color_profile_mode.get(),
            "color_profile_custom": self.color_profile_custom.get(),
            "rendering_intent": self.rendering_intent.get(),
            "bit_depth": self.bit_depth.get(),
            "hdr_tone_mapping": self.hdr_tone_mapping.get(),
            "hdr_exposure": ev_val,
            "raw_white_balance": self.raw_white_balance.get(),
            "raw_exposure": raw_ev_val,
            "raw_demosaic": self.raw_demosaic.get(),
            "svg_scale": svg_scale_val,
            "svg_background": svg_bg_val,
            "psd_composite_mode": self.psd_composite_mode.get(),
            "psd_layer_index": int(self.psd_layer_index.get()) if self.psd_layer_index.get().lstrip("-").isdigit() else -1,
        }
        self.estimate_text.set("Estimating output…")
        threading.Thread(
            target=self._estimate_size_worker,
            args=(generation, selected_path, options),
            daemon=True,
        ).start()

    def _estimate_size_worker(
        self,
        generation: int,
        source_path: Path,
        options: dict[str, object],
    ) -> None:
        try:
            estimated_size = estimate_image_output_size(source_path, **options)
            original_size = source_path.stat().st_size
            change_pct = (
                (estimated_size - original_size) / original_size * 100
                if original_size
                else 0.0
            )
            if change_pct <= 0:
                change_text = f"{abs(change_pct):.1f}% smaller"
            else:
                change_text = f"{change_pct:.1f}% larger"
            text = f"Estimated {format_file_size(estimated_size)} · {change_text}"
        except Exception:
            text = "Estimate unavailable for these settings"
        self.events.put(("estimate", (generation, text)))

    def _sync_quality_from_entry(self) -> bool:
        try:
            value = int(self.quality_text.get())
            if not 1 <= value <= 100:
                raise ValueError
        except ValueError:
            self.quality_entry.configure(border_color="#d92d20")
            self.status_text.set("Quality must be a whole number from 1 to 100")
            return False
        self.quality_entry.configure(
            border_color=ctk.ThemeManager.theme["CTkEntry"]["border_color"]
        )
        self.quality.set(value)
        self.quality_text.set(str(value))
        return True

    @staticmethod
    def _parse_ssim(text: str) -> float:
        value = float(text.strip())
        if not 0.5 <= value <= 1.0:
            raise ValueError("SSIM must be between 0.50 and 1.00")
        return value

    def _quality_targets(self) -> tuple[float | None, float | None]:
        """(min_ssim, target_ssim) from the UI; raises ValueError on bad input."""
        min_ssim = self._parse_ssim(self.min_ssim_text.get()) if self.protect_quality.get() else None
        target_ssim = self._parse_ssim(self.target_ssim_text.get()) if self.enable_quality_target.get() else None
        return min_ssim, target_ssim

    def _confirm_low_disk(self, check: Any) -> bool:
        return messagebox.askyesno(
            "Low disk space",
            f"Only {format_file_size(check.free_bytes)} is free on the destination drive, but this "
            f"batch could need up to {format_file_size(check.needed_bytes)} (a pessimistic estimate).\n\n"
            "Continue anyway?",
        )

    def _start_conversion(self, only: list[Path] | None = None) -> None:
        """Run the queue, or just ``only`` (a subset of it, e.g. failed rows)
        with whatever settings are currently in the UI."""
        if self.conversion_running or not self.selected_files:
            self.status_text.set("Add at least one item to convert")
            return
        batch_source = self.selected_files
        if only is not None:
            wanted = {p.resolve() for p in only}
            batch_source = [p for p in self.selected_files if p in wanted]
            if not batch_source:
                self.status_text.set("Nothing to retry")
                return
        if not self._sync_quality_from_entry():
            return

        # Check Free Evaluation Limit
        is_pro = is_pro_activated()
        if not is_pro and len(batch_source) > FREE_BATCH_LIMIT:
            msg = (
                f"Free Evaluation Mode processes up to {FREE_BATCH_LIMIT} items per batch.\n\n"
                f"You have {len(batch_source)} items selected.\n"
                "Would you like to upgrade to Pro for unlimited batch conversions?"
            )
            if messagebox.askyesno("Upgrade to Pro", msg):
                self._open_license_manager()
                return

        use_source_folder = self.save_in_source_folder.get()
        out_dir_str = self.output_directory.get().strip()
        if not use_source_folder and not out_dir_str:
            self.status_text.set("Choose an output folder first")
            return

        output = Path(out_dir_str) if not use_source_folder else None

        # Resolve sizing & limits. A field left blank simply disables that
        # constraint, but text that fails to parse is a typo the user should
        # be told about -- silently dropping the constraint would run the
        # whole batch without it and nobody would notice why.
        max_dim = None
        scale_pct = None
        if self.enable_resize.get():
            max_dim_str = self.max_dimension_text.get().strip()
            if max_dim_str:
                try:
                    max_dim = int(max_dim_str)
                    if max_dim <= 0:
                        raise ValueError
                except ValueError:
                    self.status_text.set("Max Dimension must be a whole number greater than 0")
                    return
            scale_str = self.scale_percent_text.get().strip()
            if scale_str:
                try:
                    scale_pct = float(scale_str)
                    if not 0 < scale_pct < 100:
                        raise ValueError
                except ValueError:
                    self.status_text.set("Scale % must be a number between 0 and 100")
                    return

        target_kb = None
        target_mb = None
        if self.enable_target_size.get():
            target_size_str = self.target_size_val.get().strip()
            try:
                val = float(target_size_str)
                if val <= 0:
                    raise ValueError
                if self.target_size_unit.get() == "KB":
                    target_kb = int(val)
                else:
                    target_mb = val
                    target_kb = int(val * 1024)
            except ValueError:
                self.status_text.set("Target Size must be a number greater than 0")
                return

        corner_rad = 0
        if self.enable_rounded.get():
            corner_rad_str = self.corner_radius.get().strip()
            try:
                corner_rad = int(corner_rad_str) if corner_rad_str else 0
                if corner_rad < 0:
                    raise ValueError
            except ValueError:
                self.status_text.set("Corner Radius must be a whole number of 0 or more")
                return

        try:
            min_ssim, target_ssim = self._quality_targets()
        except ValueError:
            self.status_text.set("SSIM values must be numbers between 0.50 and 1.00")
            return

        selected_batch = (
            batch_source
            if is_pro
            else batch_source[:FREE_BATCH_LIMIT]
        )

        preflight_dest = output if output is not None else selected_batch[0].parent
        check = disk_preflight(selected_batch, preflight_dest, self.target_format.get())
        if not check.ok and not self._confirm_low_disk(check):
            self.status_text.set(
                f"Stopped: only {format_file_size(check.free_bytes)} free on the destination, "
                f"batch may need up to {format_file_size(check.needed_bytes)}"
            )
            return

        self.conversion_running = True
        self.cancel_event.clear()
        self.pause_event.clear()
        self.log.info("batch start: %d items -> %s", len(selected_batch), self.target_format.get())
        self.pause_button.configure(text="Pause")
        self.retry_button.grid_remove()
        self._set_controls_enabled(False)
        self.progress_value.set(0)

        wm_text = (
            self.watermark_text.get().strip()
            if (self.enable_watermark.get() and self.watermark_type.get() == "Text")
            else ""
        )
        wm_logo = (
            self.watermark_logo_path.get().strip()
            if (self.enable_watermark.get() and self.watermark_type.get() == "Logo PNG")
            else ""
        )

        # Transformations and Batch Renaming
        rot_str = self.rotate_angle.get().split("°", 1)[0].strip()
        try:
            rotate_angle = int(rot_str)
        except ValueError:
            rotate_angle = 0
        flip_h = self.flip_h.get()
        flip_v = self.flip_v.get()
        aspect_ratio = self.aspect_ratio.get() if self.aspect_ratio.get() != "Original" else None
        
        grayscale = self.grayscale.get()
        filename_prefix = self.filename_prefix.get()
        filename_suffix = self.filename_suffix.get()
        normalize_audio = self.normalize_audio.get()

        threading.Thread(
            target=self._convert_batch_pool,
            args=(
                tuple(selected_batch),
                output,
                self.target_format.get(),
                self.quality.get(),
                self.overwrite.get(),
                self.lossless.get(),
                self.preserve_metadata.get(),
                use_source_folder,
                max_dim,
                scale_pct,
                target_kb,
                target_mb,
                wm_text,
                wm_logo,
                self.watermark_position.get(),
                self.strip_metadata.get(),
                self.slugify_names.get(),
                rotate_angle,
                flip_h,
                flip_v,
                aspect_ratio,
                corner_rad,
                grayscale,
                filename_prefix,
                filename_suffix,
                normalize_audio,
                min_ssim,
                target_ssim,
                self.operation_order.get(),
                dict(self.file_overrides),
                self.resize_condition.get(),
                self.watermark_condition.get(),
                self.color_profile_mode.get(),
                self.color_profile_custom.get(),
                self.rendering_intent.get(),
                self.bit_depth.get(),
                self.hdr_tone_mapping.get(),
                self.hdr_exposure.get(),
                self.raw_white_balance.get(),
                self.raw_exposure.get(),
                self.raw_demosaic.get(),
                self.svg_scale.get(),
                self.svg_background.get(),
                self.psd_composite_mode.get(),
                self.psd_layer_index.get(),
            ),
            daemon=True,
        ).start()

    def _convert_batch_pool(
        self,
        files_snapshot: tuple[Path, ...],
        output: Path | None,
        target_format_raw: str,
        quality: int,
        overwrite: bool,
        lossless: bool,
        preserve_metadata: bool,
        use_source_folder: bool,
        max_dim: int | None,
        scale_pct: float | None,
        target_kb: int | None,
        target_mb: float | None,
        watermark_text: str,
        watermark_logo_path: str,
        watermark_position: str,
        strip_metadata: bool,
        slugify_names: bool,
        rotate_angle: int = 0,
        flip_h: bool = False,
        flip_v: bool = False,
        aspect_ratio: str | None = None,
        corner_radius: int = 0,
        grayscale: bool = False,
        filename_prefix: str = "",
        filename_suffix: str = "",
        normalize_audio: bool = False,
        min_ssim: float | None = None,
        target_ssim: float | None = None,
        operation_order: str = "",
        file_overrides: dict[Path, dict[str, object]] | None = None,
        resize_condition: str = "always",
        watermark_condition: str = "always",
        color_profile_mode: str = "preserve",
        color_profile_custom: str = "",
        rendering_intent: str = "relative_colorimetric",
        bit_depth: str = "auto",
        hdr_tone_mapping: str = "none",
        hdr_exposure: str = "0.0",
        raw_white_balance: str = "camera",
        raw_exposure: str = "0.0",
        raw_demosaic: str = "auto",
        svg_scale: str = "1.0x",
        svg_background: str = "Transparent",
        psd_composite_mode: str = "merged",
        psd_layer_index: str = "-1",
    ) -> None:
        total = len(files_snapshot)
        results: list[ConversionResult] = []
        reserved_paths: set[Path] = set()
        reserved_lock = threading.Lock()
        counter_lock = threading.Lock()
        completed_count = 0
        start_time = time.perf_counter()
        workers = recommend_workers(files_snapshot)
        _, gpu_label = get_best_hardware_encoder()
        telemetry = BatchTelemetry(total, workers, gpu_label)

        # Handle special Case: Combine images into PDF. Matched exactly (not
        # a substring check) so it doesn't also catch "Document: PDF", which
        # renders each Markdown file to its own PDF instead of combining them.
        if target_format_raw.upper() == "PDF (COMBINED)" and total > 1:
            try:
                dest_dir = files_snapshot[0].parent if use_source_folder else output
                assert dest_dir is not None
                dest_name = build_destination_filename(
                    "combined_document",
                    ".pdf",
                    slugify=slugify_names,
                    prefix=filename_prefix,
                    suffix=filename_suffix,
                )
                pdf_path = next_available_output_path(
                    dest_dir / dest_name,
                    overwrite=overwrite,
                )
                combine_images_to_pdf(list(files_snapshot), pdf_path)
                res = ConversionResult(
                    files_snapshot[0],
                    pdf_path,
                    sum(p.stat().st_size for p in files_snapshot),
                    pdf_path.stat().st_size,
                    "Saved",
                    "Completed",
                )
                self.events.put(("result", res))
                self.events.put(("complete", ([res], False, time.perf_counter() - start_time)))
                return
            except Exception as e:
                self.events.put(("error", str(e)))
                self.events.put(("complete", ([], False, 0)))
                return

        def process_single(source_p: Path) -> ConversionResult:
            nonlocal completed_count
            override = (file_overrides or {}).get(source_p, {})
            effective_target_format = str(override.get("target_format", target_format_raw))
            effective_quality = int(override.get("quality", quality))
            use_override = bool(override)
            effective_lossless = bool(override.get("lossless", lossless)) if use_override else lossless
            effective_preserve_metadata = bool(override.get("preserve_metadata", preserve_metadata)) if use_override else preserve_metadata
            effective_strip_metadata = bool(override.get("strip_metadata", strip_metadata)) if use_override else strip_metadata
            effective_slugify = bool(override.get("slugify_names", slugify_names)) if use_override else slugify_names
            effective_prefix = str(override.get("filename_prefix", filename_prefix)) if use_override else filename_prefix
            effective_suffix = str(override.get("filename_suffix", filename_suffix)) if use_override else filename_suffix
            effective_normalize_audio = bool(override.get("normalize_audio", normalize_audio)) if use_override else normalize_audio
            effective_max_dim = max_dim
            effective_scale_pct = scale_pct
            effective_resize_condition = (
                str(override.get("resize_condition", resize_condition))
                if use_override and "resize_condition" in override
                else resize_condition
            )
            effective_target_kb = target_kb
            effective_target_mb = target_mb
            effective_watermark_text = watermark_text
            effective_watermark_logo = watermark_logo_path
            effective_watermark_position = watermark_position
            effective_watermark_condition = (
                str(override.get("watermark_condition", watermark_condition))
                if use_override and "watermark_condition" in override
                else watermark_condition
            )
            effective_color_profile_mode = (
                str(override.get("color_profile_mode", color_profile_mode))
                if use_override and "color_profile_mode" in override
                else color_profile_mode
            )
            effective_color_profile_custom = (
                str(override.get("color_profile_custom", color_profile_custom))
                if use_override and "color_profile_custom" in override
                else color_profile_custom
            )
            effective_rendering_intent = (
                str(override.get("rendering_intent", rendering_intent))
                if use_override and "rendering_intent" in override
                else rendering_intent
            )
            effective_bit_depth = (
                str(override.get("bit_depth", bit_depth))
                if use_override and "bit_depth" in override
                else bit_depth
            )
            effective_hdr_tone_mapping = (
                str(override.get("hdr_tone_mapping", hdr_tone_mapping))
                if use_override and "hdr_tone_mapping" in override
                else hdr_tone_mapping
            )
            raw_ev = (
                override.get("hdr_exposure", hdr_exposure)
                if use_override and "hdr_exposure" in override
                else hdr_exposure
            )
            try:
                effective_hdr_exposure = float(raw_ev)
            except (ValueError, TypeError):
                effective_hdr_exposure = 0.0
            effective_raw_wb = (
                str(override.get("raw_white_balance", raw_white_balance))
                if use_override and "raw_white_balance" in override
                else raw_white_balance
            )
            effective_raw_demosaic = (
                str(override.get("raw_demosaic", raw_demosaic))
                if use_override and "raw_demosaic" in override
                else raw_demosaic
            )
            raw_ev_shift = (
                override.get("raw_exposure", raw_exposure)
                if use_override and "raw_exposure" in override
                else raw_exposure
            )
            try:
                effective_raw_exposure = float(raw_ev_shift)
            except (ValueError, TypeError):
                effective_raw_exposure = 0.0
            effective_svg_scale_raw = (
                override.get("svg_scale", svg_scale)
                if use_override and "svg_scale" in override
                else svg_scale
            )
            try:
                effective_svg_scale = float(str(effective_svg_scale_raw).lower().replace("x", "").split()[0])
            except (ValueError, TypeError, IndexError):
                effective_svg_scale = 1.0
            effective_svg_bg = (
                str(override.get("svg_background", svg_background))
                if use_override and "svg_background" in override
                else svg_background
            )
            effective_rotate = rotate_angle
            effective_flip_h = flip_h
            effective_flip_v = flip_v
            effective_aspect = aspect_ratio
            effective_corner = corner_radius
            effective_grayscale = grayscale
            effective_min_ssim = min_ssim
            effective_target_ssim = target_ssim
            effective_order = operation_order
            if use_override:
                if override.get("enable_resize"):
                    raw_dim = str(override.get("max_dimension_text", "")).strip()
                    raw_scale = str(override.get("scale_percent_text", "")).strip()
                    effective_max_dim = int(raw_dim) if raw_dim else None
                    effective_scale_pct = float(raw_scale) if raw_scale else None
                else:
                    effective_max_dim = effective_scale_pct = None
                if override.get("enable_target_size"):
                    raw_size = float(override.get("target_size_val", "0"))
                    effective_target_kb = int(raw_size if override.get("target_size_unit") == "KB" else raw_size * 1024)
                    effective_target_mb = raw_size if override.get("target_size_unit") == "MB" else None
                else:
                    effective_target_kb = effective_target_mb = None
                if override.get("enable_watermark"):
                    if str(override.get("watermark_type", "text")) == "Logo PNG":
                        effective_watermark_text = ""
                        effective_watermark_logo = str(override.get("watermark_logo_path", ""))
                    else:
                        effective_watermark_text = str(override.get("watermark_text", ""))
                        effective_watermark_logo = ""
                    effective_watermark_position = str(override.get("watermark_position", watermark_position))
                else:
                    effective_watermark_text = effective_watermark_logo = ""
                effective_rotate = int(str(override.get("rotate_angle", "0")).replace("°", "").strip() or "0")
                effective_flip_h = bool(override.get("flip_h", False))
                effective_flip_v = bool(override.get("flip_v", False))
                raw_aspect = str(override.get("aspect_ratio", "Original"))
                effective_aspect = None if raw_aspect == "Original" else raw_aspect
                effective_corner = int(str(override.get("corner_radius", "0")).strip() or "0") if override.get("enable_rounded") else 0
                effective_grayscale = bool(override.get("grayscale", False))
                effective_min_ssim = float(override.get("min_ssim_text", "0.95")) if override.get("protect_quality") else None
                effective_target_ssim = float(override.get("target_ssim_text", "0.95")) if override.get("enable_quality_target") else None
                effective_order = str(override.get("operation_order", operation_order))
            # Pause holds workers here, before they pick up new work; items
            # already encoding run to completion. Cancel always wins.
            while self.pause_event.is_set() and not self.cancel_event.is_set():
                time.sleep(0.1)
            if self.cancel_event.is_set():
                res = ConversionResult(
                    source_p, None, None, None, "-", "Cancelled", "Operation cancelled"
                )
                with counter_lock:
                    completed_count += 1
                self.events.put(("result", res))
                return res

            target_dir = source_p.parent if use_source_folder else output
            assert target_dir is not None

            is_video = source_p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
            is_audio = source_p.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
            is_document = source_p.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS
            is_gif_anim = source_p.suffix.lower() == ".gif" and (
                "ANIMATED" in effective_target_format.upper()
                or "GIF" in effective_target_format.upper()
                or "VIDEO" in effective_target_format.upper()
                or "MP4" in effective_target_format.upper()
                or "WEBM" in effective_target_format.upper()
            )

            with reserved_lock:
                if is_document:
                    # Document/Markdown engine conversion
                    doc_fmt_key = "MD"
                    if "DOCX" in effective_target_format.upper():
                        doc_fmt_key = "DOCX"
                    elif "HTML" in effective_target_format.upper():
                        doc_fmt_key = "HTML"
                    elif "TXT" in effective_target_format.upper():
                        doc_fmt_key = "TXT"
                    elif "PDF" in effective_target_format.upper():
                        doc_fmt_key = "PDF"
                    elif "MD" in effective_target_format.upper() or "MARKDOWN" in effective_target_format.upper():
                        doc_fmt_key = "MD"

                    res = convert_document(
                        source_p,
                        target_dir,
                        target_format=doc_fmt_key,
                        overwrite=overwrite,
                        reserved_paths=reserved_paths,
                        slugify_names=effective_slugify,
                        filename_prefix=effective_prefix,
                        filename_suffix=effective_suffix,
                    )
                elif is_video or is_audio or is_gif_anim:
                    # Video/Audio engine conversion
                    fmt_key = "mp4"
                    if "WEBM" in effective_target_format.upper():
                        fmt_key = "webm"
                    elif "ANIMATED WEBP" in effective_target_format.upper() or "ANIMATED" in effective_target_format.upper():
                        fmt_key = "animated_webp"
                    elif "GIF" in effective_target_format.upper():
                        fmt_key = "gif"
                    elif "AUDIO (MP3)" in effective_target_format.upper() or "MP3" in effective_target_format.upper():
                        fmt_key = "mp3"
                    elif "AAC" in effective_target_format.upper():
                        fmt_key = "aac"
                    elif "OPUS" in effective_target_format.upper():
                        fmt_key = "opus"
                    elif "WAV" in effective_target_format.upper():
                        fmt_key = "wav"

                    res = convert_media_file(
                        source_p,
                        target_dir,
                        target_format=fmt_key,
                        target_mb=effective_target_mb,
                        overwrite=overwrite,
                        reserved_paths=reserved_paths,
                        slugify_names=effective_slugify,
                        filename_prefix=effective_prefix,
                        filename_suffix=effective_suffix,
                        normalize_audio=effective_normalize_audio,
                    )
                else:
                    # Image engine conversion
                    fmt_key = normalize_output_format(effective_target_format)

                    res = convert_image(
                        source_p,
                        target_dir,
                        quality=effective_quality,
                        overwrite=overwrite,
                        reserved_paths=reserved_paths,
                        lossless=effective_lossless,
                        preserve_metadata=effective_preserve_metadata,
                        max_width=effective_max_dim,
                        max_height=effective_max_dim,
                        scale_percent=effective_scale_pct,
                        target_format=fmt_key,
                        target_kb=effective_target_kb,
                        watermark_text=effective_watermark_text,
                        watermark_logo_path=effective_watermark_logo,
                        watermark_position=effective_watermark_position,
                        strip_metadata=effective_strip_metadata,
                        slugify_names=effective_slugify,
                        filename_prefix=effective_prefix,
                        filename_suffix=effective_suffix,
                        rotate_angle=effective_rotate,
                        flip_h=effective_flip_h,
                        flip_v=effective_flip_v,
                        aspect_ratio=effective_aspect,
                        corner_radius=effective_corner,
                        grayscale=effective_grayscale,
                        min_ssim=effective_min_ssim,
                        target_ssim=effective_target_ssim,
                        operation_order=effective_order,
                        resize_condition=effective_resize_condition,
                        watermark_condition=effective_watermark_condition,
                        color_profile_mode=effective_color_profile_mode,
                        color_profile_custom=effective_color_profile_custom,
                        rendering_intent=effective_rendering_intent,
                        bit_depth=effective_bit_depth,
                        hdr_tone_mapping=effective_hdr_tone_mapping,
                        hdr_exposure=effective_hdr_exposure,
                        raw_white_balance=effective_raw_wb,
                        raw_exposure=effective_raw_exposure,
                        raw_demosaic=effective_raw_demosaic,
                        svg_scale=effective_svg_scale,
                        svg_background=effective_svg_bg,
                        psd_composite_mode=override.get("psd_composite_mode", psd_composite_mode) if use_override and "psd_composite_mode" in override else psd_composite_mode,
                        psd_layer_index=int(override.get("psd_layer_index", psd_layer_index)) if use_override and "psd_layer_index" in override else int(psd_layer_index) if str(psd_layer_index).lstrip("-").isdigit() else -1,
                    )

            with counter_lock:
                completed_count += 1
                current = completed_count

            self.events.put(("result", res))
            self.events.put(
                (
                    "progress",
                    (
                        current / total,
                        f"Processing {min(current + 1, total)} of {total} | "
                        f"{telemetry.snapshot(current).status_text()}",
                    ),
                )
            )
            return res

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(process_single, p) for p in files_snapshot]
                for f in futures:
                    results.append(f.result())
        except Exception as error:
            self.events.put(("error", str(error)))

        elapsed = time.perf_counter() - start_time
        self.events.put(
            ("complete", (results, self.cancel_event.is_set(), elapsed))
        )

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    value, message = payload
                    self.progress_value.set(value)
                    self.status_text.set(message)
                elif event == "result":
                    self._display_result(payload)
                elif event == "error":
                    self.status_text.set(f"Process error: {payload}")
                elif event == "estimate":
                    generation, text = payload
                    if generation == self._estimate_generation:
                        self.estimate_text.set(text)
                else:
                    results, cancelled, elapsed = payload
                    self.last_results = list(results)
                    self.progress_value.set(1)
                    failed = sum(result.status == "Failed" for result in results)
                    completed = sum(
                        result.status == "Completed" for result in results
                    )
                    original_total = sum(
                        result.original_size or 0 for result in results
                    )
                    output_total = sum(
                        result.output_size or 0 for result in results
                    )
                    saved_bytes = max(0, original_total - output_total)
                    saved_pct = (
                        ((original_total - output_total) / original_total * 100)
                        if original_total > 0
                        else 0.0
                    )

                    time_text = (
                        f"{elapsed:.1f}s" if elapsed >= 1 else f"{elapsed:.2f}s"
                    )
                    summary = (
                        f"Finished {completed} of {len(results)} in {time_text} "
                        f"| Total saved: {format_file_size(saved_bytes)} ({saved_pct:.1f}%)"
                    )
                    if failed > 0:
                        summary += f" • {failed} failed"

                    self.status_text.set(
                        f"Cancelled: {summary}" if cancelled else summary
                    )
                    try:
                        record_batch(results, self._collect_recipe_settings(), self.target_format.get())
                        self.log.info(
                            "batch done: %d completed, %d failed, cancelled=%s, %.2fs, saved %s",
                            completed, failed, cancelled, elapsed, format_file_size(saved_bytes),
                        )
                        for r in results:
                            if r.status == "Failed":
                                self.log.warning("failed: %s -> %s", r.source_path, r.error)
                    except Exception:
                        self.log.exception("could not record history")
                    self.conversion_running = False
                    self.pause_event.clear()
                    self._set_controls_enabled(True)
                    self.open_button.configure(state="normal")
                    self.export_csv_button.configure(state="normal")
                    if self._failed_paths():
                        self.retry_button.grid(row=2, column=1, sticky="w", padx=(8, 0))
                    else:
                        self.retry_button.grid_remove()

                    if self.play_sound.get() and not cancelled:
                        play_completion_sound()
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _display_result(self, result: ConversionResult) -> None:
        self.row_results[result.source_path] = result
        row_id = self.row_ids.get(result.source_path)
        if row_id:
            status = (
                result.status
                if result.status in ("Completed", "Cancelled")
                else f"Failed: {result.error or 'Error'}"
            )
            if result.status == "Completed" and getattr(result, "note", None):
                status = f"Completed · {result.note}"
            self.table.item(
                row_id,
                values=(
                    result.source_path.name,
                    result.original_size_text,
                    result.output_size_text,
                    result.saved,
                    status,
                ),
            )
        self._schedule_queue_save()

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.add_button.configure(state=state)
        self.add_folder_button.configure(state=state)
        self.convert_button.configure(state=state)
        self.preview_button.configure(
            state=state if self.table.selection() else "disabled"
        )
        self.optimize_button.configure(
            state=state if self.table.selection() else "disabled"
        )
        self.remove_button.configure(
            state=state if self.table.selection() else "disabled"
        )
        self.clear_button.configure(state=state)
        if getattr(self, "quality_slider", None) is not None:
            self.quality_slider.configure(state=state)
        self.quality_entry.configure(state=state)
        self.format_menu.configure(state=state)
        self.format_browse_button.configure(state=state)
        self.recipes_button.configure(state=state)
        self.same_folder_checkbox.configure(state=state)
        if hasattr(self, "move_up_button") and hasattr(self, "move_down_button"):
            self.move_up_button.configure(state=state if self.table.selection() else "disabled")
            self.move_down_button.configure(state=state if self.table.selection() else "disabled")

        if not self.save_in_source_folder.get():
            self.output_entry.configure(state=state)
            self.browse_button.configure(state=state)

        self.cancel_button.configure(state="disabled" if enabled else "normal")
        self.pause_button.configure(state="disabled" if enabled else "normal")
        if enabled:
            self.run_controls.grid_remove()
        else:
            self.run_controls.grid(row=2, column=3, padx=(0, 8))
        self._lossless_changed()

    def _cancel_conversion(self) -> None:
        if self.conversion_running:
            self.cancel_event.set()
            self.pause_event.clear()
            self.cancel_button.configure(state="disabled")
            self.pause_button.configure(state="disabled")
            self.status_text.set("Cancelling remaining items...")

    def _toggle_pause(self) -> None:
        if not self.conversion_running:
            return
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.configure(text="Pause")
            self.status_text.set("Resumed")
        else:
            self.pause_event.set()
            self.pause_button.configure(text="Resume")
            self.status_text.set("Paused — items already encoding will finish, then the queue waits")

    def _failed_paths(self) -> list[Path]:
        return [
            p for p in self.selected_files
            if (r := self.row_results.get(p)) is not None and r.status == "Failed"
        ]

    def _retry_failed(self) -> None:
        failed = self._failed_paths()
        if not failed:
            self.status_text.set("No failed items to retry")
            return
        for p in failed:
            self.row_results.pop(p, None)
            row_id = self.row_ids.get(p)
            if row_id:
                vals = list(self.table.item(row_id)["values"])
                vals[2:] = ["-", "-", "Ready"]
                self.table.item(row_id, values=vals)
        self._start_conversion(only=failed)

    def _update_button_states(self) -> None:
        if not self.conversion_running:
            has_sel = bool(self.table.selection())
            self.preview_button.configure(state="normal" if has_sel else "disabled")
            self.optimize_button.configure(state="normal" if has_sel else "disabled")
            self.remove_button.configure(state="normal" if has_sel else "disabled")
            self.clear_button.configure(
                state="normal" if self.selected_files else "disabled"
            )
            if hasattr(self, "move_up_button") and hasattr(self, "move_down_button"):
                self.move_up_button.configure(state="normal" if has_sel else "disabled")
                self.move_down_button.configure(state="normal" if has_sel else "disabled")
            self._adapt_settings_to_selection()

    def _open_output_folder(self) -> None:
        use_source = self.save_in_source_folder.get()
        if use_source and self.selected_files:
            folder = self.selected_files[0].parent
        else:
            folder = Path(self.output_directory.get().strip())
        if not folder.is_dir():
            messagebox.showerror(
                "Output folder", "The output folder does not exist."
            )
            return
        open_file_or_folder(folder)

    def _export_csv_report(self) -> None:
        if not self.last_results:
            messagebox.showinfo("Export Report", "No conversion results to export.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Save Conversion Report",
            defaultextension=".csv",
            filetypes=[("CSV Spreadsheet", "*.csv"), ("All Files", "*.*")],
            initialfile="shadow_report.csv",
        )
        if not save_path:
            return
        try:
            export_results_to_csv(self.last_results, Path(save_path))
            self.status_text.set(f"Report saved: {Path(save_path).name}")
            messagebox.showinfo(
                "Export Complete", f"Conversion report exported to:\n{save_path}"
            )
        except Exception as err:
            messagebox.showerror("Export Failed", f"Could not save CSV:\n{err}")


if __name__ == "__main__":
    _saved_theme = load_settings().get("theme", "System")
    ctk.set_appearance_mode(_saved_theme)
    ctk.set_default_color_theme(str(Path(__file__).resolve().parent / "assets" / "theme.json"))
    WebPCompressorApp().mainloop()
