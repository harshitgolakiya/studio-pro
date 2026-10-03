"""OCR, data, and delivery controls hosted by StudioToolsDialog."""
from pathlib import Path
import json
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from studio_actions import ACTION_LABELS, run_action


def build_expansion_tabs(dialog, parent):
    from studio_workflow_ui import WorkflowPanel, ModelsPanel
    navigation = ctk.CTkFrame(parent, fg_color="transparent")
    navigation.pack(fill="x", padx=12, pady=5)
    content = ctk.CTkFrame(parent, fg_color="transparent")
    content.pack(fill="both", expand=True)
    panels = {}
    def show(title):
        for panel in panels.values():
            panel.pack_forget()
        panels[title].pack(fill="both", expand=True)
    def add(title):
        panel = ctk.CTkFrame(content, fg_color="transparent")
        panels[title] = panel
        return panel
    for title, actions, formats in (
        ("OCR", ["ocr"], ["TXT", "MD", "JSON", "PDF"]),
        ("Data", ["data-convert", "data-clean", "data-export-sheets"],
         ["CSV", "TSV", "JSON", "JSONL", "XML", "YAML", "XLSX"]),
        ("Archives & Delivery", ["archive-create", "archive-extract", "delivery-create", "delivery-verify"],
         ["ZIP", "7Z", "TAR", "TAR.GZ", "TAR.XZ"]),
    ):
        ExpansionPanel(dialog, add(title), title, actions, formats)
    WorkflowPanel(dialog, add("Advanced workflows"))
    ModelsPanel(dialog, add("Models"))
    from agency_ui import ProjectsPanel, IntegrationsPanel
    ProjectsPanel(dialog, add("Projects & Brand kits"))
    IntegrationsPanel(dialog, add("Integrations & API"))
    ctk.CTkOptionMenu(navigation, values=list(panels), command=show, width=280).pack(anchor="w")
    show("OCR")


def build_expansion_pages(dialog, tabs):
    """Expose each section directly instead of hiding them in More Tools."""
    from studio_workflow_ui import WorkflowPanel, ModelsPanel
    from agency_ui import ProjectsPanel, IntegrationsPanel
    panels = {}
    for title, actions, formats in (
        ("OCR", ["ocr"], ["TXT", "MD", "JSON", "PDF"]),
        ("Data", ["data-convert", "data-clean", "data-export-sheets"], ["CSV", "TSV", "JSON", "JSONL", "XML", "YAML", "XLSX"]),
        ("Archives", ["archive-create", "archive-extract", "delivery-create", "delivery-verify"], ["ZIP", "7Z", "TAR", "TAR.GZ", "TAR.XZ"]),
    ):
        panel_title = "Archives & Delivery" if title == "Archives" else title
        panels[title] = ExpansionPanel(dialog, tabs.add(title), panel_title, actions, formats)
    for title, cls in (("Advanced workflows", WorkflowPanel), ("Models", ModelsPanel),
                       ("Projects", ProjectsPanel), ("Integrations", IntegrationsPanel)):
        panels[title] = cls(dialog, tabs.add(title))
    return panels


