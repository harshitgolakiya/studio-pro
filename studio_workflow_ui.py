"""Forms for advanced tools and explicit local model management."""
from pathlib import Path
import json
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from studio_actions import run_action
from studio_workflows import WORKFLOWS


class WorkflowPanel:
    def __init__(self, dialog, parent):
        self.dialog = dialog
        self.sources = []
        self.variables = {}
        self.group = tk.StringVar(master=parent, value="PDF")
        self.action = tk.StringVar(master=parent)
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)
        ctk.CTkOptionMenu(row, variable=self.group, values=list(dict.fromkeys(d[0] for d in WORKFLOWS.values())), command=self.change_group).pack(side="left", padx=(0, 12))
        self.menu = ctk.CTkOptionMenu(row, variable=self.action, width=300, command=self.change_action)
        self.menu.pack(side="left")
        self.body = ctk.CTkScrollableFrame(parent)
        self.body.pack(fill="both", expand=True, padx=12)
        self.inputs = ctk.CTkLabel(self.body, text="No inputs selected", wraplength=650, anchor="w")
        self.inputs.pack(fill="x", padx=10, pady=5)
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=5)
        dialog._button(row, "Choose files", self.choose_files).pack(side="left", padx=10)
        dialog._button(row, "Choose folder", self.choose_folder).pack(side="left")
        self.fields = ctk.CTkFrame(self.body, fg_color="transparent")
        self.fields.pack(fill="x")
        dialog._button(self.body, "Run action", self.run).pack(anchor="w", padx=10, pady=10)
        self.report = ctk.CTkTextbox(self.body, height=160)
        self.report.pack(fill="x", padx=10, pady=8)
        self.report.configure(state="disabled")
        self.change_group("PDF")

    def change_group(self, group):
        values = [d[1] for d in WORKFLOWS.values() if d[0] == group]
        self.menu.configure(values=values)
        self.action.set(values[0])
        self.change_action(values[0])

    def change_action(self, label):
        for child in self.fields.winfo_children():
            child.destroy()
        self.variables = {}
        action = next(k for k, d in WORKFLOWS.items() if d[1] == label)
        notes = {
            "pdf-redact": "Redacted pages are flattened. Regions use PDF points from the top-left: [page,left,top,right,bottom].",
            "pdf-identity": "Creates a self-signed identity. Readers will show it as untrusted unless the recipient trusts the certificate. No input is required.",
            "print-import": "EPS and PostScript AI use Ghostscript. PDF-compatible AI preserves its PDF pages. INDD uses installed InDesign or a matching PDF sidecar; export PDF from InDesign for reliable layout.",
            "print-cmyk": "PDF delivery converts through Ghostscript; images use the selected ICC press profile. Inspect the result before print delivery.",
        }
        if action in notes:
            self.dialog._copy(self.fields, notes[action])
        for field in WORKFLOWS[action][2]:
            row = ctk.CTkFrame(self.fields, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=5)
            if field.kind == "bool":
                variable = tk.BooleanVar(master=row, value=field.default)
                ctk.CTkCheckBox(row, text=field.label, variable=variable).pack(anchor="w")
            else:
                ctk.CTkLabel(row, text=field.label, anchor="w", wraplength=600).pack(fill="x")
                variable = tk.StringVar(master=row, value=str(field.default))
                if field.kind in {"json", "lines"}:
                    widget = ctk.CTkTextbox(row, height=70)
                    widget.pack(fill="x")
                    widget.insert("1.0", str(field.default))
                    variable = widget
                elif field.choices:
                    ctk.CTkOptionMenu(row, variable=variable, values=list(field.choices), width=260).pack(anchor="w")
                else:
                    ctk.CTkEntry(row, textvariable=variable, show="*" if field.kind == "password" else "").pack(side="left", fill="x", expand=True)
                    if field.kind in {"file", "folder"}:
                        ctk.CTkButton(row, text="Browse", width=85,
                                      command=lambda v=variable, kind=field.kind: self.browse(v, kind)).pack(side="right", padx=5)
            self.variables[field.key] = variable

    def browse(self, variable, kind):
        value = filedialog.askdirectory(parent=self.dialog) if kind == "folder" else filedialog.askopenfilename(parent=self.dialog)
        if value:
            variable.set(value)

    def choose_files(self):
        names = filedialog.askopenfilenames(parent=self.dialog)
        if names:
            self.sources = [Path(p) for p in names]
            self.inputs.configure(text="\n".join(str(p) for p in self.sources))

    def choose_folder(self):
        name = filedialog.askdirectory(parent=self.dialog)
        if name:
            self.sources = [Path(name)]
            self.inputs.configure(text=name)

    def show_report(self, result):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", json.dumps({"ok": result.ok, "outputs": [str(p) for p in result.outputs], **result.details}, indent=2, ensure_ascii=False, default=str))
        self.report.configure(state="disabled")

    def run(self):
        action = next(k for k, d in WORKFLOWS.items() if d[1] == self.action.get())
        options = {k: v.get("1.0", "end-1c") if isinstance(v, ctk.CTkTextbox) else v.get() for k, v in self.variables.items()}
        sources, output = list(self.sources), Path(self.dialog.output.get())
        def work(progress):
            result = run_action(action, sources, output, options=options,
                                cancel_check=self.dialog._cancel.is_set, progress=progress)
            self.dialog._bridge.post(lambda: self.show_report(result))
            if not result.ok:
                raise RuntimeError("The checks found problems. See the report and saved JSON for details.")
            return result.outputs[0] if result.outputs else None
        self.dialog._run(work)


class ModelsPanel:
    def __init__(self, dialog, parent):
        from model_catalog import catalog
        self.dialog = dialog
        self.entries = catalog()
        self.selection = tk.StringVar(master=parent, value=self.entries[0].key)
        dialog._copy(parent, "Install local models for multilingual speech, voices, OCR scripts, translation, speaker labels, isolation, and print color. Downloads happen only when you click Install. Conversion stays offline.")
        ctk.CTkOptionMenu(parent, variable=self.selection, values=[e.key for e in self.entries], width=430, command=lambda _: self.refresh()).pack(anchor="w", padx=14, pady=10)
        self.details = ctk.CTkLabel(parent, wraplength=650, anchor="w", justify="left")
        self.details.pack(fill="x", padx=14, pady=8)
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14)
        dialog._button(row, "Install selected", self.install).pack(side="left", padx=(0, 10))
        dialog._button(row, "Remove selected", self.remove).pack(side="left", padx=(0, 10))
        dialog._button(row, "Refresh", self.refresh).pack(side="left")
        self.refresh()

    def refresh(self):
        from model_catalog import find_entry, is_installed, installed_bytes, entry_path
        entry = find_entry(self.selection.get())
        self.details.configure(text=f"{entry.label}\nLanguages: {entry.language}\nDownload: about {entry.size_mb} MB\n"
                               f"{'Installed' if is_installed(entry) else 'Available'} ({installed_bytes(entry) / 1024**2:.1f} MB on disk)\n{entry_path(entry)}")

    def install(self):
        from model_catalog import find_entry, install
        entry = find_entry(self.selection.get())
        def work(progress):
            path = install(entry, progress, self.dialog._cancel.is_set)
            self.dialog._bridge.post(self.refresh)
            return path
        self.dialog._run(work)

    def remove(self):
        from model_catalog import find_entry, remove
        entry = find_entry(self.selection.get())
        def work(progress):
            remove(entry)
            self.dialog._bridge.post(self.refresh)
        self.dialog._run(work)
