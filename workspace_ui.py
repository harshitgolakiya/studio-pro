"""A file-first workspace and one searchable entry point for every tool."""
from pathlib import Path
import tkinter as tk
import customtkinter as ctk

from file_context import tool_catalog, file_tags


class FileWorkspace:
    def __init__(self, app, parent, queue, header, output, footer):
        self.app, self.queue, self.header = app, queue, header
        self.output, self.footer = output, footer
        self.tools = tool_catalog()
        self.mode = 'files'
        self.converting = False
        self._signature = None
        self.home = ctk.CTkFrame(parent, fg_color='transparent', height=450)
        self.home.grid_columnconfigure(0, weight=1)
        self.home.grid_rowconfigure((0, 2), weight=1)
        hero = ctk.CTkFrame(self.home, corner_radius=20, border_width=1, border_color=('#cbd5e1', '#26313c'))
        hero.grid(row=1, column=0, sticky='ew', padx=90, pady=50)
        ctk.CTkLabel(hero, text='Start with your files', font=ctk.CTkFont(size=30, weight='bold')).pack(pady=(50, 12))
        ctk.CTkLabel(hero, text='Drop files anywhere, or choose them below.\nShadow will show what you can do with them.',
                     font=ctk.CTkFont(size=15), text_color=('#526170', '#aab8c5')).pack(pady=(0, 28))
        buttons = ctk.CTkFrame(hero, fg_color='transparent')
        buttons.pack(pady=(0, 50))
        ctk.CTkButton(buttons, text='Choose files', height=44, command=app._add_files).pack(side='left', padx=8)
        ctk.CTkButton(buttons, text='Choose folder', height=44, command=app._add_folder).pack(side='left', padx=8)
        self.browser = ctk.CTkFrame(parent, fg_color='transparent')
        self.browser.grid_columnconfigure(0, weight=1)
        self.title = ctk.CTkLabel(self.browser, text='', font=ctk.CTkFont(size=23, weight='bold'), anchor='w')
        self.title.grid(row=0, column=0, sticky='ew', pady=(0, 3))
        self.summary = ctk.CTkLabel(self.browser, text='', anchor='w', text_color=('#526170', '#aab8c5'))
        self.summary.grid(row=1, column=0, sticky='ew', pady=(0, 10))
        filters = ctk.CTkFrame(self.browser, fg_color='transparent')
        filters.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        filters.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(filters, text='Search tools', anchor='w').grid(row=0, column=0, padx=(0, 10))
        self.query = tk.StringVar(master=app)
        self.search = ctk.CTkEntry(filters, textvariable=self.query, placeholder_text='Search tools, e.g. subtitles, PDF, voice…', height=36)
        self.search.grid(row=0, column=1, sticky='ew', padx=(0, 10))
        self.search.bind('<KeyRelease>', lambda _: self.render_tools())
        self.group = tk.StringVar(master=app, value='All categories')
        self.group_menu = ctk.CTkOptionMenu(filters, variable=self.group, values=['All categories'], command=lambda _: self.render_tools(), width=180)
        self.group_menu.grid(row=0, column=2)
        self.cards = ctk.CTkFrame(self.browser, fg_color='transparent')
        self.cards.grid(row=3, column=0, sticky='ew')
        self.cards.grid_columnconfigure((0, 1), weight=1, uniform='tools')
        self.back = ctk.CTkButton(parent, text='← Back to file actions', command=self.back_to_actions, height=34)
        self.refresh()

    def selected_inputs(self):
        selected = self.app._selected_paths()
        return selected or list(self.app.selected_files)

    def reset_scroll(self):
        self.app._content_shell._parent_canvas.yview_moveto(0)

    def show_library(self):
        if self.app.conversion_running: return
        self.mode = 'library'
        self.converting = False
        self.query.set('')
        self.group.set('All categories')
        self._signature = None
        self.refresh()
        self.reset_scroll()
        self.search.focus_set()

    def back_to_actions(self):
        if self.app.conversion_running: return
        self.mode = 'files'
        self.converting = False
        self.query.set('')
        self.group.set('All categories')
        self._signature = None
        self.refresh()
        self.reset_scroll()

    def refresh(self):
        has_files = bool(self.app.selected_files)
        for widget in (self.home, self.browser, self.back, self.queue, self.output, self.footer, self.app.settings_tabview):
            widget.grid_remove()
        if self.mode == 'library':
            self.browser.grid(row=0, column=0, sticky='ew', padx=32, pady=24)
            self.title.configure(text='All tools')
            self.summary.configure(text='Everything in one place. Choose a tool to open its workspace.')
        elif not has_files:
            self.converting = False
            self.home.grid(row=0, column=0, sticky='nsew')
            return
        else:
            self.queue.grid()
            self.app.empty_state.grid_remove()
            self.app.table_frame.grid(row=1, column=0, sticky='ew', pady=(0, 8))
            if self.converting:
                self.back.grid(row=1, column=0, sticky='w', padx=32, pady=(0, 8))
                self.app.settings_tabview.grid(row=2, column=0, sticky='ew', padx=32, pady=(0, 8))
                self.output.grid(row=3, column=0, sticky='ew', padx=32, pady=(0, 10))
                self.footer.grid(row=4, column=0, sticky='ew', padx=32, pady=(0, 20))
                return
            self.browser.grid(row=1, column=0, sticky='ew', padx=32, pady=(8, 24))
            paths = self.selected_inputs()
            self.title.configure(text='What would you like to do?')
            types = sorted(set().union(*(file_tags(p) for p in paths)) - {'file', 'office', 'ocr-image', 'text', 'workbook'})
            self.summary.configure(text=f'{len(paths)} file(s) in focus · {", ".join(types)}. Select queue rows to work on a subset.')
        signature = (self.mode, tuple(self.selected_inputs()))
        if signature != self._signature:
            self._signature = signature
            candidates = self.candidates()
            groups = ['All categories', *sorted({t.group for t in candidates})]
            self.group_menu.configure(values=groups)
            if self.group.get() not in groups: self.group.set('All categories')
            self.render_tools()

    def candidates(self):
        paths = self.selected_inputs()
        return self.tools if self.mode == 'library' else [t for t in self.tools if t.inputs(paths)]

    def render_tools(self):
        for child in self.cards.winfo_children(): child.destroy()
        query, group = self.query.get().strip().casefold(), self.group.get()
        matches = [t for t in self.candidates() if (group == 'All categories' or t.group == group)
                   and query in f'{t.title} {t.description} {t.group} {t.key}'.casefold()]
        if self.mode != 'library':
            priority = {'transcribe': 1, 'pdf-merge': 1, 'data-convert': 1, 'subtitle-edit': 1, 'archive-extract': 1,
                        'ocr': 2, 'audio': 2, 'trim': 2, 'speak': 3, 'preview': 4}
            matches.sort(key=lambda t: 0 if t.key.startswith('convert-') else priority.get(t.key, 5))
        self.visible_tools = [t.key for t in matches]
        if not matches:
            ctk.CTkLabel(self.cards, text='No matching tools. Try another search or category.').grid(row=0, column=0, sticky='w')
        for index, tool in enumerate(matches):
            card = ctk.CTkFrame(self.cards, corner_radius=12, border_width=1, border_color=('#d4dfe6', '#26313c'))
            card.grid(row=index // 2, column=index % 2, sticky='nsew', padx=(0, 10) if index % 2 == 0 else (0, 0), pady=(0, 10))
            ctk.CTkLabel(card, text=tool.group.upper(), font=ctk.CTkFont(size=10), anchor='w', text_color=('#526170', '#aab8c5')).pack(fill='x', padx=16, pady=(12, 0))
            button = ctk.CTkButton(card, text=tool.title, anchor='w', font=ctk.CTkFont(size=15, weight='bold'),
                                  fg_color='transparent', text_color=('#142330', '#e5eff7'), hover_color=('#dce8ed', '#21313c'),
                                  height=36, command=lambda t=tool: self.open(t))
            button.pack(fill='x', padx=10, pady=2)
            ctk.CTkLabel(card, text=tool.description, wraplength=360, justify='left', anchor='w').pack(fill='x', padx=16, pady=(0, 6))
            inputs = tool.inputs(self.selected_inputs())
            hint = 'Choose inputs in the tool' if self.mode == 'library' else f'{len(inputs)} of {len(self.selected_inputs())} file(s) apply'
            if self.mode == 'library' and tool.no_input: hint = 'Available without a file'
            if len(inputs) > 1 and not tool.multiple and self.mode != 'library':
                hint += ' · select one queue row'
                button.configure(state='disabled')
            ctk.CTkLabel(card, text=hint, font=ctk.CTkFont(size=11), text_color=('#526170', '#aab8c5'), anchor='w').pack(fill='x', padx=16, pady=(0, 12))

    def open(self, tool):
        app = self.app
        if app.conversion_running:
            app.status_text.set('Wait for the current conversion to finish.')
            return
        paths = tool.inputs(self.selected_inputs())
        if not tool.multiple and len(paths) > 1:
            paths = [] if self.mode == 'library' else paths
            if paths: return
        if tool.key.startswith('convert-'):
            if not paths:
                self.back_to_actions()
                app._add_files()
                paths = tool.inputs(self.selected_inputs())
                if not paths: return
            self.mode = 'files'
            self.converting = True
            app._conversion_inputs = paths
            app.table.selection_set([app.row_ids[p] for p in paths])
            app._adapt_settings_to_selection()
            app.status_text.set(f'Conversion applies to {len(paths)} of {len(app.selected_files)} queued files.')
            self.refresh()
            self.reset_scroll()
            return
        local = {'preview': app._open_selected_preview, 'optimize': app._open_selected_optimizer,
                 'trim': app._open_selected_trimmer, 'history': app._open_history, 'recipes': app._open_recipe_manager,
                 'watch': app._open_watch_folder_dialog, 'download': app._open_url_downloader,
                 'license': app._open_license_manager, 'about': app._open_about_dialog}
        if tool.key in local:
            if tool.key in {'preview', 'optimize', 'trim'}:
                if not paths:
                    app._add_files()
                    paths = tool.inputs(app.selected_files)
                if len(paths) != 1: return
                tags = file_tags(paths[0])
                if tool.key == 'preview' and tags.intersection({'audio', 'video'}):
                    from utils import open_file_or_folder
                    open_file_or_folder(paths[0])
                    return
                app.table.selection_set(app.row_ids[paths[0]])
            local[tool.key]()
            return
        app._open_studio_tools().open_tool(tool.key, paths)


def install_workspace(app, parent, queue, header, output, footer, header_right):
    app._file_workspace = FileWorkspace(app, parent, queue, header, output, footer)
    for child in header_right.winfo_children(): child.pack_forget()
    menu = tk.Menu(app, tearoff=0)
    menu.add_command(label='All tools…', command=app._file_workspace.show_library)
    menu.add_command(label='Files', command=app._file_workspace.back_to_actions)
    menu.add_separator()
    menu.add_command(label='History', command=app._open_history)
    for theme in ('System', 'Dark', 'Light'):
        menu.add_command(label=f'Theme: {theme}', command=lambda t=theme: app._set_theme(t))
    menu.add_command(label='License', command=app._open_license_manager)
    menu.add_command(label='About', command=app._open_about_dialog)
    button = ctk.CTkButton(header_right, text='Menu', width=90, height=34,
                          command=lambda: menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()))
    button.pack(side='right')
    app.workspace_menu = button
    app.convert_button.configure(command=app._run_workspace_conversion)
    app.table.configure(height=3)
    for button in (app.preview_button, app.optimize_button, app.watch_folder_button, app.vip_downloader_button):
        button.pack_forget()
    app.add_button.configure(text='+ Add files')
