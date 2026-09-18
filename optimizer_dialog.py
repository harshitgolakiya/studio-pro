"""Optimizer window: sweep codecs/qualities for one image, show the Pareto
frontier and a recommendation, and apply the chosen setting to the main
window."""
from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

import customtkinter as ctk
from PIL import Image

from optimizer import (
    DEFAULT_QUALITIES,
    DESTINATIONS,
    Candidate,
    ImageProfile,
    Recommendation,
    profile_image,
    recommend,
    sweep,
)
from utils import format_file_size

_MUTED = ("#607181", "#91A0AE")
_ACCENT = "#16A394"
_CTA = "#D4A03C"


class OptimizerDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: Any,
        source_path: Path,
        on_apply: Callable[[str, int], None],
        initial_destination: str = "Web (modern browsers)",
    ) -> None:
        super().__init__(master)
        self.title(f"Optimize · {source_path.name}")
        self.geometry("880x640")
        self.minsize(760, 540)
        self.transient(master)

        self._source_path = source_path
        self._on_apply = on_apply
        self._candidates: list[Candidate] = []
        self._profile: ImageProfile | None = None
        self._recommendation: Recommendation | None = None
        self._worker: threading.Thread | None = None
        self._stop = False

        self.destination = tk.StringVar(value=initial_destination)
        self.min_ssim = tk.DoubleVar(value=0.95)
        self.fast_mode = tk.BooleanVar(value=True)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(top, text="Destination:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(top, values=list(DESTINATIONS), variable=self.destination, width=220, height=28, command=lambda _v: self._refresh_recommendation()).pack(side="left", padx=(0, 14))
        ctk.CTkLabel(top, text="Quality floor (SSIM):", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        self.floor_label = ctk.CTkLabel(top, text="0.95", width=40)
        ctk.CTkSlider(top, from_=0.85, to=0.99, number_of_steps=14, variable=self.min_ssim, width=140, command=self._floor_changed).pack(side="left")
        self.floor_label.pack(side="left", padx=(4, 14))
        ctk.CTkCheckBox(top, text="Fast (≤1024 px working copy)", variable=self.fast_mode, font=ctk.CTkFont(size=11)).pack(side="left")
        self.analyze_btn = ctk.CTkButton(top, text="Analyze", width=100, height=30, fg_color=_ACCENT, command=self.run_analysis)
        self.analyze_btn.pack(side="right")

        self.progress = ctk.CTkProgressBar(self, height=6)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=16, pady=(0, 4))
        self.status = ctk.CTkLabel(self, text="Click Analyze to compare WebP, AVIF, HEIC and JPEG at five quality levels.", text_color=_MUTED, anchor="w", font=ctk.CTkFont(size=11))
        self.status.pack(fill="x", padx=18)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=8)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        cols = ("codec", "quality", "size", "ssim", "psnr", "pareto")
        self.table = ttk.Treeview(body, columns=cols, show="headings", height=12, selectmode="browse")
        for col, text, width, anchor in (
            ("codec", "Codec", 90, "w"),
            ("quality", "Quality", 60, "center"),
            ("size", "Est. size", 90, "e"),
            ("ssim", "SSIM", 70, "e"),
            ("psnr", "PSNR", 80, "e"),
            ("pareto", "Frontier", 70, "center"),
        ):
            self.table.heading(col, text=text)
            self.table.column(col, width=width, anchor=anchor, stretch=col == "codec")
        self.table.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.table.bind("<<TreeviewSelect>>", lambda _e: self._selection_changed())
        self.table.bind("<Double-1>", lambda _e: self._apply_selected())

        self.chart = tk.Canvas(body, highlightthickness=0, bd=0)
        self.chart.grid(row=0, column=1, sticky="nsew")
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())

        self.reco_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=820, font=ctk.CTkFont(size=12))
        self.reco_label.pack(fill="x", padx=18, pady=(2, 6))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 14))
        self.apply_reco_btn = ctk.CTkButton(actions, text="Apply recommendation", width=180, height=32, fg_color=_CTA, hover_color="#E8B750", text_color="#1a1a1a", state="disabled", command=self._apply_recommendation)
        self.apply_reco_btn.pack(side="left", padx=(0, 8))
        self.apply_sel_btn = ctk.CTkButton(actions, text="Apply selected", width=130, height=32, state="disabled", command=self._apply_selected)
        self.apply_sel_btn.pack(side="left")
        ctk.CTkButton(actions, text="Close", width=90, height=32, fg_color="transparent", border_width=1, command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self._close)

    # -- analysis ----------------------------------------------------------

    def _floor_changed(self, value: float) -> None:
        self.floor_label.configure(text=f"{float(value):.2f}")
        self._refresh_recommendation()

    def run_analysis(self, synchronous: bool = False, codecs: tuple[str, ...] = ("WEBP", "AVIF", "HEIC", "JPEG")) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop = False
        self.analyze_btn.configure(state="disabled")
        self.progress.set(0)
        self.status.configure(text="Loading image…")
        max_edge = 1024 if self.fast_mode.get() else 10_000

        def work() -> None:
            try:
                with Image.open(self._source_path) as img:
                    img.load()
                    image = img.convert("RGBA") if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info else img.convert("RGB")
                    profile = profile_image(img)
                cands = sweep(
                    image,
                    codecs=codecs,
                    qualities=DEFAULT_QUALITIES,
                    max_edge=max_edge,
                    progress=lambda d, t, label: self._post(lambda: self._progress(d, t, label)),
                    should_stop=lambda: self._stop,
                )
                self._post(lambda: self._finished(profile, cands))
            except Exception as exc:  # pragma: no cover - surfaced in UI
                self._post(lambda: self._failed(str(exc)))

        if synchronous:
            work()
        else:
            self._worker = threading.Thread(target=work, daemon=True)
            self._worker.start()

    def _post(self, fn: Callable[[], None]) -> None:
        try:
            if threading.current_thread() is threading.main_thread():
                fn()
            else:
                self.after(0, fn)
        except Exception:
            pass

    def _progress(self, done: int, total: int, label: str) -> None:
        self.progress.set(done / total if total else 0)
        self.status.configure(text=f"Encoding {label}  ({done}/{total})")

    def _failed(self, message: str) -> None:
        self.analyze_btn.configure(state="normal")
        self.status.configure(text=f"Analysis failed: {message}")

    def _finished(self, profile: ImageProfile, cands: list[Candidate]) -> None:
        self._profile = profile
        self._candidates = cands
        self.analyze_btn.configure(state="normal")
        self.progress.set(1)
        kind = "photo" if profile.kind == "photo" else "graphic"
        alpha = ", transparent" if profile.has_alpha else ""
        note = "" if self.fast_mode.get() else " · exact sizes"
        self.status.configure(text=f"{len(cands)} candidates · {profile.width}×{profile.height} {kind}{alpha}{note}")
        self._fill_table()
        self._refresh_recommendation()
        self._draw_chart()

    # -- presentation ------------------------------------------------------

    def _fill_table(self) -> None:
        self.table.delete(*self.table.get_children())
        for idx, c in enumerate(sorted(self._candidates, key=lambda c: c.size_bytes)):
            psnr_text = "∞" if c.psnr == float("inf") else f"{c.psnr:.1f} dB"
            self.table.insert("", "end", iid=str(idx), values=(c.codec, c.quality, format_file_size(c.estimated_full_bytes), f"{c.ssim:.4f}", psnr_text, "★" if c.pareto else ""), tags=("pareto",) if c.pareto else ())
        self.table.tag_configure("pareto", foreground=_ACCENT)
        self._sorted = sorted(self._candidates, key=lambda c: c.size_bytes)

    def _refresh_recommendation(self) -> None:
        if not self._candidates or self._profile is None:
            return
        self._recommendation = recommend(self._candidates, self._profile, self.destination.get(), float(self.min_ssim.get()))
        pick = self._recommendation.candidate
        if pick is None:
            self.reco_label.configure(text=f"No recommendation: {self._recommendation.reason}")
            self.apply_reco_btn.configure(state="disabled")
        else:
            alts = ", ".join(f"{a.codec} q{a.quality} ({format_file_size(a.estimated_full_bytes)})" for a in self._recommendation.alternatives)
            text = f"Recommended: {pick.codec} at quality {pick.quality} — about {format_file_size(pick.estimated_full_bytes)}, SSIM {pick.ssim:.3f}. {self._recommendation.reason.capitalize()}."
            if alts:
                text += f"\nAlso on the frontier: {alts}."
            self.reco_label.configure(text=text)
            self.apply_reco_btn.configure(state="normal")
        self._draw_chart()

    def _draw_chart(self) -> None:
        c = self.chart
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60 or h < 60:
            return
        dark = ctk.get_appearance_mode() == "Dark"
        bg = "#11161D" if dark else "#FFFFFF"
        fg = "#91A0AE" if dark else "#607181"
        c.configure(bg=bg)
        pad_l, pad_r, pad_t, pad_b = 46, 12, 14, 30
        c.create_text(w / 2, 8, text="File size vs SSIM (★ = Pareto frontier)", fill=fg, font=("TkDefaultFont", 9))
        if not self._candidates:
            c.create_text(w / 2, h / 2, text="Run Analyze to plot candidates", fill=fg)
            return
        xs = [cand.estimated_full_bytes for cand in self._candidates]
        ys = [cand.ssim for cand in self._candidates]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x1 == x0:
            x1 = x0 + 1
        if y1 - y0 < 0.01:
            y0, y1 = y0 - 0.005, y1 + 0.005

        def px(x: float) -> float:
            return pad_l + (x - x0) / (x1 - x0) * (w - pad_l - pad_r)

        def py(y: float) -> float:
            return h - pad_b - (y - y0) / (y1 - y0) * (h - pad_t - pad_b)

        c.create_line(pad_l, h - pad_b, w - pad_r, h - pad_b, fill=fg)
        c.create_line(pad_l, pad_t, pad_l, h - pad_b, fill=fg)
        c.create_text(w - pad_r, h - pad_b + 12, text=format_file_size(x1), fill=fg, anchor="e", font=("TkDefaultFont", 8))
        c.create_text(pad_l, h - pad_b + 12, text=format_file_size(x0), fill=fg, anchor="w", font=("TkDefaultFont", 8))
        c.create_text(pad_l - 4, pad_t, text=f"{y1:.3f}", fill=fg, anchor="e", font=("TkDefaultFont", 8))
        c.create_text(pad_l - 4, h - pad_b, text=f"{y0:.3f}", fill=fg, anchor="e", font=("TkDefaultFont", 8))

        floor = float(self.min_ssim.get())
        if y0 <= floor <= y1:
            c.create_line(pad_l, py(floor), w - pad_r, py(floor), fill=_CTA, dash=(3, 3))

        colours = {"WEBP": "#16A394", "AVIF": "#6D28D9", "HEIC": "#1D4ED8", "JPEG": "#B45309", "JPEG 2000": "#0369A1"}
        frontier = sorted((cand for cand in self._candidates if cand.pareto), key=lambda cand: cand.size_bytes)
        if len(frontier) > 1:
            c.create_line(*[coord for cand in frontier for coord in (px(cand.estimated_full_bytes), py(cand.ssim))], fill=fg, width=1)
        pick = self._recommendation.candidate if self._recommendation else None
        for cand in self._candidates:
            x, y = px(cand.estimated_full_bytes), py(cand.ssim)
            r = 5 if cand.pareto else 3
            colour = colours.get(cand.codec, fg)
            c.create_oval(x - r, y - r, x + r, y + r, fill=colour, outline=bg if cand is not pick else _CTA, width=2 if cand is pick else 1)
        legend_y = pad_t + 4
        for codec, colour in colours.items():
            if any(cand.codec == codec for cand in self._candidates):
                c.create_oval(w - pad_r - 70, legend_y, w - pad_r - 62, legend_y + 8, fill=colour, outline=colour)
                c.create_text(w - pad_r - 58, legend_y + 4, text=codec, fill=fg, anchor="w", font=("TkDefaultFont", 8))
                legend_y += 13

    # -- actions -----------------------------------------------------------

    def _selection_changed(self) -> None:
        self.apply_sel_btn.configure(state="normal" if self.table.selection() else "disabled")

    def _selected_candidate(self) -> Candidate | None:
        sel = self.table.selection()
        if not sel:
            return None
        try:
            return self._sorted[int(sel[0])]
        except (ValueError, IndexError, AttributeError):
            return None

    def _apply_selected(self) -> None:
        cand = self._selected_candidate()
        if cand is not None:
            self._apply(cand)

    def _apply_recommendation(self) -> None:
        if self._recommendation and self._recommendation.candidate:
            self._apply(self._recommendation.candidate)

    def _apply(self, cand: Candidate) -> None:
        try:
            self._on_apply(cand.codec, cand.quality)
        finally:
            self._close()

    def _close(self) -> None:
        self._stop = True
        self.destroy()
