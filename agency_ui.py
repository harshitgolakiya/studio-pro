"""Client projects, brand kits, publishing adapters, plugins, and local API controls."""
from pathlib import Path
import json
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from studio_runtime import StagedOutput


def entry(parent, label, variable, password=False):
    ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", padx=12)
    ctk.CTkEntry(parent, textvariable=variable, show="*" if password else "").pack(fill="x", padx=12, pady=(0, 5))


class ProjectsPanel:
    def __init__(self, dialog, parent):
        from agency_projects import PRESETS
        self.dialog = dialog
        self.sources = []
        self.profile = {}
        self.profiles = []
        self.last_receipt = None
        body = ctk.CTkScrollableFrame(parent)
        body.pack(fill="both", expand=True)
        dialog._copy(body, "Save client projects and brand kits, apply social/web/print presets, and create named deliverables with a verified ZIP package. Naming supports {client}, {project}, {stem}, {preset}, {index}, {date}.")
        self.selected = tk.StringVar(master=parent)
        self.menu = ctk.CTkOptionMenu(body, variable=self.selected, values=["New project"], command=self.load_selected, width=400)
        self.menu.pack(anchor="w", padx=12, pady=5)
        self.variables = {key: tk.StringVar(master=parent, value=value) for key, value in
                          {"client": "", "project": "", "colors": "", "fonts": "", "logo": "",
                           "naming": "{client}-{project}-{stem}-{index}", "preset": "Web images", "export_set":"Single preset"}.items()}
        for key, label in (("client", "Client"), ("project", "Project"), ("colors", "Brand colors (#RRGGBB, comma separated)"),
                           ("fonts", "Brand font names (comma separated)"), ("logo", "Brand logo path"), ("naming", "Output naming template")):
            entry(body, label, self.variables[key])
        dialog._button(body, "Choose brand logo", self.choose_logo).pack(anchor="w", padx=12, pady=5)
        ctk.CTkOptionMenu(body, variable=self.variables["preset"], values=list(PRESETS), width=260).pack(anchor="w", padx=12, pady=5)
        from campaign_exports import EXPORT_SETS
        ctk.CTkLabel(body,text='Campaign export set',anchor='w').pack(fill='x',padx=12)
        ctk.CTkOptionMenu(body,variable=self.variables['export_set'],values=list(EXPORT_SETS),width=260).pack(anchor='w',padx=12,pady=5)
        dialog._copy(body,'Social sets export square, portrait and story images together. Mixed client handoff chooses web images, MP4 video, PDF documents or WAV audio by file type. Sources stay unchanged.')
        self.watermark = tk.BooleanVar(master=parent)
        self.package = tk.BooleanVar(master=parent, value=True)
        ctk.CTkCheckBox(body, text="Apply brand logo watermark to images", variable=self.watermark).pack(anchor="w", padx=12, pady=5)
        ctk.CTkCheckBox(body, text="Create delivery ZIP with checksums", variable=self.package).pack(anchor="w", padx=12, pady=5)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=5)
        for label, command in (("Save project", self.save), ("Import profile", self.import_profile), ("Export profile", self.export_profile)):
            dialog._button(row, label, command).pack(side="left", padx=(0, 5))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=5)
        for label, command in (("Choose files", self.choose_files), ("Choose folder", self.choose_folder), ("Preview exports", self.preview)):
            dialog._button(row, label, command).pack(side="left", padx=(0, 5))
        row=ctk.CTkFrame(body,fg_color='transparent');row.pack(fill='x',padx=12,pady=5)
        dialog._button(row,'Export campaign',self.run).pack(side='left',padx=(0,5))
        dialog._button(row,'Retry unfinished',self.retry).pack(side='left',padx=(0,5))
        dialog._button(row,'Resume export',self.resume).pack(side='left',padx=(0,5))
        dialog._button(body,'Review this export',self.review_export).pack(anchor='w',padx=12,pady=5)
        self.report = ctk.CTkLabel(body, text="No delivery inputs selected", wraplength=650, justify="left", anchor="w")
        self.report.pack(fill="x", padx=12, pady=8)
        self.refresh()

    def refresh(self):
        from agency_projects import list_profiles
        self.profiles = list_profiles()
        self.labels = {f"{p.get('client', '')} / {p['project']} ({p['id'][:6]})": (path, p) for path, p in self.profiles}
        self.menu.configure(values=["New project", *self.labels])

    def load_selected(self, label):
        self.profile = dict(self.labels[label][1]) if label in self.labels else {}
        for key, variable in self.variables.items():
            value = self.profile.get(key, "Single preset" if key=='export_set' else "Web images" if key == "preset" else "{client}-{project}-{stem}-{index}" if key == "naming" else "")
            variable.set(", ".join(value) if isinstance(value, list) else value)
        self.watermark.set(self.profile.get("watermark", False))

    def current(self):
        profile = dict(self.profile)
        profile.update({key: variable.get().strip() for key, variable in self.variables.items()})
        for key in ("colors", "fonts"):
            profile[key] = [v.strip() for v in profile[key].split(",") if v.strip()]
        profile["watermark"] = self.watermark.get()
        collector = getattr(self.dialog._master, "_collect_recipe_settings", None)
        if collector:
            profile["settings"] = collector()
        return profile

    def save(self):
        from agency_projects import save_profile, load_profile
        try:
            path = save_profile(self.current())
            self.profile = load_profile(path)
            self.refresh()
            self.dialog.status.set("Project and brand kit saved")
        except Exception as exc:
            self.dialog.status.set(str(exc))

    def choose_logo(self):
        name = filedialog.askopenfilename(parent=self.dialog, filetypes=[("Images", "*.png *.jpg *.webp")])
        if name:
            self.variables["logo"].set(name)

    def import_profile(self):
        from agency_projects import load_profile, save_profile
        name = filedialog.askopenfilename(parent=self.dialog, filetypes=[("Project profile", "*.json")])
        if name:
            try:
                profile = load_profile(Path(name))
                # Import as a new project to preserve any existing profile.
                profile.pop("id", None)
                save_profile(profile)
                self.refresh()
                self.dialog.status.set("Project imported")
            except Exception as exc:
                self.dialog.status.set(str(exc))

    def export_profile(self):
        from agency_projects import validate_profile
        try:
            profile = validate_profile(self.current())
            name = filedialog.asksaveasfilename(parent=self.dialog, defaultextension=".json", initialfile="agency-project.json")
            if name:
                with StagedOutput(Path(name)) as stage:
                    stage.path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
                self.dialog.status.set("Project profile exported")
        except Exception as exc:
            self.dialog.status.set(str(exc))

    def choose_files(self):
        names = filedialog.askopenfilenames(parent=self.dialog)
        if names:
            self.sources = [Path(p) for p in names]
            self.report.configure(text="\n".join(str(p) for p in self.sources))

    def choose_folder(self):
        name = filedialog.askdirectory(parent=self.dialog)
        if name:
            self.sources = [Path(name)]
            self.report.configure(text=name)

    def run(self):
        self._export()

    def review_export(self):
        if not self.last_receipt:
            self.dialog.status.set('Export a campaign first, or open Reviews to select an earlier export receipt.')
            return
        self.dialog.show_page('Reviews');self.dialog.panels['Reviews'].import_export(self.last_receipt)

    def preview(self):
        from campaign_exports import plan_exports
        try:
            jobs=plan_exports(self.current(),self.sources)
            text=f'{len(jobs)} exports · a new campaign folder will be created\n'
            text+='\n'.join(f"{Path(job['source']).name} → {job['relative_output']}" for job in jobs[:30])
            if len(jobs)>30:text+=f'\n… and {len(jobs)-30} more'
            self.report.configure(text=text)
        except Exception as exc:self.dialog.status.set(str(exc))

    def retry(self):
        if not self.last_receipt:
            self.dialog.status.set('Run a campaign first. Retry uses its receipt and skips completed exports.')
            return
        self._export(self.last_receipt)

    def resume(self):
        name=filedialog.askopenfilename(parent=self.dialog,title='Resume campaign export',filetypes=[('Campaign receipt','campaign-receipt.json')])
        if name:self._export(Path(name))

    def _export(self, receipt=None):
        from campaign_exports import run_campaign,plan_exports
        profile, sources, output, package = self.current(), list(self.sources), Path(self.dialog.output.get()), self.package.get()
        if not receipt and profile.get('export_set')=='Single preset' and profile.get('preset')=='Current queue settings':
            def legacy_work(progress):
                from agency_projects import run_project
                result=run_project(profile,sources,output,package,self.dialog._cancel.is_set,progress)
                self.dialog._bridge.post(lambda:self.report.configure(text=json.dumps(result.details,indent=2)))
                if not result.ok:raise RuntimeError('Some inputs failed. See the report.')
                return result.outputs[-1] if result.outputs else None
            self.dialog._run(legacy_work)
            return
        if not receipt:
            try:plan_exports(profile,sources)
            except Exception as exc:self.dialog.status.set(str(exc));return
        def work(progress):
            result = run_campaign(profile, sources, output, package, self.dialog._cancel.is_set, progress,retry_receipt=receipt)
            def show():
                self.last_receipt=Path(result.details['receipt'])
                message=f"{result.details['exported']}/{result.details['total']} exported · {result.details['status']}\n{result.details['folder']}"
                for failed in result.details['failures'][:8]:message+=f"\n{Path(failed['source']).name} · {failed['preset']}: {failed.get('error','Not started')}"
                if result.details.get('package_error'):message+='\nZIP: '+result.details['package_error']
                self.report.configure(text=message)
            self.dialog._bridge.post(show)
            if not result.ok:
                if result.details['status']=='cancelled':
                    from studio_runtime import StudioCancelled
                    raise StudioCancelled()
                raise RuntimeError('Some exports are unfinished. Completed files were kept; use Retry unfinished. See the report.')
            return Path(result.details['folder'])
        self.dialog._run(work)


