"""Position square, portrait and story framing before a campaign export."""
import copy
from pathlib import Path
import threading
import tkinter as tk
import customtkinter as ctk
from PIL import Image,ImageOps,ImageTk
from campaign_crops import SOCIAL_SIZES,prepare_crop_preview,crop_box,settings_sha
from visual_pages import fitted_rect,normalized_point
from ui_dispatch import TkEventBridge,cancel_widget_callbacks
from design_system import style_dialog,ACCENT,ACCENT_HOVER


class CropDialog(ctk.CTkToplevel):
    def __init__(self,master,profile,jobs,on_save):
        super().__init__(master);style_dialog(self,master);self.title('Shadow — Campaign framing');self.geometry('1000x720');self.minsize(800,600)
        self.profile=copy.deepcopy(profile);self.positions=copy.deepcopy(profile.get('crop_positions',{}));self.on_save=on_save
        self.jobs=[job for job in jobs if job['preset'] in SOCIAL_SIZES];self.sources=list(dict.fromkeys(job['source'] for job in self.jobs))
        self.source=self.sources[0];self.preset=next(job['preset'] for job in self.jobs if job['source']==self.source)
        self.bridge=TkEventBridge(self);self._generation=0;self._prepared={};self._image=None;self._photos=[None,None];self._rect=None;self._draw_job=None;self._closed=False
        self.x=tk.DoubleVar(master=self,value=.5);self.y=tk.DoubleVar(master=self,value=.5)
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(1,weight=1)
        header=ctk.CTkFrame(self,fg_color='transparent');header.grid(row=0,column=0,sticky='ew',padx=20,pady=14)
        labels={f'{index} · {Path(source).name}':source for index,source in enumerate(self.sources,1)};self.source_labels=labels
        self.source_menu=ctk.CTkOptionMenu(header,values=list(labels),command=self.choose_source,width=240);self.source_menu.set(next(iter(labels)));self.source_menu.pack(side='left',padx=(0,12))
        self.preset_menu=ctk.CTkOptionMenu(header,command=self.choose_preset,width=200);self.preset_menu.pack(side='left')
        canvases=ctk.CTkFrame(self);canvases.grid(row=1,column=0,sticky='nsew',padx=20);canvases.grid_columnconfigure((0,1),weight=1,uniform='previews');canvases.grid_rowconfigure(1,weight=1)
        self.canvases=[]
        for column,title in enumerate(('Source · click to move the crop','Export preview')):
            ctk.CTkLabel(canvases,text=title,anchor='w').grid(row=0,column=column,sticky='ew',padx=12,pady=8)
            canvas=tk.Canvas(canvases,background='#18181F',highlightthickness=0);canvas.grid(row=1,column=column,sticky='nsew',padx=8,pady=(0,8));canvas.bind('<Configure>',self.schedule_draw);self.canvases.append(canvas)
        self.canvases[0].bind('<Button-1>',self.move_crop);self.canvases[0].bind('<B1-Motion>',self.move_crop)
        controls=ctk.CTkFrame(self,fg_color='transparent');controls.grid(row=2,column=0,sticky='ew',padx=20,pady=12);controls.grid_columnconfigure(1,weight=1)
        for row,(name,variable) in enumerate((('Horizontal',self.x),('Vertical',self.y))):
            ctk.CTkLabel(controls,text=name).grid(row=row,column=0,padx=(0,15),pady=5)
            ctk.CTkSlider(controls,from_=0,to=1,variable=variable,command=lambda value:self.changed()).grid(row=row,column=1,sticky='ew')
        row=ctk.CTkFrame(self,fg_color='transparent');row.grid(row=3,column=0,sticky='ew',padx=20,pady=(0,14))
        self.status=ctk.CTkLabel(row,text='Preparing full image…',anchor='w',justify='left',wraplength=360);self.status.pack(side='left',fill='x',expand=True)
        self.save_button=ctk.CTkButton(row,text='Use these crops',fg_color=ACCENT,hover_color=ACCENT_HOVER,command=self.save);self.save_button.pack(side='right')
        ctk.CTkButton(row,text='Center',width=80,command=self.center).pack(side='right',padx=10)
        self.protocol('WM_DELETE_WINDOW',self.destroy);self.load_source()

    def remember(self):
        if self._image is None or self.source not in self._prepared:return
        self.positions.setdefault(self.source,{})[self.preset]={'x':self.x.get(),'y':self.y.get(),'source_sha256':self._prepared[self.source][1],'settings_sha256':settings_sha(self.profile,self.preset)}

    def choose_source(self,label):self.remember();self.source=self.source_labels[label];self.load_source()

    def choose_preset(self,preset):self.remember();self.preset=preset;self.load_position();self.draw()

    def load_position(self):
        point=self.positions.get(self.source,{}).get(self.preset,{})
        if point and self.source in self._prepared and (point['source_sha256']!=self._prepared[self.source][1] or point['settings_sha256']!=settings_sha(self.profile,self.preset)):point={}
        self.x.set(point.get('x',.5));self.y.set(point.get('y',.5))

    def load_source(self):
        presets=list(dict.fromkeys(job['preset'] for job in self.jobs if job['source']==self.source))
        if self.preset not in presets:self.preset=presets[0]
        self.preset_menu.configure(values=presets);self.preset_menu.set(self.preset)
        self._generation+=1;generation=self._generation;source=self.source;self._image=None;self.save_button.configure(state='disabled');self.status.configure(text='Preparing full image…')
        for canvas in self.canvases:canvas.delete('all')
        def work():
            try:prepared=self._prepared.get(source) or prepare_crop_preview(self.profile,Path(source));error=None
            except Exception as exc:prepared=None;error=str(exc)
            def finish():
                if generation!=self._generation:return
                if error:self.status.configure(text=error);return
                self._prepared[source]=prepared;self._image=prepared[0]
                while len(self._prepared)>3:self._prepared.pop(next(key for key in self._prepared if key!=source))
                self.positions[source]={preset:point for preset,point in self.positions.get(source,{}).items() if point['source_sha256']==prepared[1] and point['settings_sha256']==settings_sha(self.profile,preset)}
                self.load_position();self.save_button.configure(state='normal');self.status.configure(text='Original stays unchanged · positions save with the project');self.draw()
            self.bridge.post(finish)
        threading.Thread(target=work,daemon=True).start()

    def changed(self):self.schedule_draw()

    def center(self):self.x.set(.5);self.y.set(.5);self.draw()

    def schedule_draw(self,event=None):
        if self._draw_job:self.after_cancel(self._draw_job)
        self._draw_job=self.after(30,self.draw)

    def draw(self):
        self._draw_job=None
        if self._image is None:return
        size=SOCIAL_SIZES[self.preset];position=(self.x.get(),self.y.get())
        canvas=self.canvases[0];canvas.delete('all');rect=fitted_rect(self._image.size,canvas.winfo_width(),canvas.winfo_height());self._rect=rect
        left,top,width,height=rect
        self._photos[0]=ImageTk.PhotoImage(self._image.resize((max(1,int(width)),max(1,int(height))),Image.Resampling.LANCZOS));canvas.create_image(left,top,image=self._photos[0],anchor='nw')
        box=crop_box(self._image.size,size,position);scale=width/self._image.width
        canvas.create_rectangle(left+box[0]*scale,top+box[1]*scale,left+box[2]*scale,top+box[3]*scale,outline=ACCENT,width=3)
        canvas=self.canvases[1];canvas.delete('all');rect=fitted_rect(size,canvas.winfo_width(),canvas.winfo_height());left,top,width,height=rect
        cropped=ImageOps.fit(self._image,(max(1,int(width)),max(1,int(height))),method=Image.Resampling.LANCZOS,centering=position)
        self._photos[1]=ImageTk.PhotoImage(cropped);canvas.create_image(left,top,image=self._photos[1],anchor='nw')

    def move_crop(self,event):
        if self._image is None or self._rect is None:return
        point=normalized_point(self._rect,event.x,event.y)
        if point is None:return
        box=crop_box(self._image.size,SOCIAL_SIZES[self.preset]);cw,ch=box[2]-box[0],box[3]-box[1]
        self.x.set(max(0,min(1,(point[0]*self._image.width-cw/2)/(self._image.width-cw))) if self._image.width>cw else .5)
        self.y.set(max(0,min(1,(point[1]*self._image.height-ch/2)/(self._image.height-ch))) if self._image.height>ch else .5)
        self.schedule_draw()

    def save(self):self.remember();self.on_save(self.positions);self.destroy()

    def destroy(self):
        if self._closed:return
        self._closed=True;self.bridge.close();cancel_widget_callbacks(self);super().destroy()