class ExpansionPanel:
    def __init__(self, dialog, tab, title, actions, formats):
        self.dialog = dialog
        self.title = title
        self.sources = []
        self.action = tk.StringVar(master=tab, value=ACTION_LABELS[actions[0]])
        self.format = tk.StringVar(master=tab, value=formats[0])
        self.sheet = tk.StringVar(master=tab)
        self.pages = tk.StringVar(master=tab, value="all")
        self.dpi = tk.StringVar(master=tab, value="200")
        self.force = tk.BooleanVar(master=tab)
        self.duplicates = tk.BooleanVar(master=tab)
        self.headers = tk.BooleanVar(master=tab)
        self.client = tk.StringVar(master=tab)
        self.project = tk.StringVar(master=tab)
        self.password = tk.StringVar(master=tab)
        body = ctk.CTkScrollableFrame(tab)
        body.pack(fill="both", expand=True)
        description = {
            "OCR": "Extract text from scans/screenshots or create a searchable PDF. Extra scripts need local OCR models.",
            "Data": "Convert structured data, clean rows, or export every XLSX/XLSM sheet. Originals are kept.",
            "Archives & Delivery": "Pack files or folders, safely extract archives, or create and verify delivery packages with SHA-256 checksums.",
        }[title]
        dialog._copy(body, description)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        dialog._button(row, "Choose files", self.choose_files).pack(side="left", padx=(0, 8))
        if title == "Archives & Delivery":
            dialog._button(row, "Choose folder", self.choose_folder).pack(side="left")
        self.selection = ctk.CTkLabel(body, text="No inputs selected", anchor="w", wraplength=620)
        self.selection.pack(fill="x", padx=14, pady=6)
        ctk.CTkOptionMenu(body, variable=self.action, values=[ACTION_LABELS[a] for a in actions], width=300).pack(anchor="w", padx=14, pady=6)
        self.entry(body, "Output format", self.format, formats)
        if title == "OCR":
            from ocr_engine import OCR_LANGUAGES, DEFAULT_OCR_LANGUAGE
            self.language = tk.StringVar(master=tab, value=DEFAULT_OCR_LANGUAGE)
            self.entry(body, "OCR script", self.language, list(OCR_LANGUAGES))
            self.entry(body, "PDF pages (all or 1,3-5)", self.pages)
            self.entry(body, "Resolution (72-600 DPI)", self.dpi)
            ctk.CTkCheckBox(body, text="Recognize pages that already contain text", variable=self.force).pack(anchor="w", padx=14, pady=6)
        elif title == "Data":
            self.entry(body, "Sheet (empty = first; every-sheet export ignores this)", self.sheet)
            ctk.CTkCheckBox(body, text="Cleanup: remove duplicate rows", variable=self.duplicates).pack(anchor="w", padx=14, pady=6)
            ctk.CTkCheckBox(body, text="Cleanup: normalize column names", variable=self.headers).pack(anchor="w", padx=14, pady=6)
        else:
            self.entry(body, "Delivery client", self.client)
            self.entry(body, "Delivery project", self.project)
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=5)
            ctk.CTkLabel(row, text="Archive password (7Z creation)").pack(side="left")
            ctk.CTkEntry(row, textvariable=self.password, show="*").pack(side="right")
            dialog._copy(body, "Output format applies to package creation. Extraction and verification read the selected archive's format. Select one archive for those actions.")
        dialog._button(body, "Run tool", self.run).pack(anchor="w", padx=14, pady=10)
        self.report = ctk.CTkTextbox(body, height=110, wrap="word")
        self.report.pack(fill="x", padx=14, pady=6)
        self.report.configure(state="disabled")

    def entry(self, parent, label, variable, choices=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(row, text=label, anchor="w").pack(side="left", padx=(0, 12))
        widget = ctk.CTkOptionMenu(row, variable=variable, values=choices, width=230) if choices else ctk.CTkEntry(row, textvariable=variable, width=200)
        widget.pack(side="right")

    def choose_files(self):
        patterns = {"OCR": "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.gif",
                    "Data": "*.csv *.tsv *.json *.jsonl *.ndjson *.xml *.yaml *.yml *.xlsx *.xlsm",
                    "Archives & Delivery": "*.*"}
        names = filedialog.askopenfilenames(parent=self.dialog, title="Choose inputs", filetypes=[("Inputs", patterns[self.title]), ("All files", "*.*")])
        if names:
            self.select([Path(name) for name in names])

    def choose_folder(self):
        name = filedialog.askdirectory(parent=self.dialog, title="Choose folder to package")
        if name:
            self.select([Path(name)])

    def select(self, paths):
        self.sources = paths
        self.selection.configure(text="\n".join(str(p) for p in paths))

    def show_report(self, result):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", "\n".join(str(p) for p in result.outputs) +
                           ("\n" + json.dumps(result.details, indent=2, ensure_ascii=False) if result.details else ""))
        self.report.configure(state="disabled")

    def run(self):
        action = next(key for key, label in ACTION_LABELS.items() if label == self.action.get())
        if not self.sources or not self.dialog.output.get().strip():
            self.dialog.status.set("Select inputs and an output folder first.")
            return
        try:
            options = dict(fmt=self.format.get(), sheet=self.sheet.get().strip() or None,
                           pages=self.pages.get(), dpi=int(self.dpi.get()), force=self.force.get(),
                           drop_duplicates=self.duplicates.get(), normalize_headers=self.headers.get(),
                           client=self.client.get(), project=self.project.get())
            if self.title == "Archives & Delivery":
                options["options"] = {"password": self.password.get()}
            if self.title == "OCR":
                options["language"] = self.language.get()
        except ValueError:
            self.dialog.status.set("Enter OCR resolution as a whole number.")
            return
        sources, output = list(self.sources), Path(self.dialog.output.get())
        def work(progress):
            result = run_action(action, sources, output, cancel_check=self.dialog._cancel.is_set,
                                progress=progress, **options)
            self.dialog._bridge.post(lambda: self.show_report(result))
            if not result.ok:
                raise RuntimeError("Package verification failed. See the report for changed or missing files.")
            if not result.outputs:
                progress("Package verification passed.")
                return None
            return result.outputs[0]
        self.dialog._run(work)