class IntegrationsPanel:
    def __init__(self, dialog, parent):
        from workflow_hooks import get_hook_manager
        self.dialog = dialog
        self.source = tk.StringVar(master=parent)
        self.adapter = tk.StringVar(master=parent, value="Local web project")
        self.config = {}
        body = ctk.CTkScrollableFrame(parent)
        body.pack(fill="both", expand=True)
        dialog._copy(body, "Publish a selected output through an adapter. Cloud and WordPress operations use your credentials and run only when you click Publish. Local automation binds to this computer.")
        ctk.CTkOptionMenu(body, variable=self.adapter, values=["Local web project", "Cloud storage", "WordPress", "Design export folder", "Plugin exporter"], width=260, command=self.change_adapter).pack(anchor="w", padx=12, pady=5)
        self.fields = ctk.CTkFrame(body, fg_color="transparent")
        self.fields.pack(fill="x")
        entry(body, "File to publish", self.source)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=5)
        dialog._button(row, "Choose file", self.choose).pack(side="left", padx=(0, 8))
        dialog._button(row, "Publish", self.publish).pack(side="left")
        self.hooks = tk.BooleanVar(master=parent, value=get_hook_manager().enabled)
        ctk.CTkCheckBox(body, text="Enable conversion lifecycle hooks", variable=self.hooks,
                        command=lambda: setattr(get_hook_manager(), "enabled", self.hooks.get())).pack(anchor="w", padx=12, pady=8)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=5)
        dialog._button(row, "Load plugins", self.plugins).pack(side="left", padx=(0, 8))
        dialog._button(row, "Open hooks folder", self.open_hooks).pack(side="left")
        self.api_port = tk.StringVar(master=parent, value="17394")
        entry(body, "Local API port", self.api_port)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=5)
        dialog._button(row, "Start API", self.start_api).pack(side="left", padx=(0, 8))
        dialog._button(row, "Stop API", self.stop_api).pack(side="left")
        self.report = ctk.CTkTextbox(body, height=140)
        self.report.pack(fill="x", padx=12, pady=8)
        self.report.configure(state="disabled")
        self.change_adapter("Local web project")

    def change_adapter(self, name):
        for child in self.fields.winfo_children():
            child.destroy()
        self.config = {}
        fields = {
            "Local web project": [("project_root", "Project folder", ""), ("assets_dir", "Assets subfolder", "public/images"), ("base_url", "Asset URL prefix", "/images/")],
            "Cloud storage": [("provider", "Provider (s3, gcs, azure)", "s3"), ("bucket", "Bucket / container", ""), ("prefix", "Object prefix", "assets/"), ("region", "Region (optional)", "")],
            "WordPress": [("site_url", "Site URL", ""), ("username", "Username", ""), ("app_password", "Application password", "")],
            "Design export folder": [("output_dir", "Design output folder", ""), ("tool", "Design tool (figma, sketch, xd, generic)", "generic")],
            "Plugin exporter": [("name", "Loaded exporter name", "")],
        }[name]
        for key, label, default in fields:
            variable = tk.StringVar(master=self.fields, value=default)
            self.config[key] = variable
            entry(self.fields, label, variable, key == "app_password")

    def show(self, value):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", json.dumps(value, indent=2, default=str))
        self.report.configure(state="disabled")

    def choose(self):
        name = filedialog.askopenfilename(parent=self.dialog)
        if name:
            self.source.set(name)

    def publish(self):
        from agency_integrations import publish_file
        source, adapter = Path(self.source.get()), self.adapter.get()
        config = {k: v.get() for k, v in self.config.items()}
        def work(progress):
            result = publish_file(adapter, source, config)
            self.dialog._bridge.post(lambda: self.show(result))
            if result.get("status") != "published":
                raise RuntimeError(result.get("error", "Publishing failed"))
        self.dialog._run(work)

    def plugins(self):
        from agency_integrations import load_plugins
        def work(progress):
            result = load_plugins()
            self.dialog._bridge.post(lambda: self.show(result))
        self.dialog._run(work)

    def open_hooks(self):
        from settings import get_app_data_dir
        from utils import open_file_or_folder
        folder = get_app_data_dir() / "hooks"
        folder.mkdir(parents=True, exist_ok=True)
        open_file_or_folder(folder)

    def start_api(self):
        from automation_api import AutomationServer
        try:
            port = int(self.api_port.get())
            if not 1024 <= port <= 65535:
                raise ValueError("Choose a port between 1024 and 65535")
            if getattr(self.dialog, "_automation_server", None) and self.dialog._automation_server.is_running:
                self.show({"url": self.dialog._automation_server.base_url, "status": "Already running"})
                return
            server = AutomationServer(port=port)
            server.start()
            self.dialog._automation_server = server
            self.show({"url": server.base_url, "endpoints": ["/status", "/formats", "/studio/actions", "/studio/run", "/convert", "/batch"]})
        except Exception as exc:
            self.dialog.status.set(str(exc))

    def stop_api(self):
        server = getattr(self.dialog, "_automation_server", None)
        if server:
            server.stop()
        self.show({"status": "API stopped"})
