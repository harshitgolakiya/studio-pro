"""Nonblocking read-only delivery report with an explicit recheck action."""
from pathlib import Path
import threading
from tkinter import filedialog
import customtkinter as ctk
from campaign_checks import check_delivery, save_check_report
from design_system import style_dialog, MUTED, ACCENT, ACCENT_HOVER, DANGER_LIGHT, DANGER_DARK
from studio_runtime import StudioCancelled
from ui_dispatch import TkEventBridge, cancel_widget_callbacks


class DeliveryChecksDialog(ctk.CTkToplevel):
    def __init__(self, master, receipt, rules=None):
        super().__init__(master)
        style_dialog(self, master)
        self.title('Shadow — Delivery checks');self.geometry('880x680');self.minsize(700,480)
        self.receipt=Path(receipt);self.rules=rules;self.report=None;self._busy=False;self._closed=False
        self.cancel=threading.Event();self.bridge=TkEventBridge(self)
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(2,weight=1)
        ctk.CTkLabel(self,text='Delivery checks',font=ctk.CTkFont(size=26,weight='bold'),anchor='w').grid(row=0,column=0,sticky='ew',padx=22,pady=(18,5))
        self.summary=ctk.CTkLabel(self,text='Checking exported files…',anchor='w',justify='left',wraplength=650)
        self.summary.grid(row=1,column=0,sticky='ew',padx=22,pady=(0,12))
        self.results=ctk.CTkScrollableFrame(self);self.results.grid(row=2,column=0,sticky='nsew',padx=20);self.results.grid_columnconfigure(0,weight=1)
        footer=ctk.CTkFrame(self,fg_color='transparent');footer.grid(row=3,column=0,sticky='ew',padx=22,pady=16)
        ctk.CTkLabel(footer,text='File checks only · reviewer approval stays separate.',text_color=MUTED,wraplength=290,justify='left').pack(side='left',fill='x',expand=True)
        self.save_button=ctk.CTkButton(footer,text='Save report',width=110,command=self.save,state='disabled');self.save_button.pack(side='right',padx=(10,0))
        self.recheck_button=ctk.CTkButton(footer,text='Recheck',width=100,fg_color=ACCENT,hover_color=ACCENT_HOVER,command=self.recheck);self.recheck_button.pack(side='right')
        self.protocol('WM_DELETE_WINDOW',self.destroy);self.recheck()

    def recheck(self):
        if self._busy:return
        self._busy=True;self.report=None;self.save_button.configure(state='disabled');self.recheck_button.configure(state='disabled');self.summary.configure(text='Checking exported files…')
        for child in self.results.winfo_children():child.destroy()
        def work():
            try:
                report=check_delivery(self.receipt,self.rules,self.cancel.is_set)
                save_check_report(report,self.receipt.parent/'delivery-checks.json');error=None
            except StudioCancelled:return
            except Exception as exc:report=None;error=str(exc)
            self.bridge.post(lambda:self.finish(report,error))
        threading.Thread(target=work,daemon=True).start()

    def finish(self,report,error):
        self._busy=False;self.recheck_button.configure(state='normal')
        if error:self.summary.configure(text=error);return
        self.report=report;self.save_button.configure(state='normal')
        self.summary.configure(text=f'{report["status"]} · {report["files"]} required files · {report["errors"]} errors · {report["warnings"]} warnings\nChecked against recorded formats, dimensions, hashes and configured size limits.')
        for row,record in enumerate([{'file':'Campaign requirements','issues':report['issues']},*report['results']]):
            if row==0 and not record['issues']:continue
            card=ctk.CTkFrame(self.results);card.grid(row=row,column=0,sticky='ew',padx=4,pady=5)
            ctk.CTkLabel(card,text=record['file'],font=ctk.CTkFont(weight='bold'),anchor='w',justify='left',wraplength=620).pack(fill='x',padx=14,pady=(10,3))
            details=record.get('preset','')
            if record.get('dimensions'):details+=f' · {record["dimensions"][0]} × {record["dimensions"][1]} px'
            if 'bytes' in record:details+=f' · {record["bytes"]/1024/1024:.2f} MB'
            if details:ctk.CTkLabel(card,text=details,text_color=MUTED,anchor='w').pack(fill='x',padx=14)
            for issue in record['issues'] or [{'level':'pass','text':'Passed file checks.'}]:
                text=f'{issue["level"].capitalize()} · {issue["text"]}'
                color=(DANGER_LIGHT,DANGER_DARK) if issue['level']=='error' else MUTED
                ctk.CTkLabel(card,text=text,text_color=color,anchor='w',justify='left',wraplength=620).pack(fill='x',padx=14,pady=(3,8))

    def save(self):
        if not self.report:return
        name=filedialog.asksaveasfilename(parent=self,title='Save delivery check report',defaultextension='.json',initialfile='delivery-checks.json')
        if name:
            try:save_check_report(self.report,Path(name))
            except Exception as exc:self.summary.configure(text=str(exc))

    def destroy(self):
        if self._closed:return
        self._closed=True;self.cancel.set();self.bridge.close();cancel_widget_callbacks(self);super().destroy()
