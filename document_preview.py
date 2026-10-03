"""Native local document viewer: rendered Office/PDF pages and extracted text."""
from __future__ import annotations

from design_system import style_dialog

from pathlib import Path
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from doc_converter import to_markdown
from office_engine import OFFICE_EXTENSIONS, render_office
from pdf_tools import render_pdf_page
from studio_runtime import StudioCancelled
from ui_dispatch import TkEventBridge, cancel_widget_callbacks
from utils import open_file_or_folder
from document_cache import preview_pdf


class DocumentPreviewDialog(ctk.CTkToplevel):
    def __init__(self, master, source: Path):
        super().__init__(master)
        style_dialog(self, master)
        self.title(f"Document Preview — {source.name}")
        self.geometry("900x740")
        self.minsize(650, 520)
        self.source = source
        self._cancel = threading.Event()
        self._bridge = TkEventBridge(self)
        self._pdf: Path | bytes | None = None
        self._page = 0
        self._count = 0
        self._busy = False
        self._photo = None
        self._text_loaded = False
        self._text_loading = False
        self._page_cache = {}
        self._layout_loading = False
        self._page_resize_job = None
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        ctk.CTkLabel(header, text=source.name, anchor="w").pack(side="left", padx=12, pady=10)
        ctk.CTkButton(header, text="Open in default app", command=lambda: open_file_or_folder(source), width=140).pack(side="right", padx=10)
        self.tabs = ctk.CTkTabview(self, command=self._tab_changed)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16)
        page_tab = self.tabs.add("Pages")
        text_tab = self.tabs.add("Text")
        page_tab.grid_rowconfigure(0, weight=1)
        page_tab.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(page_tab)
        self.page_scroll = scroll
        scroll._parent_canvas.bind('<Configure>', self._schedule_page_fit, add='+')
        scroll.grid(row=0, column=0, sticky="nsew")
        self.page_image = ctk.CTkLabel(scroll, text="Loading document…")
        self.page_image.pack(expand=True, padx=10, pady=10)
        navigation = ctk.CTkFrame(page_tab, fg_color="transparent")
        navigation.grid(row=1, column=0, pady=8)
        self.prev = ctk.CTkButton(navigation, text="Previous", width=100, command=lambda: self._navigate(-1), state="disabled")
        self.prev.pack(side="left", padx=8)
        self.page_label = ctk.CTkLabel(navigation, text="")
        self.page_label.pack(side="left", padx=8)
        self.next = ctk.CTkButton(navigation, text="Next", width=100, command=lambda: self._navigate(1), state="disabled")
        self.next.pack(side="left", padx=8)
        self.text = ctk.CTkTextbox(text_tab, wrap="word")
        self.text.pack(fill="both", expand=True)
        self.text.insert('1.0', 'Open this tab to extract text. Layout preview loads independently.')
        self.status = tk.StringVar(value="Opening locally…")
        ctk.CTkLabel(self, textvariable=self.status, wraplength=800).grid(row=2, column=0, padx=16, pady=8)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        if source.suffix.lower() in {'.xlsx', '.xlsm'}:
            from workbook_view import WorkbookView
            self.workbook = WorkbookView(self.tabs.add('Sheets'), source, self._cancel, self._bridge, self.status)
            self.workbook.pack(fill='both', expand=True)
            self.tabs.set('Sheets')
            self.status.set('Loading workbook sheets…')
        else:self._start_layout()

    def _start_layout(self):
        if self._layout_loading or self._pdf is not None:return
        self._layout_loading = True
        self._busy = True
        threading.Thread(target=self._load, daemon=True).start()

    def _schedule_page_fit(self, event=None):
        if self._page_resize_job:self.after_cancel(self._page_resize_job)
        def fit():
            self._page_resize_job = None
            if self._page in self._page_cache:self._display(self._page_cache[self._page])
        self._page_resize_job = self.after(100, fit)

    def _tab_changed(self):
        if self.tabs.get() == 'Pages':self._start_layout()
        elif self.tabs.get() == 'Text':self._start_text()

    def _start_text(self):
        if self._text_loaded or self._text_loading:return
        self._text_loading = True
        self.text.configure(state='normal');self.text.delete('1.0', 'end')
        self.text.insert('1.0', 'Extracting text…')
        def worker():
            try:extracted = to_markdown(self.source, self._cancel.is_set)
            except Exception as exc:extracted = f'Text extraction unavailable: {exc}'
            self._bridge.post(lambda:self._show_text(extracted))
        threading.Thread(target=worker, daemon=True).start()

    def _show_text(self, extracted):
        self.text.configure(state='normal');self.text.delete('1.0', 'end')
        self.text.insert('1.0', extracted);self.text.configure(state='disabled')
        self._text_loaded = True;self._text_loading = False

    def _load(self):
        try:
            pdf = None
            if self.source.suffix.lower() == ".pdf":
                pdf = self.source
            elif self.source.suffix.lower() in OFFICE_EXTENSIONS:
                pdf, reused = preview_pdf(self.source, self._cancel.is_set,
                                          lambda message:self._bridge.post(lambda:self.status.set(message)))
            image, count = render_pdf_page(pdf) if pdf else (None, 0)
            if not pdf:
                extracted = to_markdown(self.source, self._cancel.is_set)
            else:extracted = None
            self._bridge.post(lambda: self._loaded(pdf, image, count, extracted))
        except StudioCancelled:
            pass
        except Exception as exc:
            message = str(exc)
            self._bridge.post(lambda: self._failed(message))

    def _failed(self, message):
        self._busy = False
        self._layout_loading = False
        self.status.set(message)
        self.page_image.configure(text="Preview unavailable. Use Open in default app.")

    def _loaded(self, pdf, image, count, extracted):
        self._pdf = pdf
        self._count = count
        self._busy = False
        self._layout_loading = False
        if extracted is not None:self._show_text(extracted)
        if image:
            self._display(image)
        else:
            self.page_image.configure(text="This document has a text preview.")
            self.tabs.set("Text")
        self.status.set('Read-only layout preview · Text loads on request' if pdf else 'Read-only text preview')

    def _display(self, image):
        self._page_cache[self._page] = image
        if len(self._page_cache) > 8:self._page_cache.pop(next(iter(self._page_cache)))
        available = max(300, self.page_scroll._parent_canvas.winfo_width()/self.page_scroll._get_widget_scaling()-24)
        width = min(760, image.width, int(available))
        height = int(image.height * width / image.width)
        self._photo = ctk.CTkImage(light_image=image, dark_image=image, size=(width, height))
        self.page_image.configure(image=self._photo, text="")
        item = 'Slide' if self.source.suffix.lower() in {'.ppt', '.pptx', '.pptm', '.odp', '.pps', '.ppsx'} else 'Page'
        self.page_label.configure(text=f"{item} {self._page + 1} of {self._count}")
        self.prev.configure(state="normal" if self._page > 0 else "disabled")
        self.next.configure(state="normal" if self._page + 1 < self._count else "disabled")

    def _navigate(self, delta):
        if self._busy or self._pdf is None:
            return
        index = self._page + delta
        if not 0 <= index < self._count:
            return
        if index in self._page_cache:
            self._page = index;self._display(self._page_cache[index]);return
        self._busy = True
        self.prev.configure(state="disabled")
        self.next.configure(state="disabled")
        def worker():
            try:
                image, _ = render_pdf_page(self._pdf, index)
                self._bridge.post(lambda: finish(image))
            except Exception as exc:
                message = str(exc)
                self._bridge.post(lambda: self._failed(message))
        def finish(image):
            self._page = index
            self._busy = False
            self._display(image)
        threading.Thread(target=worker, daemon=True).start()

    def destroy(self):
        self._cancel.set()
        self._bridge.close()
        cancel_widget_callbacks(self)
        super().destroy()
