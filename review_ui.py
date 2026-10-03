"""Campaign review board with version history and approved-only delivery."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
import local_reviews as reviews
from design_system import ACCENT,ACCENT_HOVER,MUTED,SURFACE,TEXT


class ReviewsPanel:
    def __init__(self,dialog,parent):
        self.dialog=dialog;self.sources=[];self.path=None;self.data=None;self.asset_id=None;self.version_id=None
        parent.grid_columnconfigure(0,weight=1);parent.grid_rowconfigure(2,weight=1)
        header=ctk.CTkFrame(parent,fg_color='transparent');header.grid(row=0,column=0,sticky='ew',padx=12,pady=10)
        header.grid_columnconfigure(0,weight=1)
        self.menu=ctk.CTkOptionMenu(header,values=['Choose a campaign'],command=self.select_campaign,width=280)
        self.menu.grid(row=0,column=0,sticky='ew',columnspan=2,pady=(0,8))
        self.name=tk.StringVar(master=parent);self.client=tk.StringVar(master=parent);self.author=tk.StringVar(master=parent)
        ctk.CTkEntry(header,textvariable=self.name,placeholder_text='Campaign name').grid(row=1,column=0,sticky='ew',padx=(0,8))
        ctk.CTkEntry(header,textvariable=self.client,placeholder_text='Client (optional)').grid(row=1,column=1,sticky='ew')
        row=ctk.CTkFrame(header,fg_color='transparent');row.grid(row=2,column=0,columnspan=2,sticky='ew',pady=8)
        for label,command in [('Choose files',self.choose),('Create campaign',self.create),('Review export',self.choose_export)]:dialog._button(row,label,command,width=125).pack(side='left',padx=(0,6))
        self.summary=ctk.CTkLabel(parent,text='Select files or review a campaign export. Everything stays local.',anchor='w',text_color=MUTED)
        self.summary.grid(row=1,column=0,sticky='ew',padx=12,pady=(0,8))
        body=ctk.CTkFrame(parent,fg_color='transparent');body.grid(row=2,column=0,sticky='nsew',padx=12)
        body.grid_rowconfigure(0,weight=1);body.grid_columnconfigure(1,weight=1)
        self.files=ctk.CTkScrollableFrame(body,width=190);self.files.grid(row=0,column=0,sticky='ns',padx=(0,10))
        detail=ctk.CTkFrame(body,fg_color='transparent');detail.grid(row=0,column=1,sticky='nsew');detail.grid_columnconfigure(0,weight=1);detail.grid_rowconfigure(2,weight=1)
        self.version_menu=ctk.CTkOptionMenu(detail,values=['Select a file'],command=self.select_version)
        self.version_menu.grid(row=0,column=0,sticky='ew',pady=(0,6))
        row=ctk.CTkFrame(detail,fg_color='transparent');row.grid(row=1,column=0,sticky='ew',pady=(0,6))
        dialog._button(row,'Visual review',self.open_visual,width=120).pack(side='left',padx=(0,6))
        dialog._button(row,'Add revision',self.revise,width=120).pack(side='left')
        self.history=ctk.CTkTextbox(detail,wrap='word');self.history.grid(row=2,column=0,sticky='nsew');self.history.configure(state='disabled')
        ctk.CTkEntry(detail,textvariable=self.author,placeholder_text='Your reviewer name').grid(row=3,column=0,sticky='ew',pady=(8,6))
        self.comment=ctk.CTkTextbox(detail,height=70,wrap='word');self.comment.grid(row=4,column=0,sticky='ew')
        row=ctk.CTkFrame(detail,fg_color='transparent');row.grid(row=5,column=0,sticky='ew',pady=6)
        dialog._button(row,'Add comment',self.add_comment,width=120).pack(side='left')
        row=ctk.CTkFrame(detail,fg_color='transparent');row.grid(row=6,column=0,sticky='ew',pady=(0,6))
        self.state=tk.StringVar(master=parent,value='Draft')
        ctk.CTkOptionMenu(row,variable=self.state,values=list(reviews.STATUSES),width=130).pack(side='left',padx=6)
        dialog._button(row,'Set status',self.set_status,width=95).pack(side='left')
        self.package_button=dialog._button(parent,'Package approved versions',self.package,width=230)
        self.package_button.configure(fg_color=ACCENT,hover_color=ACCENT_HOVER,text_color='white')
        self.package_button.grid(row=3,column=0,sticky='w',padx=12,pady=12)
        self.refresh_menu()

    def refresh_menu(self):
        self.campaigns={f"{data['name']} · {data['id'][:6]}":path for path,data in reviews.list_reviews()}
        self.menu.configure(values=list(self.campaigns) or ['Choose a campaign'])
        if self.path:
            label=next((name for name,path in self.campaigns.items() if path==self.path),None)
            if label:self.menu.set(label)

    def _read(self):
        data=reviews.load_review(self.path)
        statuses={v['id']:reviews.version_status(self.path,v) for a in data['assets'] for v in a['versions']}
        return data,statuses

    def _task(self,action,select_new=False,comment_text=None):
        def work(progress):
            try:output=action()
            except Exception:
                if self.path:
                    try:
                        data,statuses=self._read()
                        self.dialog._bridge.post(lambda data=data,statuses=statuses:self.paint(data,statuses))
                    except Exception:pass
                raise
            data,statuses=self._read()
            def paint():
                if select_new:self.version_id=None
                if comment_text is not None and self.comment.get('1.0','end').strip()==comment_text:self.comment.delete('1.0','end')
                self.refresh_menu();self.paint(data,statuses)
            self.dialog._bridge.post(paint)
            return output if isinstance(output,Path) and output.suffix=='.zip' else None
        self.dialog._run(work)

    def select_campaign(self,label):
        if self.dialog._busy or label not in self.campaigns:return
        self.path=self.campaigns[label];self.asset_id=None;self.version_id=None
        self._task(lambda:None)

    def choose(self):
        names=filedialog.askopenfilenames(parent=self.dialog,title='Choose campaign files')
        if names:self.sources=[Path(p) for p in names];self.summary.configure(text=f'{len(names)} files selected · create a campaign to start reviewing')

    def create(self):
        name,client,sources=self.name.get(),self.client.get(),list(self.sources)
        def action():
            self.path=reviews.create_review(name,sources,client,cancel_check=self.dialog._cancel.is_set)
            self.asset_id=None;self.version_id=None
        self._task(action)

    def choose_export(self):
        name=filedialog.askopenfilename(parent=self.dialog,title='Review campaign export',filetypes=[('Campaign receipt','campaign-receipt.json')])
        if name:self.import_export(Path(name))

    def import_export(self,path):
        def action():
            self.path=reviews.review_export(path,cancel_check=self.dialog._cancel.is_set);self.asset_id=None;self.version_id=None
        self._task(action)

    def paint(self,data,statuses):
        self.data=data;self.statuses=statuses
        self.name.set(data['name']);self.client.set(data['client'])
        current=[statuses[a['versions'][-1]['id']] for a in data['assets']]
        self.summary.configure(text=' · '.join(f'{current.count(status)} {status.lower()}' for status in (*reviews.STATUSES,'Changed','Missing') if current.count(status)))
        for child in self.files.winfo_children():child.destroy()
        for asset in data['assets']:
            status=statuses[asset['versions'][-1]['id']]
            name=asset['name'] if len(asset['name'])<25 else asset['name'][:22]+'…'
            ctk.CTkButton(self.files,text=f"{name}\n{status} · v{len(asset['versions'])}",anchor='w',height=55,fg_color=SURFACE,text_color=TEXT,command=lambda identifier=asset['id']:self.select_asset(identifier)).pack(fill='x',pady=4)
        if self.asset_id not in {a['id'] for a in data['assets']}:self.asset_id=data['assets'][0]['id']
        self.select_asset(self.asset_id,keep_version=True)

    def select_asset(self,identifier,keep_version=False):
        if self.dialog._busy and not keep_version:return
        self.asset_id=identifier;asset=next(a for a in self.data['assets'] if a['id']==identifier)
        self.versions={f"v{index} · {self.statuses[v['id']]} · {v['created'][:10]}":v for index,v in enumerate(asset['versions'],1)}
        if not keep_version or self.version_id not in {v['id'] for v in asset['versions']}:self.version_id=asset['versions'][-1]['id']
        self.version_menu.configure(values=list(self.versions));label=next(label for label,v in self.versions.items() if v['id']==self.version_id)
        self.version_menu.set(label);self.select_version(label)

    def select_version(self,label):
        if label not in getattr(self,'versions',{}):return
        version=self.versions[label];self.version_id=version['id'];self.state.set(version['status'])
        from datetime import datetime
        def date(value):return datetime.fromisoformat(value).astimezone().strftime('%d %b %Y, %H:%M %Z')
        text=f"{version['name']}\n{self.statuses[version['id']]} · {date(version['created'])}\n"
        for decision in version['decisions']:text+=f"\n{decision['author']} · {decision['status']} · {date(decision['created'])}"
        for comment in version['comments']:
            location=f" · page {comment['anchor']['page']}" if comment.get('anchor') else ''
            text+=f"\n\n{comment['author']}{location} · {date(comment['created'])}\n{comment['text']}"
        if not version['comments']:text+='\n\nNo comments on this version.'
        self.history.configure(state='normal');self.history.delete('1.0','end');self.history.insert('1.0',text);self.history.configure(state='disabled')

    def _selection(self):
        if not self.path or not self.asset_id:raise ValueError('Select a review campaign and a file first')
        return self.path,self.asset_id,self.version_id

    def add_comment(self):
        try:path,asset,version=self._selection()
        except ValueError as exc:self.dialog.status.set(str(exc));return
        author,text=self.author.get(),self.comment.get('1.0','end').strip()
        self._task(lambda:reviews.add_comment(path,asset,version,author,text),comment_text=text)

    def set_status(self):
        try:path,asset,version=self._selection()
        except ValueError as exc:self.dialog.status.set(str(exc));return
        author,status=self.author.get(),self.state.get()
        self._task(lambda:reviews.decide(path,asset,version,author,status))

    def revise(self):
        try:path,asset,_=self._selection()
        except ValueError as exc:self.dialog.status.set(str(exc));return
        name=filedialog.askopenfilename(parent=self.dialog,title='Add a new revision')
        if name:self._task(lambda:reviews.add_revision(path,asset,Path(name)),select_new=True)

    def open_version(self):
        try:
            path,asset,version=self._selection();_,selected=reviews.find_version(self.data,asset,version)
            source=path.parent/selected['path']
            from doc_converter import SUPPORTED_DOCUMENT_EXTENSIONS
            from converter import SUPPORTED_EXTENSIONS
            if source.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS:
                from document_preview import DocumentPreviewDialog
                DocumentPreviewDialog(self.dialog,source);return
            if source.suffix.lower() in SUPPORTED_EXTENSIONS:
                from preview_modal import ImagePreviewDialog
                ImagePreviewDialog(self.dialog,source);return
            from media_engine import SUPPORTED_AUDIO_EXTENSIONS,SUPPORTED_VIDEO_EXTENSIONS
            from utils import open_file_or_folder
            open_file_or_folder(source if source.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS|SUPPORTED_VIDEO_EXTENSIONS else source.parent)
        except Exception as exc:self.dialog.status.set(str(exc))

    def open_visual(self):
        try:
            path,asset,version=self._selection();_,selected=reviews.find_version(self.data,asset,version)
            from office_engine import OFFICE_EXTENSIONS
            from converter import SUPPORTED_EXTENSIONS
            if Path(selected['name']).suffix.lower() not in OFFICE_EXTENSIONS|SUPPORTED_EXTENSIONS|{'.pdf'}:self.open_version();return
            from visual_review_ui import VisualReviewDialog
            def changed():
                if self.dialog.winfo_exists() and not self.dialog._busy:self._task(lambda:None)
            self.visual=VisualReviewDialog(self.dialog,path,asset,version,self.author.get(),changed)
        except Exception as exc:self.dialog.status.set(str(exc))

    def package(self):
        if not self.path:self.dialog.status.set('Select a campaign first');return
        path=self.path;destination=Path(self.dialog.output.get())/'approved-delivery.zip'
        self._task(lambda:reviews.package_approved(path,destination,self.dialog._cancel.is_set))
