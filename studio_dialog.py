"""Agency tools with local PDF and speech workflows."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from doc_converter import SUPPORTED_DOCUMENT_EXTENSIONS, to_markdown
from audio_tools import ENCODERS, process_audio
from document_preview import DocumentPreviewDialog
from media_engine import SUPPORTED_AUDIO_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS, get_ffmpeg_path
from pdf_tools import process_pdf
from speech_engine import available_voices, default_voice, default_whisper_model, synthesize_speech, transcribe_media
from studio_runtime import StudioCancelled, find_libreoffice
from ui_dispatch import TkEventBridge, cancel_widget_callbacks
from utils import open_file_or_folder


class NavigationTabs(ctk.CTkTabview):
    def _grid_forget_all_tabs(self, exclude_name=None):
        # CTk queues tab cleanup for 100ms later. Rapid navigation must keep
        # the current page, rather than hiding it for an earlier selection.
        if exclude_name is not None:
            exclude_name = self.get()
        super()._grid_forget_all_tabs(exclude_name)


class StudioToolsDialog(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Shadow — Studio Tools")
        scale = self._get_window_scaling()
        width = min(940, max(640, int((self.winfo_screenwidth() - 80) / scale)))
        height = min(760, max(480, int((self.winfo_screenheight() - 100) / scale)))
        left = max(0, int((self.winfo_screenwidth() - width * scale) / 2))
        top = max(0, int((self.winfo_screenheight() - height * scale - 80) / 2))
        self.geometry(f"{width}x{height}+{left}+{top}")
        self.minsize(min(740, width), min(620, height))
        self._master = master
        self._bridge = TkEventBridge(self)
        self._cancel = threading.Event()
        self._busy = False
        self._actions = []
        self._last_output = None
        self._preview_output = None
        from audio_preview import WavPlayer
        self._player = WavPlayer()
        self._pdfs: list[Path] = []
        self._voice = None
        self._model = None
        self.output = tk.StringVar(value=master.output_directory.get() or str(Path.home() / "Documents" / "Shadow"))
        self.source = tk.StringVar()
        self.transcript_format = tk.StringVar(value="TXT")
        self.language = tk.StringVar(value="English")
        self.pdf_operation = tk.StringVar(value="Merge PDFs")
        self.pages = tk.StringVar(value="all")
        self.rotation = tk.StringVar(value="90")
        self.speed = tk.StringVar(value="1.0")
        self.audio_source = tk.StringVar()
        self.audio_format = tk.StringVar(value="WAV")
        self.audio_normalize = tk.BooleanVar(value=True)
        self.audio_denoise = tk.BooleanVar(value=False)
        self.audio_start = tk.StringVar(value="0")
        self.audio_duration = tk.StringVar()
        self.status = tk.StringVar(value="Ready. All file processing stays on this computer.")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Creative studio", font=ctk.CTkFont(family="Outfit", size=25, weight="bold"), anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 4))
        tabs = NavigationTabs(self)
        self.tabs = tabs
        tabs.grid(row=1, column=1, sticky="nsew", padx=(4, 20), pady=8)
        self._documents(tabs.add("Documents"))
        self._pdf_tools(tabs.add("PDF Tools"))
        self._transcription(tabs.add("Audio to Text"))
        self._synthesis(tabs.add("Text to Audio"))
        self._audio_tools(tabs.add("Audio Tools"))
        from studio_expansion_ui import build_expansion_pages
        self.panels = build_expansion_pages(self, tabs)
        self._engines(tabs.add("Engines"))
        tabs._segmented_button.grid_forget()
        navigation = ctk.CTkScrollableFrame(self, width=155, fg_color="transparent")
        navigation.grid(row=1, column=0, sticky="ns", padx=(16, 0), pady=8)
        self._navigation = {}
        for title, label in (("Documents", "Documents"), ("PDF Tools", "PDF pages"), ("Audio to Text", "Audio to text"),
                             ("Text to Audio", "Text to audio"), ("Audio Tools", "Audio tools"), ("OCR", "OCR / scans"),
                             ("Data", "Data / sheets"), ("Archives", "Archives / delivery"), ("Advanced workflows", "Advanced tools"),
                             ("Projects", "Projects / brands"), ("Integrations", "Integrations / API"), ("Models", "Voices / models"), ("Engines", "Engine status")):
            button = ctk.CTkButton(navigation, text=label, width=150, height=34, anchor="w", fg_color="transparent",
                                  text_color=("#777785", "#aaa7b8"), hover_color=("#EEEEF4", "#292932"), command=lambda name=title: self.show_page(name))
            button.pack(fill="x", pady=3)
            self._navigation[title] = button
        self.show_page("Documents")
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", padx=24, pady=10)
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(footer, text="Output folder").grid(row=0, column=0, padx=(0, 10))
        ctk.CTkEntry(footer, textvariable=self.output).grid(row=0, column=1, sticky="ew")
        self._button(footer, "Browse", self._browse_output).grid(row=0, column=2, padx=8)
        self.open_output = ctk.CTkButton(footer, text="Open output", width=110, state="disabled", command=self._open_output)
        self.open_output.grid(row=1, column=0, pady=10)
        ctk.CTkLabel(footer, textvariable=self.status, wraplength=590, anchor="w").grid(row=1, column=1, sticky="ew", padx=10)
        self.cancel = ctk.CTkButton(footer, text="Cancel", width=90, state="disabled", command=self._cancel.set)
        self.cancel.grid(row=1, column=2)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def show_page(self, name):
        self.tabs.set(name)
        for title, button in getattr(self, "_navigation", {}).items():
            button.configure(fg_color=("#E2DDF3", "#2B2639") if title == name else "transparent")

    def open_tool(self, key, paths=()):
        if self._busy:
            self.status.set("Wait for the current operation to finish.")
            return
        from studio_workflows import WORKFLOWS
        paths = list(paths)
        if key in WORKFLOWS:
            self.panels["Advanced workflows"].select_tool(key, paths)
            self.show_page("Advanced workflows")
        elif key in {"ocr", "data-convert", "data-clean", "data-export-sheets", "archive-create", "archive-extract", "delivery-create", "delivery-verify"}:
            from studio_actions import ACTION_LABELS
            page = "OCR" if key == "ocr" else "Data" if key.startswith("data-") else "Archives"
            panel = self.panels[page]
            panel.select(paths)
            panel.action.set(ACTION_LABELS[key])
            self.show_page(page)
        elif key.startswith("pdf-"):
            self._pdfs = paths
            self.pdf_list.configure(state="normal")
            self.pdf_list.delete("1.0", "end")
            self.pdf_list.insert("1.0", "\n".join(f"{i}. {p.name}" for i, p in enumerate(paths, 1)))
            self.pdf_list.configure(state="disabled")
            self.pdf_operation.set({"pdf-merge": "Merge PDFs", "pdf-extract": "Extract pages", "pdf-rotate": "Rotate pages", "pdf-compress": "Compress PDF", "pdf-images": "Pages to PNG ZIP"}[key])
            self.show_page("PDF Tools")
        elif key == "transcribe":
            self.source.set(str(paths[0]) if paths else "")
            self.show_page("Audio to Text")
        elif key == "audio":
            self.audio_source.set(str(paths[0]) if paths else "")
            self.show_page("Audio Tools")
        elif key == "speak":
            self.show_page("Text to Audio")
            if paths:
                source = paths[0]
                def work(progress):
                    text = to_markdown(source, self._cancel.is_set)
                    self._bridge.post(lambda: self._set_script(text))
                self._run(work)
        else:
            page = {"models": "Models", "projects": "Projects", "integrations": "Integrations", "engines": "Engines"}[key]
            self.show_page(page)
            if key == "projects" and paths:
                panel = self.panels[page]
                panel.sources = paths
                panel.report.configure(text="\n".join(str(p) for p in paths))
        self.lift()

    def _button(self, parent, text, command, width=145):
        button = ctk.CTkButton(parent, text=text, command=command, width=width)
        if text in {"Generate speech", "Transcribe", "Process PDFs", "Process audio"}:
            button.configure(fg_color="#7561D4", hover_color="#8975E4", text_color="#ffffff")
        self._actions.append(button)
        return button

    def _copy(self, parent, text):
        ctk.CTkLabel(parent, text=text, wraplength=680, justify="left", anchor="w").pack(fill="x", padx=14, pady=(12, 8))

    def _documents(self, tab):
        self._copy(tab, "Word, PowerPoint, Excel, OpenDocument, PDF, Markdown, HTML, and text. "
                   "Add files to the main queue, then choose a target format for batch conversion.")
        self._button(tab, "Add documents to queue", self._add_documents).pack(anchor="w", padx=14, pady=8)
        self._button(tab, "Open document preview", self._preview_document).pack(anchor="w", padx=14, pady=8)
        self._copy(tab, "Office → PDF keeps the document layout through LibreOffice. Presentations stay presentations; "
                   "spreadsheets stay spreadsheets. Text extraction to Markdown/TXT does not retain the original layout. "
                   "PDF → DOCX uses positioned content; inspect layout and fonts before delivery.")
        self._copy(tab, "Common workflows: client proposal DOC/DOCX → PDF · pitch PPT/PPTX → PDF · "
                   "campaign budget XLS/XLSX → PDF or CSV · legacy Office → modern Office · meeting notes → Markdown.")

    def _add_documents(self):
        paths = filedialog.askopenfilenames(parent=self, title="Add documents", filetypes=[("Documents", " ".join(f"*{e}" for e in sorted(SUPPORTED_DOCUMENT_EXTENSIONS))), ("All files", "*.*")])
        self._master._ingest_image_paths([Path(p) for p in paths])

    def _preview_document(self):
        name = filedialog.askopenfilename(parent=self, title="Open document", filetypes=[("Documents", " ".join(f"*{e}" for e in sorted(SUPPORTED_DOCUMENT_EXTENSIONS)))])
        if name:
            DocumentPreviewDialog(self, Path(name))

    def _pdf_tools(self, tab):
        self._copy(tab, "Merge documents in the order selected, extract page ranges, rotate pages, compress losslessly, "
                   "or export pages as PNG images inside a ZIP. Originals are kept.")
        self._button(tab, "Select PDFs", self._choose_pdfs).pack(anchor="w", padx=14, pady=6)
        self.pdf_list = ctk.CTkTextbox(tab, height=130)
        self.pdf_list.pack(fill="x", padx=14, pady=8)
        self.pdf_list.configure(state="disabled")
        ctk.CTkOptionMenu(tab, variable=self.pdf_operation, values=["Merge PDFs", "Extract pages", "Rotate pages", "Compress PDF", "Pages to PNG ZIP"]).pack(anchor="w", padx=14, pady=8)
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=8)
        ctk.CTkLabel(row, text="Pages (all or 1,3-5)").pack(side="left", padx=(0, 8))
        ctk.CTkEntry(row, textvariable=self.pages, width=150).pack(side="left")
        ctk.CTkLabel(row, text="Rotation").pack(side="left", padx=12)
        ctk.CTkOptionMenu(row, variable=self.rotation, values=["90", "180", "270"], width=90).pack(side="left")
        self._button(tab, "Process PDFs", self._process_pdf).pack(anchor="w", padx=14, pady=12)
        self._copy(tab, "For extraction, rotation, compression, and PNG export, select one PDF. "
                   "Compression keeps image quality; already optimized PDFs may not become smaller.")

    def _choose_pdfs(self):
        paths = filedialog.askopenfilenames(parent=self, title="Select PDFs in merge order", filetypes=[("PDF", "*.pdf")])
        if paths:
            self._pdfs = [Path(p) for p in paths]
            self.pdf_list.configure(state="normal")
            self.pdf_list.delete("1.0", "end")
            self.pdf_list.insert("1.0", "\n".join(f"{i}. {p.name}" for i, p in enumerate(self._pdfs, 1)))
            self.pdf_list.configure(state="disabled")

    def _process_pdf(self):
        operation = {"Merge PDFs": "merge", "Extract pages": "extract", "Rotate pages": "rotate", "Compress PDF": "compress", "Pages to PNG ZIP": "images"}[self.pdf_operation.get()]
        if not self._pdfs:
            self.status.set("Select PDF files first.")
            return
        extension = ".zip" if operation == "images" else ".pdf"
        output = filedialog.asksaveasfilename(parent=self, title="Save PDF result", initialdir=self.output.get(), initialfile="studio-result" + extension, defaultextension=extension, filetypes=[("Output", "*" + extension)])
        if output:
            sources, pages, rotation = list(self._pdfs), self.pages.get(), int(self.rotation.get())
            self._run(lambda progress: process_pdf(sources, Path(output), operation, pages, rotation, cancel_check=self._cancel.is_set))

    def _transcription(self, tab):
        self._copy(tab, "Transcribe recordings, interviews, voice notes, and video soundtracks locally. Export plain text, "
                   "timed subtitles, or timestamped JSON. English is the default; multilingual models can be selected.")
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        ctk.CTkEntry(row, textvariable=self.source).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._button(row, "Choose media", self._choose_media).pack(side="left")
        ctk.CTkOptionMenu(tab, variable=self.transcript_format, values=["TXT", "SRT", "VTT", "JSON"]).pack(anchor="w", padx=14, pady=8)
        ctk.CTkOptionMenu(tab, variable=self.language, values=["English", "Auto-detect"]).pack(anchor="w", padx=14, pady=8)
        self._button(tab, "Choose local model", self._choose_model).pack(anchor="w", padx=14, pady=8)
        self.model_label = ctk.CTkLabel(tab, text=str(default_whisper_model()), wraplength=680, anchor="w")
        self.model_label.pack(fill="x", padx=14)
        self._button(tab, "Transcribe", self._transcribe).pack(anchor="w", padx=14, pady=16)
        self._copy(tab, "Review transcripts before publishing. Transcription does not identify speakers. "
                   "Auto-detect requires a multilingual model; the bundled base.en model is English-only.")

    def _choose_media(self):
        extensions = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS
        source = filedialog.askopenfilename(parent=self, title="Choose audio or video", filetypes=[("Media", " ".join(f"*{e}" for e in sorted(extensions))), ("All files", "*.*")])
        if source:
            self.source.set(source)

    def _choose_model(self):
        name = filedialog.askdirectory(parent=self, title="Select faster-whisper model directory")
        if name:
            self._model = Path(name)
            self.model_label.configure(text=name)

    def _transcribe(self):
        source = Path(self.source.get())
        output, fmt, model = Path(self.output.get()), self.transcript_format.get(), self._model
        language = "en" if self.language.get() == "English" else None
        def work(progress):
            result = transcribe_media(source, output, fmt, model, language, cancel_check=self._cancel.is_set, progress=progress)
            if result.status == "Cancelled":
                raise StudioCancelled()
            if result.status != "Completed":
                raise RuntimeError(result.error)
            return result.output_path
        self._run(work)

    def _synthesis(self, tab):
        # Reserve the controls' rows; only the script editor shrinks on shorter
        # screens. Packing the expanding editor first could clip the action.
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(tab, text="Create a voiceover from a script. Choose a voice, generate, then play.",
                     wraplength=500, justify="left", anchor="w").grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 4))
        self.script = ctk.CTkTextbox(tab, height=80, wrap="word")
        self.script.grid(row=1, column=0, sticky="nsew", padx=14, pady=4)
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=14, pady=3)
        self._button(row, "Load document text", self._load_script).pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(row, variable=self.speed, values=["0.5", "0.75", "1.0", "1.25", "1.5", "2.0"], width=85).pack(side="right")
        ctk.CTkLabel(row, text="Speed").pack(side="right", padx=8)
        voices = ctk.CTkFrame(tab, fg_color="transparent")
        voices.grid(row=3, column=0, sticky="ew", padx=14, pady=3)
        voices.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(voices, text="Voice").grid(row=0, column=0, padx=(0, 8))
        self.voice_choice = tk.StringVar(master=self)
        self.voice_menu = ctk.CTkOptionMenu(voices, variable=self.voice_choice, values=["No installed voices"], command=self._select_voice)
        self.voice_menu.grid(row=0, column=1, sticky="ew")
        self._button(voices, "Refresh", self._refresh_voices, width=75).grid(row=0, column=2, padx=8)
        self._button(voices, "Browse custom voice", self._choose_voice, width=175).grid(row=0, column=3)
        self.voice_label = ctk.CTkLabel(voices, text="", anchor="w")
        self.voice_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        # Keep the action parented to the tab for scaling/visibility checks.
        self.generate_speech = self._button(tab, "Generate speech", self._speak)
        self.generate_speech.grid(row=4, column=0, sticky="w", padx=14, pady=(4, 8))
        playback = ctk.CTkFrame(tab, fg_color="transparent")
        playback.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 8))
        playback.grid_columnconfigure(0, weight=1)
        self.audio_device = tk.StringVar(master=self, value="System default")
        try:
            from audio_preview import output_devices
            self._devices = output_devices()
        except Exception:
            self._devices = {"System default": None}
        self.device_menu = ctk.CTkOptionMenu(playback, variable=self.audio_device, values=list(self._devices))
        self.device_menu.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.play_audio = ctk.CTkButton(playback, text="Play", width=65, state="disabled", command=self._play_audio)
        self.play_audio.grid(row=0, column=1, padx=(0, 6))
        self.stop_audio = ctk.CTkButton(playback, text="Stop", width=65, state="disabled", command=self._stop_audio)
        self.stop_audio.grid(row=0, column=2)
        self.audio_preview_status = self.status
        self._refresh_voices()

    def _play_audio(self):
        if not self._preview_output:
            return
        try:
            self.play_audio.configure(state="disabled")
            self.stop_audio.configure(state="normal")
            self.audio_preview_status.set(f"Playing through {self.audio_device.get()}")
            self._player.play(self._preview_output, device=self._devices[self.audio_device.get()],
                              finished=lambda error: self._bridge.post(lambda: self._playback_finished(error)))
        except Exception as exc:
            self._playback_finished(str(exc))

    def _stop_audio(self):
        self._player.stop()

    def _playback_finished(self, error):
        self.stop_audio.configure(state="disabled")
        self.play_audio.configure(state="normal" if self._preview_output else "disabled")
        self.audio_preview_status.set(f"Playback failed: {error}. Try another output device." if error else "Preview finished · choose another output device if you could not hear it")

    def _refresh_voices(self):
        from model_catalog import catalog
        labels = {entry.marker.removesuffix(".onnx.json"): entry.label for entry in catalog() if entry.kind == "voice"}
        paths = [voice for voice in available_voices() if Path(str(voice) + ".json").is_file()]
        self._voices = {labels.get(voice.stem, voice.stem): voice for voice in paths}
        if self._voice and self._voice.is_file() and Path(str(self._voice) + ".json").is_file() and self._voice not in self._voices.values():
            self._voices[f"Custom: {self._voice.stem}"] = self._voice
        selected = self._voice or default_voice()
        choice = next((label for label, path in self._voices.items() if path == selected), next(iter(self._voices), "No installed voices"))
        self.voice_menu.configure(values=list(self._voices) or ["No installed voices"])
        self.voice_menu.set(choice)
        self._select_voice(choice)
        self.voice_label.configure(text=f"{len(paths)} installed voices available" if paths else "Install a voice in Voices / models, or browse for a custom voice.")

    def _select_voice(self, choice):
        self._voice = self._voices.get(choice)

    def _choose_voice(self):
        name = filedialog.askopenfilename(parent=self, title="Select Piper voice", filetypes=[("Piper voice", "*.onnx")])
        if name:
            if not Path(name + ".json").is_file():
                self.status.set("The voice needs its matching .onnx.json file in the same folder.")
                return
            self._voice = Path(name)
            self._refresh_voices()

    def _load_script(self):
        name = filedialog.askopenfilename(parent=self, title="Read script from document", filetypes=[("Documents", " ".join(f"*{e}" for e in sorted(SUPPORTED_DOCUMENT_EXTENSIONS)))])
        if name:
            def work(progress):
                text = to_markdown(Path(name), self._cancel.is_set)
                self._bridge.post(lambda: self._set_script(text))
                return None
            self._run(work)

    def _set_script(self, text):
        self.script.delete("1.0", "end")
        self.script.insert("1.0", text)

    def _speak(self):
        if not self.script.get("1.0", "end-1c").strip():
            self.status.set("Write or load a script first.")
            return
        self._player.stop()
        text, voice, speed = self.script.get("1.0", "end-1c"), self._voice, float(self.speed.get())
        output = filedialog.asksaveasfilename(parent=self, title="Save voiceover", initialdir=self.output.get(), initialfile="voiceover.wav", defaultextension=".wav", filetypes=[("WAV audio", "*.wav")])
        if output:
            self._run(lambda progress: synthesize_speech(text, Path(output), voice, speed, cancel_check=self._cancel.is_set, progress=progress))

    def _audio_tools(self, tab):
        self._copy(tab, "Prepare voiceovers, podcasts, and video soundtracks: normalize loudness, reduce steady background "
                   "noise, trim a segment, and export delivery formats. Original files are kept.")
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)
        ctk.CTkEntry(row, textvariable=self.audio_source).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._button(row, "Choose media", self._choose_audio).pack(side="left")
        ctk.CTkOptionMenu(tab, variable=self.audio_format, values=list(ENCODERS)).pack(anchor="w", padx=14, pady=8)
        ctk.CTkCheckBox(tab, text="Normalize loudness for spoken content", variable=self.audio_normalize).pack(anchor="w", padx=14, pady=8)
        ctk.CTkCheckBox(tab, text="Reduce steady background noise", variable=self.audio_denoise).pack(anchor="w", padx=14, pady=8)
        trim = ctk.CTkFrame(tab, fg_color="transparent")
        trim.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(trim, text="Start (seconds)").pack(side="left", padx=(0, 8))
        ctk.CTkEntry(trim, textvariable=self.audio_start, width=85).pack(side="left")
        ctk.CTkLabel(trim, text="Duration (empty = rest)").pack(side="left", padx=12)
        ctk.CTkEntry(trim, textvariable=self.audio_duration, width=85).pack(side="left")
        self._button(tab, "Process audio", self._process_audio).pack(anchor="w", padx=14, pady=12)
        self._copy(tab, "Noise reduction works best on consistent hum or hiss. Listen to the output before delivery; "
                   "strong noise and overlapping voices cannot always be cleaned completely.")

    def _choose_audio(self):
        extensions = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS
        name = filedialog.askopenfilename(parent=self, title="Choose audio or video", filetypes=[("Media", " ".join(f"*{e}" for e in sorted(extensions)))])
        if name:
            self.audio_source.set(name)

    def _process_audio(self):
        try:
            start = float(self.audio_start.get())
            duration = float(self.audio_duration.get()) if self.audio_duration.get().strip() else None
        except ValueError:
            self.status.set("Enter start and duration as seconds.")
            return
        source, fmt = Path(self.audio_source.get()), self.audio_format.get()
        normalize, denoise = self.audio_normalize.get(), self.audio_denoise.get()
        ext = ENCODERS[fmt][0]
        output = filedialog.asksaveasfilename(parent=self, title="Save processed audio", initialdir=self.output.get(), initialfile="audio-master" + ext, defaultextension=ext, filetypes=[(fmt, "*" + ext)])
        if output:
            self._run(lambda progress: process_audio(source, Path(output), fmt, normalize, denoise, start, duration,
                                                    cancel_check=self._cancel.is_set))

    def _engines(self, tab):
        self._copy(tab, "Engine readiness")
        self.engine_status = ctk.CTkTextbox(tab, height=230, wrap="word")
        self.engine_status.pack(fill="x", padx=14, pady=12)
        self._button(tab, "Refresh engines", self._refresh_engines).pack(anchor="w", padx=14, pady=8)
        self._copy(tab, "Source setup: run setup_studio.ps1 with your Python environment. "
                   "It downloads LibreOffice and English speech models once. Conversions never download models or upload files.")
        self._refresh_engines()

    def _refresh_engines(self):
        def available(name):
            return importlib.util.find_spec(name) is not None
        entries = [
            ("Office engine", find_libreoffice() or "Missing — run setup_studio.ps1"),
            ("FFmpeg", get_ffmpeg_path() or "Missing"),
            ("PDF page viewer", "Ready" if available("pypdfium2") else "Missing package pypdfium2"),
            ("Transcription engine", "Ready" if available("faster_whisper") else "Missing package faster-whisper"),
            ("English transcription model", "Ready" if (default_whisper_model() / "model.bin").is_file() else "Missing — run setup_studio.ps1"),
            ("Speech synthesis engine", "Ready" if available("piper") else "Missing package piper-tts"),
            ("Voice models", ", ".join(p.stem for p in available_voices()) or "Missing — run setup_studio.ps1"),
        ]
        from ocr_engine import available_ocr_languages
        from translation_engine import installed_pairs
        from speech_engine import diarization_models
        from audio_tools import voice_isolation_model
        from print_tools import ghostscript_path
        entries.extend([
            ("OCR scripts", ", ".join(available_ocr_languages()) if available("rapidocr") else "Missing rapidocr"),
            ("Translation pairs", ", ".join(f"{a}-{b}" for a, b in installed_pairs()) or "Install pairs in More Tools > Models"),
            ("Speaker labels", "Ready" if all(p.is_file() for p in diarization_models()) else "Install speaker models"),
            ("Voice isolation", "Ready" if voice_isolation_model().is_file() else "Install isolation model"),
            ("Print engine", ghostscript_path() or "Missing Ghostscript"),
        ])
        self.engine_status.configure(state="normal")
        self.engine_status.delete("1.0", "end")
        self.engine_status.insert("1.0", "\n\n".join(f"{name}: {value}" for name, value in entries))
        self.engine_status.configure(state="disabled")

    def _browse_output(self):
        name = filedialog.askdirectory(parent=self, title="Output folder")
        if name:
            self.output.set(name)

    def _open_output(self):
        if self._last_output:
            open_file_or_folder(self._last_output if self._last_output.is_dir() else self._last_output.parent)

    def _run(self, work):
        if self._busy:
            return
        self._busy = True
        self._cancel.clear()
        for action in self._actions:
            action.configure(state="disabled")
        self.cancel.configure(state="normal")
        self.status.set("Processing locally…")
        def progress(message):
            self._bridge.post(lambda: self.status.set(message))
        def worker():
            try:
                result = work(progress)
                self._bridge.post(lambda: self._finish(result, None))
            except StudioCancelled:
                self._bridge.post(lambda: self._finish(None, "Cancelled"))
            except Exception as exc:
                message = str(exc)
                self._bridge.post(lambda: self._finish(None, message))
        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, output, error):
        self._busy = False
        for action in self._actions:
            action.configure(state="normal")
        self.cancel.configure(state="disabled")
        if error:
            self.status.set(error)
            if error != "Cancelled":
                messagebox.showerror("Studio operation failed", error, parent=self)
        else:
            self.status.set(f"Completed: {output.name}" if output else "Completed")
            if output:
                self._last_output = output
                self.open_output.configure(state="normal")
                if output.suffix.lower() == ".wav":
                    from audio_preview import wav_info
                    self._preview_output = output
                    self.play_audio.configure(state="normal")
                    info = wav_info(output)
                    message = f"{output.name} · {info['duration']:.1f}s audio ready · choose output and press Play"
                    if info['peak'] < 0.001: message = "This audio is silent or very quiet. Try another voice."
                    self.audio_preview_status.set(message)

    def destroy(self):
        self._player.stop()
        self._cancel.set()
        server = getattr(self, "_automation_server", None)
        if server:
            server.stop()
        self._bridge.close()
        cancel_widget_callbacks(self)
        super().destroy()
