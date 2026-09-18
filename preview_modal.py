from __future__ import annotations

from pathlib import Path
import tkinter as tk

import customtkinter as ctk
from PIL import ExifTags, Image, ImageChops, ImageDraw, ImageTk

from converter import ConversionResult
from utils import format_file_size, open_file_or_folder, reveal_in_file_manager


class ImagePreviewDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        source_path: Path,
        result: ConversionResult | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(f"Image Inspection & Diff - {source_path.name}")
        self.geometry("860x640")
        self.minsize(740, 520)
        self.transient(parent)

        self.source_path = source_path
        self.result = result
        self.output_path = (
            self.result.output_path
            if (self.result and self.result.output_path and self.result.output_path.exists())
            else None
        )

        self.view_mode = tk.StringVar(
            value="Split Slider" if self.output_path else "Side-by-Side"
        )
        self.split_pct = 0.50  # 50% split position
        self.zoom_factor = 1.0

        self.orig_pil: Image.Image | None = None
        self.conv_pil: Image.Image | None = None
        self.disp_orig: Image.Image | None = None
        self.disp_conv: Image.Image | None = None
        self.disp_size: tuple[int, int] = (600, 400)
        self.tk_canvas_img: ImageTk.PhotoImage | None = None

        self._load_source_images()

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

        info = f"Original: {format_file_size(self.source_path.stat().st_size)}"
        if self.result and self.result.saved:
            info += f"  ➔  Output: {self.result.output_size_text} ({self.result.saved} saved)"
        ctk.CTkLabel(
            title_frame,
            text=info,
            font=ctk.CTkFont(size=12),
            text_color=("#667085", "#98a2b3"),
        ).pack(anchor="w")

        modes = ["Split Slider", "Side-by-Side", "Difference Map", "EXIF & Details"] if self.output_path else ["Side-by-Side", "EXIF & Details"]
        mode_selector = ctk.CTkSegmentedButton(
            header,
            values=modes,
            variable=self.view_mode,
            command=self._on_mode_change,
        )
        mode_selector.pack(side="right", padx=(10, 0))

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
        self.canvas.grid(row=1, column=0, padx=16, pady=(4, 16))

        self.canvas.bind("<B1-Motion>", self._on_slider_drag)
        self.canvas.bind("<Button-1>", self._on_slider_drag)

        self._draw_split_canvas()

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

        ctk.CTkLabel(
            card,
            text=title,
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
