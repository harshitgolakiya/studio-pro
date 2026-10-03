"""Wide visual review workspace with page pins and side-by-side revisions."""
from pathlib import Path
import threading
import tkinter as tk
import customtkinter as ctk
from PIL import ImageTk,Image
import local_reviews as reviews
from visual_pages import load_visual,visual_page,fitted_rect,normalized_point
from ui_dispatch import TkEventBridge,cancel_widget_callbacks
from design_system import style_dialog,ACCENT,ACCENT_HOVER,MUTED


class VisualReviewDialog(ctk.CTkToplevel):
    def __init__(self,master,path,asset_id,version_id,author='',on_changed=None):
        super().__init__(master);style_dialog(self,master)
        self.title('Shadow — Visual review');self.geometry('1240x780');self.minsize(940,640)
        self.path=Path(path);self.asset_id=asset_id;self.current=version_id;self.on_changed=on_changed
        self.cancel=threading.Event();self.bridge=TkEventBridge(self);self._generation=0;self._busy=False;self._closed=False
        self._documents={};self._page_cache={};self._images=[None,None];self._photos=[None,None];self._rects=[None,None]
        self.page=0;self.anchor=None;self.comparison=None;self._resize_job=None
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(1,weight=1)
        header=ctk.CTkFrame(self,fg_color='transparent');header.grid(row=0,column=0,columnspan=2,sticky='ew',padx=20,pady=14)
        ctk.CTkLabel(header,text='Visual review',font=ctk.CTkFont(size=24,weight='bold')).pack(side='left',padx=(0,20))
        self.version_menu=ctk.CTkOptionMenu(header,command=self.choose_version,width=180);self.version_menu.pack(side='left',padx=6)
        self.compare_menu=ctk.CTkOptionMenu(header,command=self.choose_compare,width=200);self.compare_menu.pack(side='left',padx=6)
        self.zoom=tk.StringVar(master=self,value='Fit')
        ctk.CTkOptionMenu(header,variable=self.zoom,values=['Fit','100%','150%','200%'],width=90,command=lambda value:self.reset_view()).pack(side='left',padx=6)
        self.viewer=ctk.CTkFrame(self);self.viewer.grid(row=1,column=0,sticky='nsew',padx=(20,10));self.viewer.grid_rowconfigure(1,weight=1);self.viewer.grid_columnconfigure((0,1),weight=1,uniform='versions')
        self.labels=[];self.canvases=[];self.panes=[]
        for column in range(2):
            label=ctk.CTkLabel(self.viewer,text='',anchor='w');label.grid(row=0,column=column,sticky='ew',padx=12,pady=8);self.labels.append(label)
            pane=ctk.CTkFrame(self.viewer,fg_color='transparent');pane.grid(row=1,column=column,sticky='nsew',padx=8,pady=(0,8));pane.grid_columnconfigure(0,weight=1);pane.grid_rowconfigure(0,weight=1);self.panes.append(pane)
            canvas=tk.Canvas(pane,background='#18181F',highlightthickness=0);canvas.grid(row=0,column=0,sticky='nsew')
            vertical=ctk.CTkScrollbar(pane,orientation='vertical',command=canvas.yview);vertical.grid(row=0,column=1,sticky='ns')
            horizontal=ctk.CTkScrollbar(pane,orientation='horizontal',command=canvas.xview);horizontal.grid(row=1,column=0,sticky='ew')
            canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
            canvas.bind('<MouseWheel>',lambda event,c=canvas:self.wheel(event,c))
            canvas.bind('<Configure>',self.schedule_draw);self.canvases.append(canvas)
        self.canvases[0].bind('<Button-1>',self.pin)
        sidebar=ctk.CTkFrame(self,width=280);sidebar.grid(row=1,column=1,sticky='nsew',padx=(0,20));sidebar.grid_columnconfigure(0,weight=1);sidebar.grid_rowconfigure(1,weight=1)
        ctk.CTkLabel(sidebar,text='Feedback on selected version',anchor='w',font=ctk.CTkFont(weight='bold')).grid(row=0,column=0,sticky='ew',padx=12,pady=12)
        self.comments=ctk.CTkScrollableFrame(sidebar,width=270);self.comments.grid(row=1,column=0,sticky='nsew',padx=8)
        self.author=tk.StringVar(master=self,value=author)
        ctk.CTkEntry(sidebar,textvariable=self.author,placeholder_text='Your reviewer name').grid(row=2,column=0,sticky='ew',padx=12,pady=(10,6))
        self.text=ctk.CTkTextbox(sidebar,height=100,wrap='word');self.text.grid(row=3,column=0,sticky='ew',padx=12)
        self.location=ctk.CTkLabel(sidebar,text='Click the preview to pin feedback.',text_color=MUTED,wraplength=260);self.location.grid(row=4,column=0,padx=12,pady=6)
        ctk.CTkButton(sidebar,text='Clear pin',height=24,width=90,command=self.clear_pin).grid(row=5,column=0,sticky='w',padx=12,pady=(0,6))
        self.add_button=ctk.CTkButton(sidebar,text='Add comment',fg_color=ACCENT,hover_color=ACCENT_HOVER,command=self.add_comment);self.add_button.grid(row=6,column=0,sticky='ew',padx=12,pady=(0,12))
        footer=ctk.CTkFrame(self,fg_color='transparent');footer.grid(row=2,column=0,columnspan=2,sticky='ew',padx=20,pady=12)
        self.previous=ctk.CTkButton(footer,text='Previous',width=90,command=lambda:self.navigate(-1));self.previous.pack(side='left')
        self.page_label=ctk.CTkLabel(footer,text='');self.page_label.pack(side='left',padx=12)
        self.next=ctk.CTkButton(footer,text='Next',width=90,command=lambda:self.navigate(1));self.next.pack(side='left')
        self.status=ctk.CTkLabel(footer,text='Loading preview…',anchor='w');self.status.pack(side='left',padx=18)
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        self.reload_data();self.load_pages()

    def reload_data(self):
        self.data=reviews.load_review(self.path);self.asset,_=reviews.find_version(self.data,self.asset_id,self.current)
        self.versions={f"v{index} · {version['status']}":version for index,version in enumerate(self.asset['versions'],1)}
        self.version_menu.configure(values=list(self.versions));self.version_menu.set(next(label for label,v in self.versions.items() if v['id']==self.current))
        self.compare_options={'No comparison':None,**{f'Compare {label}':v['id'] for label,v in self.versions.items() if v['id']!=self.current}}
        self.compare_menu.configure(values=list(self.compare_options));self.compare_menu.set(next((label for label,identifier in self.compare_options.items() if identifier==self.comparison),'No comparison'))
        self.paint_comments()

    def choose_version(self,label):
        if self._busy:return
        self.current=self.versions[label]['id'];self.page=0;self.anchor=None;self.location.configure(text='Click the preview to pin feedback.')
        if self.current==self.comparison:self.comparison=None
        self.reload_data();self.load_pages()

    def choose_compare(self,label):
        if self._busy:return
        self.comparison=self.compare_options[label];self.load_pages()

    def load_pages(self):
        self._generation+=1;generation=self._generation;page=self.page;identifiers=[self.current,self.comparison]
        self.previous.configure(state='disabled');self.next.configure(state='disabled');self.status.configure(text='Loading preview…')
        self._images=[None,None];self._rects=[None,None]
        for canvas in self.canvases:canvas.delete('all')
        if self.comparison:self.panes[1].grid();self.labels[1].grid();self.viewer.grid_columnconfigure(1,weight=1)
        else:self.panes[1].grid_remove();self.labels[1].grid_remove();self.viewer.grid_columnconfigure(1,weight=0)
        def work():
            documents={};images=[];errors=[]
            for identifier in identifiers:
                if not identifier:images.append(None);continue
                _,version=reviews.find_version(self.data,self.asset_id,identifier)
                try:
                    if reviews.version_status(self.path,version) in {'Changed','Missing'}:raise ValueError('Snapshot changed or missing. Add a revision before reviewing.')
                    document=self._documents.get(identifier) or load_visual(self.path.parent/version['path'],self.cancel.is_set)
                    documents[identifier]=document;key=(identifier,page)
                    image=self._page_cache.get(key)
                    if image is None:image=visual_page(document,page)
                    if reviews.version_status(self.path,version) in {'Changed','Missing'}:raise ValueError('Snapshot changed while loading. Add a revision before reviewing.')
                    images.append(image)
                except Exception as exc:images.append(None);errors.append(str(exc))
            def finish():
                if generation!=self._generation:return
                self._documents.update(documents);self._images=images
                while len(self._documents)>4:self._documents.pop(next(key for key in self._documents if key not in identifiers))
                for identifier,image in zip(identifiers,images):
                    if identifier and image:self._page_cache[(identifier,page)]=image
                while len(self._page_cache)>12:self._page_cache.pop(next(iter(self._page_cache)))
                count=max((doc['count'] for doc in documents.values()),default=1);self._count=count
                self.previous.configure(state='normal' if page>0 else 'disabled');self.next.configure(state='normal' if page+1<count else 'disabled')
                self.page_label.configure(text=f'Page / slide {page+1} of {count}')
                self.status.configure(text=errors[0][:100] if errors else 'Read-only · click the left preview to place a pin')
                self.location.configure(text='Click the preview to pin feedback.' if self.anchor is None else self.location.cget('text'))
                self.reset_view()
            self.bridge.post(finish)
        threading.Thread(target=work,daemon=True).start()

    def navigate(self,delta):
        target=self.page+delta
        if 0<=target<getattr(self,'_count',1):self.page=target;self.anchor=None;self.load_pages()

    def schedule_draw(self,event=None):
        if self._resize_job:self.after_cancel(self._resize_job)
        self._resize_job=self.after(40,self.draw)

    def draw(self):
        self._resize_job=None
        for index,(canvas,image,identifier) in enumerate(zip(self.canvases,self._images,[self.current,self.comparison])):
            canvas.delete('all');self._rects[index]=None
            if not identifier:continue
            label=next(label for label,v in self.versions.items() if v['id']==identifier);self.labels[index].configure(text=label)
            if image is None:canvas.create_text(max(1,canvas.winfo_width())/2,max(1,canvas.winfo_height())/2,text='Preview unavailable for this page.',fill='#AAA7B8');continue
            if self.zoom.get()=='Fit':rect=fitted_rect(image.size,canvas.winfo_width(),canvas.winfo_height())
            else:
                factor=float(self.zoom.get().rstrip('%'))/100
                width,height=image.width*factor,image.height*factor
                rect=(max(16,(canvas.winfo_width()-width)/2),max(16,(canvas.winfo_height()-height)/2),width,height)
            self._rects[index]=rect
            left,top,width,height=rect
            canvas.configure(scrollregion=(0,0,max(canvas.winfo_width(),left+width+16),max(canvas.winfo_height(),top+height+16)))
            self._photos[index]=ImageTk.PhotoImage(image.resize((max(1,int(width)),max(1,int(height))),Image.Resampling.LANCZOS))
            canvas.create_image(left,top,image=self._photos[index],anchor='nw')
            _,version=reviews.find_version(self.data,self.asset_id,identifier)
            for number,comment in enumerate(version['comments'],1):
                point=comment.get('anchor')
                if point and point['page']==self.page+1:
                    x,y=left+point['x']*width,top+point['y']*height
                    canvas.create_oval(x-11,y-11,x+11,y+11,fill=ACCENT,outline='white',width=2);canvas.create_text(x,y,text=str(number),fill='white')
            if index==0 and self.anchor:
                x,y=left+self.anchor['x']*width,top+self.anchor['y']*height
                canvas.create_oval(x-8,y-8,x+8,y+8,outline=ACCENT,width=3)

    def pin(self,event):
        if self._busy or not self._rects[0]:return
        point=normalized_point(self._rects[0],self.canvases[0].canvasx(event.x),self.canvases[0].canvasy(event.y))
        if point:
            self.anchor={'page':self.page+1,'x':point[0],'y':point[1]};self.location.configure(text=f'Pinned to page / slide {self.page+1}');self.draw()

    def paint_comments(self):
        for child in self.comments.winfo_children():child.destroy()
        _,version=reviews.find_version(self.data,self.asset_id,self.current)
        for number,comment in enumerate(version['comments'],1):
            anchor=comment.get('anchor');location=f" · page {anchor['page']}" if anchor else ''
            frame=ctk.CTkFrame(self.comments);frame.pack(fill='x',pady=5)
            ctk.CTkLabel(frame,text=f"#{number} {comment['author']}{location}",anchor='w',wraplength=230).pack(fill='x',padx=10,pady=(8,2))
            ctk.CTkLabel(frame,text=comment['text'],anchor='w',justify='left',wraplength=230).pack(fill='x',padx=10,pady=(0,8))
            if anchor:ctk.CTkButton(frame,text='Go to pin',height=24,command=lambda p=anchor['page']:self.go_to_page(p)).pack(anchor='w',padx=10,pady=(0,8))
        if not version['comments']:ctk.CTkLabel(self.comments,text='No feedback yet.',text_color=MUTED).pack(pady=15)

    def go_to_page(self,page):
        count=self._documents.get(self.current,{}).get('count',getattr(self,'_count',1))
        self.page=max(0,min(page-1,count-1));self.anchor=None;self.load_pages()

    def clear_pin(self):self.anchor=None;self.location.configure(text='Comment for this version · click to pin a location');self.draw()

    def reset_view(self):
        for canvas in self.canvases:canvas.xview_moveto(0);canvas.yview_moveto(0)
        self.draw()

    def wheel(self,event,canvas):
        if event.state & 1:canvas.xview_scroll(-int(event.delta/120),'units')
        else:canvas.yview_scroll(-int(event.delta/120),'units')
        return 'break'

    def add_comment(self):
        if self._busy:return
        identifier=self.current;author=self.author.get();text=self.text.get('1.0','end').strip();anchor=dict(self.anchor) if self.anchor else None
        self._busy=True;self.add_button.configure(state='disabled');self.version_menu.configure(state='disabled');self.compare_menu.configure(state='disabled')
        def work():
            try:reviews.add_comment(self.path,self.asset_id,identifier,author,text,anchor);error=None
            except Exception as exc:error=str(exc)
            def finish():
                self._busy=False;self.add_button.configure(state='normal');self.version_menu.configure(state='normal');self.compare_menu.configure(state='normal')
                if error:self.status.configure(text=error);return
                self.text.delete('1.0','end');self.anchor=None;self.location.configure(text='Click the preview to pin feedback.');self.reload_data();self.draw();self.status.configure(text='Comment saved to this version')
            self.bridge.post(finish)
        threading.Thread(target=work,daemon=True).start()

    def destroy(self):
        if self._closed:return
        self._closed=True;self.cancel.set();self.bridge.close();cancel_widget_callbacks(self);super().destroy()
        if self.on_changed:self.on_changed()
