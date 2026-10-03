"""A file-first workspace and one searchable entry point for every tool."""
from pathlib import Path
import tkinter as tk
import customtkinter as ctk

from file_context import tool_catalog, file_tags

SECTIONS = {
    'Images': ('Resize, convert and watermark', {'convert-image', 'optimize', 'plugin-codec', 'plugin-process', 'print-cmyk'}),
    'Video': ('Compress, trim and export', {'convert-video', 'trim'}),
    'Audio': ('Voiceovers, transcripts and cleanup', {'convert-audio', 'transcribe', 'speak', 'audio', 'speech-batch', 'audio-isolate'}),
    'Documents & PDF': ('Convert, edit and manage pages', set()),
    'Data': ('Spreadsheets and structured data', set()),
    'Archives & delivery': ('Pack, extract and deliver files', set()),
    'Workspace': ('Projects, recipes and automation', set()),
    'Settings': ('Voices, engines and preferences', set()),
}


def section_for(tool):
    for title, (_, keys) in SECTIONS.items():
        if tool.key in keys: return title
    if tool.group in {'PDF', 'Office', 'Subtitles', 'Print', 'OCR'} or tool.key == 'convert-document': return 'Documents & PDF'
    if tool.group == 'Data': return 'Data'
    if tool.group in {'Archives', 'Delivery'}: return 'Archives & delivery'
    if tool.group == 'Setup': return 'Settings'
    return 'Workspace'


def in_section(tool, section):
    if section_for(tool) == section: return True
    if section == 'Video' and tool.key in {'transcribe', 'speech-batch', 'audio-isolate', 'subtitle-edit', 'subtitle-translate'}: return True
    if section == 'Documents & PDF' and tool.key in {'speak', 'print-cmyk'}: return True
    return False


def section_icon(name):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (96, 96))
    draw = ImageDraw.Draw(image)
    ink, line = '#A799EA', 6
    if name == 'Images':
        draw.rounded_rectangle((14, 18, 82, 78), radius=8, outline=ink, width=line)
        draw.ellipse((56, 30, 66, 40), fill=ink)
        draw.line((19, 69, 38, 48, 54, 62, 63, 53, 78, 68), fill=ink, width=line)
    elif name == 'Video':
        draw.rounded_rectangle((14, 22, 82, 74), radius=9, outline=ink, width=line)
        draw.polygon((41, 35, 41, 62, 63, 48), fill=ink)
    elif name == 'Audio':
        for x, height in ((19, 18), (33, 38), (47, 60), (61, 38), (75, 18)):
            draw.rounded_rectangle((x, 48-height//2, x+6, 48+height//2), radius=3, fill=ink)
    elif name == 'Documents & PDF':
        draw.rounded_rectangle((25, 12, 73, 84), radius=6, outline=ink, width=line)
        for y in (35, 49, 63): draw.line((36, y, 62, y), fill=ink, width=5)
    elif name == 'Data':
        draw.rounded_rectangle((14, 20, 82, 76), radius=5, outline=ink, width=line)
        draw.line((17, 38, 79, 38), fill=ink, width=5)
        draw.line((38, 23, 38, 73), fill=ink, width=5)
        draw.line((17, 57, 79, 57), fill=ink, width=4)
    elif name == 'Archives & delivery':
        draw.rounded_rectangle((18, 34, 78, 79), radius=5, outline=ink, width=line)
        draw.rounded_rectangle((13, 20, 83, 35), radius=4, outline=ink, width=line)
        draw.line((38, 51, 58, 51), fill=ink, width=line)
    elif name == 'Workspace':
        for x, y in ((18, 18), (54, 18), (18, 54), (54, 54)):
            draw.rounded_rectangle((x, y, x+24, y+24), radius=5, outline=ink, width=5)
    else:
        draw.ellipse((24, 24, 72, 72), outline=ink, width=line)
        draw.ellipse((40, 40, 56, 56), outline=ink, width=5)
        for a, b in (((48, 12), (48, 25)), ((48, 71), (48, 84)), ((12, 48), (25, 48)), ((71, 48), (84, 48))):
            draw.line((*a, *b), fill=ink, width=line)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(28, 28))


class FileWorkspace:
    def __init__(self, app, parent, queue, header, output, footer):
        self.app, self.queue, self.header = app, queue, header
        self.output, self.footer = output, footer
        self.tools = tool_catalog()
        self.mode = 'files'
        self.converting = False
        self._signature = None
        self.expanded = False
        self.section = None
        self._icons = {name: section_icon(name) for name in SECTIONS}
        self.home = ctk.CTkFrame(parent, fg_color='transparent')
        self.home.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.home, text='YOUR CREATIVE WORKSPACE', anchor='w', text_color=('#81758f', '#a99bcf'),
                     font=ctk.CTkFont(size=11, weight='bold')).grid(row=0, column=0, sticky='w', pady=(28, 14))
        ctk.CTkLabel(self.home, text='Good work. Less effort.', anchor='w',
                     font=ctk.CTkFont(family='Outfit', size=38, weight='bold')).grid(row=1, column=0, sticky='w')
        ctk.CTkLabel(self.home, text='One calm place to convert, create and finish your files.', anchor='w',
                     text_color=('#777785', '#9493A3'), font=ctk.CTkFont(size=14)).grid(row=2, column=0, sticky='w', pady=(8, 28))
        hero = ctk.CTkFrame(self.home, fg_color=('#ffffff', '#1C1C23'), corner_radius=18,
                            border_width=1, border_color=('#e4e1ec', '#38323f'))
        hero.grid(row=3, column=0, sticky='ew')
        ctk.CTkLabel(hero, text='', image=self._icons['Archives & delivery'], width=48, height=48, corner_radius=14,
                     fg_color=('#eee9fc', '#302940'), text_color=('#7561D4', '#B9ADF3'),
                     font=ctk.CTkFont(size=28)).pack(pady=(28, 12))
        ctk.CTkLabel(hero, text='Bring your files. We’ll take it from here.',
                     font=ctk.CTkFont(size=18, weight='bold')).pack(pady=(0, 5))
        ctk.CTkLabel(hero, text='Drop files anywhere in this window', text_color=('#777785', '#9493A3'),
                     font=ctk.CTkFont(size=12)).pack()
        buttons = ctk.CTkFrame(hero, fg_color='transparent');buttons.pack(pady=(20, 26))
        ctk.CTkButton(buttons, text='Choose files', width=150, height=40, fg_color='#7561D4', hover_color='#8975E4', text_color='#ffffff', command=app._add_files).pack(side='left', padx=(0, 12))
        ctk.CTkButton(buttons, text='Open a folder', width=130, height=40, fg_color='transparent',
                      text_color=('#777785', '#aaa7b8'), hover_color=('#eeeeF4', '#292932'), command=app._add_folder).pack(side='left')
        ctk.CTkLabel(self.home, text='OR START SOMETHING NEW', anchor='w', text_color=('#777785', '#9493A3'),
                     font=ctk.CTkFont(size=10, weight='bold')).grid(row=4, column=0, sticky='w', pady=(28, 12))
        quick = ctk.CTkFrame(self.home, fg_color='transparent');quick.grid(row=5, column=0, sticky='ew')
        quick.grid_columnconfigure((0, 1, 2), weight=1, uniform='quick')
        for i, (key, title, copy) in enumerate((('speak', 'Create a voiceover', 'Turn your words into audio'),
                                              ('pdf-merge', 'Bring PDFs together', 'One polished document'),
                                              ('transcribe', 'Get the transcript', 'Speech into editable text'))):
            card = ctk.CTkFrame(quick, fg_color=('#ffffff', '#1C1C23'), corner_radius=12)
            card.grid(row=0, column=i, sticky='ew', padx=(0, 12) if i < 2 else 0)
            tool = next(t for t in self.tools if t.key == key)
            ctk.CTkButton(card, text=title+'  ›', anchor='w', height=42, font=ctk.CTkFont(size=12, weight='bold'),
                          fg_color='transparent', text_color=('#282833', '#eeecf5'), hover_color=('#EEEEF4', '#292932'),
                          command=lambda t=tool:self.open(t)).pack(fill='x', padx=8, pady=(6, 0))
            ctk.CTkLabel(card, text=copy, anchor='w', font=ctk.CTkFont(size=11),
                         text_color=('#777785', '#9493A3')).pack(fill='x', padx=18, pady=(0, 12))
        self.browser = ctk.CTkFrame(parent, fg_color='transparent')
        self.browser.grid_columnconfigure(0, weight=1)
        self.title = ctk.CTkLabel(self.browser, text='', font=ctk.CTkFont(family='Outfit', size=30, weight='bold'), anchor='w')
        self.title.grid(row=0, column=0, sticky='ew', pady=(0, 3))
        self.summary = ctk.CTkLabel(self.browser, text='', anchor='w', text_color=('#777785', '#9493A3'))
        self.summary.grid(row=1, column=0, sticky='ew', pady=(0, 18))
        filters = ctk.CTkFrame(self.browser, fg_color='transparent')
        self.filters = filters
        filters.grid(row=3, column=0, sticky='ew', pady=(0, 12))
        filters.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(filters, text='Search tools', anchor='w').grid(row=0, column=0, padx=(0, 10))
        self.query = tk.StringVar(master=app)
        self.search = ctk.CTkEntry(filters, textvariable=self.query, placeholder_text='Search tools, e.g. subtitles, PDF, voice…', height=36)
        self.search.grid(row=0, column=1, sticky='ew', padx=(0, 10))
        self.search.bind('<KeyRelease>', lambda _: self.render_tools())
        self.group = tk.StringVar(master=app, value='All categories')
        self.group_menu = ctk.CTkOptionMenu(filters, variable=self.group, values=['All categories'], command=lambda _: self.render_tools(), width=180)
        # Categories are visible tiles, rather than a filter hiding a long list.
        self.library_back = ctk.CTkButton(filters, text='← Categories', width=125, height=34,
                                         fg_color='transparent', border_width=1, border_color=('#DDDDE7', '#33333E'),
                                         text_color=('#282833', '#aaa7b8'), command=self._categories)
        self.library_back.grid(row=0, column=2)
        self.cards = ctk.CTkFrame(self.browser, fg_color='transparent')
        self.cards.grid(row=4, column=0, sticky='ew')
        self.cards.grid_columnconfigure((0, 1, 2), weight=1, uniform='tools')
        self.back = ctk.CTkButton(parent, text='← Back to file actions', command=self.back_to_actions, height=34)
        self.file_identity = ctk.CTkFrame(self.browser, corner_radius=12, fg_color=('#EEEEF4', '#202027'))
        self.file_identity.grid_columnconfigure(1, weight=1)
        self.file_icon = ctk.CTkLabel(self.file_identity, text='', width=52)
        self.file_icon.grid(row=0, column=0, rowspan=2, padx=(14, 6), pady=14)
        self.file_name = ctk.CTkLabel(self.file_identity, text='', anchor='w', font=ctk.CTkFont(size=14, weight='bold'))
        self.file_name.grid(row=0, column=1, sticky='ew', pady=(14, 0))
        self.file_detail = ctk.CTkLabel(self.file_identity, text='', anchor='w', font=ctk.CTkFont(size=11), text_color=('#777785', '#9493A3'))
        self.file_detail.grid(row=1, column=1, sticky='ew', pady=(0, 14))
        ctk.CTkButton(self.file_identity, text='Change', width=80, height=32, fg_color='transparent',
                      text_color=('#7561D4', '#B9ADF3'), hover_color=('#e4e0ef', '#2b2639'), command=self._change_files).grid(row=0, column=2, rowspan=2, padx=18)
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
        self.section = None
        self.expanded = False
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
        self.section = None
        self.expanded = False
        self.group.set('All categories')
        self._signature = None
        self.refresh()
        self.reset_scroll()

    def _sync_navigation(self):
        if not hasattr(self, 'nav_buttons'):return
        name = ('Explore tools' if self.section is None else self.section) if self.mode == 'library' else 'Preferences' if self.mode == 'preferences' else 'Home' if self.mode == 'home' or not self.app.selected_files else 'Files'
        self.breadcrumb.configure(text='Workspace  /  '+name)
        for title, button in self.nav_buttons.items():
            button.configure(fg_color=('#E2DDF3', '#2B2639') if title == name else 'transparent',
                             text_color=('#6652C2', '#C8BEF3') if title == name else ('#777785', '#a8a5b5'))

    def refresh(self):
        self._sync_navigation()
        if hasattr(self, 'preferences'):self.preferences.grid_remove()
        has_files = bool(self.app.selected_files)
        for widget in (self.home, self.browser, self.back, self.queue, self.output, self.footer, self.app.settings_tabview):
            widget.grid_remove()
        if self.mode == 'preferences':
            self.preferences.grid(row=0, column=0, sticky='ew')
            return
        if self.mode == 'library':
            self.browser.grid(row=0, column=0, sticky='ew', padx=0, pady=(28, 24))
            self.title.configure(text='Tools')
            self.summary.configure(text='Choose a category, or search for a tool.')
        elif self.mode == 'home' or not has_files:
            self.converting = False
            self.home.grid(row=0, column=0, sticky='nsew')
            return
        else:
            if len(self.app.selected_files) > 1 or self.converting:
                self.queue.grid()
            self.app.empty_state.grid_remove()
            self.app.table_frame.grid(row=1, column=0, sticky='ew', pady=(0, 8))
            if self.converting:
                self.back.grid(row=1, column=0, sticky='w', padx=32, pady=(0, 8))
                self.app.settings_tabview.grid(row=2, column=0, sticky='ew', padx=32, pady=(0, 8))
                self.output.grid(row=3, column=0, sticky='ew', padx=32, pady=(0, 10))
                self.footer.grid(row=4, column=0, sticky='ew', padx=32, pady=(0, 20))
                return
            self.browser.grid(row=1, column=0, sticky='ew', padx=0, pady=(24, 24))
            paths = self.selected_inputs()
            self.title.configure(text=paths[0].name if len(paths) == 1 else f'{len(paths)} files selected')
            self.summary.configure(text='Choose what to do with your file.' if len(paths) == 1 else 'Choose an action. Select rows above to work on fewer files.')
        signature = (self.mode, tuple(self.selected_inputs()))
        if signature != self._signature:
            self._signature = signature
            self.expanded = False
            candidates = self.candidates()
            groups = ['All categories', *sorted({t.group for t in candidates})]
            self.group_menu.configure(values=groups)
            if self.group.get() not in groups: self.group.set('All categories')
            self.render_tools()

    def candidates(self):
        paths = self.selected_inputs()
        return self.tools if self.mode == 'library' else [t for t in self.tools if t.inputs(paths)]

    def render_tools(self):
        self._sync_navigation()
        for child in self.cards.winfo_children(): child.destroy()
        self.file_identity.grid_remove()
        if self.mode == 'files' and len(self.selected_inputs()) == 1:
            path = self.selected_inputs()[0]
            tags = file_tags(path)
            section = 'Audio' if 'audio' in tags else 'Video' if 'video' in tags else 'Images' if 'image' in tags else 'Documents & PDF'
            self.file_icon.configure(image=self._icons[section])
            self.file_name.configure(text=path.name)
            size = path.stat().st_size if path.exists() else 0
            self.file_detail.configure(text=f'{path.suffix[1:].upper()} file   /   {size/1024/1024:.1f} MB')
            self.file_identity.grid(row=2, column=0, sticky='ew', pady=(4, 22))
            self.title.configure(text='Your file is ready.')
            self.summary.configure(text='Pick a direction. We’ll handle the details.')
        query = self.query.get().strip().casefold()
        if self.mode == 'library' or self.expanded or query:
            self.filters.grid()
        else:
            self.filters.grid_remove()
        self.library_back.grid_remove()
        if self.mode == 'library' and not query and self.section is None:
            self.cards.grid_columnconfigure((0, 1, 2), weight=1, uniform='tools')
            self.title.configure(text='Tools')
            self.summary.configure(text='Choose a category, or search for a tool.')
            self.visible_tools = []
            self.title.configure(text='Find your next shortcut.')
            self.summary.configure(text='Useful tools for everyday creative work. Browse a collection in the sidebar.')
            featured = ('speak', 'transcribe', 'pdf-merge', 'convert-image', 'convert-video', 'archive-extract')
            for index, key in enumerate(featured):
                tool = next(t for t in self.tools if t.key == key)
                tile = ctk.CTkFrame(self.cards, fg_color=('#ffffff', '#1C1C23'), corner_radius=12)
                tile.grid(row=index//3, column=index%3, sticky='nsew', padx=(0, 12), pady=(0, 12))
                ctk.CTkLabel(tile, text='', image=self._icons[section_for(tool)], anchor='w').pack(fill='x', padx=18, pady=(18, 8))
                ctk.CTkButton(tile, text=tool.title+'  ›', anchor='w', height=42, font=ctk.CTkFont(size=12, weight='bold'),
                              fg_color='transparent', text_color=('#282833', '#F0EFF6'), hover_color=('#EEEEF4', '#292932'),
                              command=lambda t=tool:self.open(t)).pack(fill='x', padx=8)
                ctk.CTkLabel(tile, text=tool.description, anchor='w', justify='left', wraplength=210,
                             font=ctk.CTkFont(size=11), text_color=('#777785', '#9493A3')).pack(fill='x', padx=18, pady=(0, 20))
            return
        if self.mode == 'library':
            self.library_back.grid()
            self.title.configure(text='Search results' if query else self.section or 'Tools')
            self.summary.configure(text='')
        matches = [t for t in self.candidates() if (query or self.section is None or in_section(t, self.section))
                   and query in f'{t.title} {t.description} {t.group} {t.key}'.casefold()]
        if self.mode != 'library':
            priority = {'transcribe': 1, 'pdf-merge': 1, 'data-convert': 1, 'subtitle-edit': 1, 'archive-extract': 1,
                        'ocr': 2, 'audio': 2, 'trim': 2, 'speak': 3, 'preview': 4}
            matches.sort(key=lambda t: 0 if t.key.startswith('convert-') else priority.get(t.key, 5))
        all_matches = matches
        if self.mode != 'library' and not query and not self.expanded:
            matches = matches[:4]
        self.visible_tools = [t.key for t in matches]
        self.cards.grid_columnconfigure(2, weight=0, uniform='', minsize=0)
        self.cards.grid_columnconfigure((0, 1), weight=1, uniform='tools')
        if not matches:
            ctk.CTkLabel(self.cards, text='No matching tools. Try another search or category.').grid(row=0, column=0, sticky='w')
        for index, tool in enumerate(matches):
            card = ctk.CTkFrame(self.cards, fg_color='transparent')
            card.grid(row=index // 2, column=index % 2, sticky='ew', padx=(0, 12), pady=(0, 8))
            button = ctk.CTkButton(card, text=f'{tool.title}   ›', image=self._icons[section_for(tool)], compound='left',
                                  anchor='w', font=ctk.CTkFont(size=14), corner_radius=9,
                                  fg_color=('#ffffff', '#1C1C23'), text_color=('#282833', '#F0EFF6'), hover_color=('#EEEEF4', '#292932'),
                                  height=54, command=lambda t=tool: self.open(t))
            button.pack(fill='x')
            if self.mode == 'files' and not self.expanded and not query:
                ctk.CTkLabel(card, text=tool.description, font=ctk.CTkFont(size=11), anchor='w', justify='left',
                             wraplength=360, text_color=('#777785', '#9493A3')).pack(fill='x', padx=16, pady=(6, 14))
            inputs = tool.inputs(self.selected_inputs())
            hint = ''
            if len(inputs) > 1 and not tool.multiple and self.mode != 'library':
                hint = 'Select one file above'
                button.configure(state='disabled')
            elif self.mode != 'library' and len(inputs) < len(self.selected_inputs()):
                hint = f'Applies to {len(inputs)} selected file(s)'
            if hint:
                ctk.CTkLabel(card, text=hint, font=ctk.CTkFont(size=11), text_color=('#777785', '#9493A3'), anchor='w').pack(fill='x', padx=12)
        if self.mode != 'library' and not query:
            extras = ctk.CTkFrame(self.cards, fg_color='transparent')
            extras.grid(row=(len(matches)+1)//2, column=0, columnspan=2, sticky='w', pady=(12, 0))
            if len(all_matches) > 4:
                ctk.CTkButton(extras, text='Fewer actions' if self.expanded else 'More actions', width=120, height=30,
                              fg_color='transparent', text_color=('#7561D4', '#B9ADF3'), command=self._toggle_more).pack(side='left', padx=(0, 16))
            ctk.CTkButton(extras, text='Change files', width=120, height=30, fg_color='transparent',
                          text_color=('#777785', '#9493A3'), command=self._change_files).pack(side='left')

    def _show_section(self, name):
        self.section = name
        self.query.set('')
        self.render_tools()
        self.reset_scroll()

    def _categories(self):
        self.section = None
        self.query.set('')
        self.cards.grid_columnconfigure((0, 1, 2), weight=1, uniform='tools')
        self.render_tools()

    def _toggle_more(self):
        self.expanded = not self.expanded
        self.render_tools()

    def _change_files(self):
        from tkinter import filedialog
        names = filedialog.askopenfilenames(parent=self.app, title='Choose files')
        if names:
            self.app._clear_all()
            self.app._ingest_image_paths([Path(name) for name in names])

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
    app._file_workspace = w = FileWorkspace(app, parent, queue, header, output, footer)
    app.grid_columnconfigure(0, weight=0)
    app.grid_columnconfigure(1, weight=1)
    top = header_right.master
    for child in top.winfo_children(): child.grid_remove()
    for child in app.winfo_children():
        if child is not top and child.winfo_manager() == 'grid' and child.grid_info().get('row') == 0:
            child.grid_remove()
    top.grid_configure(column=1)
    top.configure(height=58)
    top.grid_columnconfigure(0, weight=1)
    top.grid_columnconfigure(1, weight=0)
    app._content_shell.grid(row=1, column=1, sticky='nsew')
    parent.grid_configure(padx=32)
    bar = ctk.CTkFrame(top, fg_color='transparent')
    bar.grid(row=0, column=0, columnspan=3, sticky='ew', padx=32, pady=(16, 8))
    bar.grid_columnconfigure(0, weight=1)
    w.breadcrumb = ctk.CTkLabel(bar, text='Workspace  /  Home', anchor='w', font=ctk.CTkFont(size=11),
                               text_color=('#777785', '#9493A3'))
    w.breadcrumb.grid(row=0, column=0, sticky='w')
    ctk.CTkButton(bar, text='+  Add files', width=110, height=32, corner_radius=8, fg_color='transparent',
                  border_width=1, border_color=('#DDDDE7', '#33333E'), text_color=('#282833', '#d6d2e3'),
                  hover_color=('#EEEEF4', '#292932'), command=app._add_files).grid(row=0, column=1)
    sidebar = ctk.CTkFrame(app, width=204, corner_radius=0, fg_color=('#EEEEF4', '#19191F'))
    sidebar.grid(row=0, column=0, rowspan=2, sticky='nsew')
    sidebar.grid_propagate(False);sidebar.grid_columnconfigure(0, weight=1);sidebar.grid_rowconfigure(3, weight=1)
    brand = ctk.CTkFrame(sidebar, fg_color='transparent');brand.grid(row=0, column=0, sticky='ew', padx=20, pady=(27, 28))
    ctk.CTkLabel(brand, text='S', width=32, height=32, corner_radius=10, fg_color='#7561D4', text_color='#ffffff',
                 font=ctk.CTkFont(family='Outfit', size=20, weight='bold')).pack(side='left')
    ctk.CTkLabel(brand, text='shadow', font=ctk.CTkFont(family='Outfit', size=23, weight='bold')).pack(side='left', padx=10)
    nav = ctk.CTkFrame(sidebar, fg_color='transparent');nav.grid(row=1, column=0, sticky='ew', padx=12)
    w.nav_buttons = {}
    def choose(name, command):
        if app.conversion_running:return
        command()
        w.breadcrumb.configure(text='Workspace  /  '+name)
        for title, button in w.nav_buttons.items():
            button.configure(fg_color=('#E2DDF3', '#2B2639') if title == name else 'transparent',
                             text_color=('#6652C2', '#C8BEF3') if title == name else ('#777785', '#a8a5b5'))
    def nav_button(container, name, command, image=None):
        button=ctk.CTkButton(container, text=name, image=image, compound='left', anchor='w', height=36,
                             font=ctk.CTkFont(size=12), fg_color='transparent', text_color=('#777785', '#a8a5b5'),
                             hover_color=('#E5E2EE', '#25252E'), corner_radius=7, command=lambda:choose(name,command))
        button.pack(fill='x', pady=2);w.nav_buttons[name]=button
        return button
    def home():
        w.mode='home';w.converting=False;w.refresh();w.reset_scroll()
    nav_button(nav, 'Home', home)
    app.workspace_menu=nav_button(nav, 'Explore tools', w.show_library)
    nav_button(nav, 'History', app._open_history)
    ctk.CTkLabel(nav, text='TOOL COLLECTIONS', anchor='w', font=ctk.CTkFont(size=9, weight='bold'),
                 text_color=('#9993A6', '#757180')).pack(fill='x', padx=12, pady=(28, 10))
    for name in SECTIONS:
        if name == 'Settings':continue
        nav_button(nav, name, lambda n=name:(w.show_library(), w._show_section(n)), w._icons[name])
    bottom = ctk.CTkFrame(sidebar, fg_color='transparent');bottom.grid(row=4, column=0, sticky='ew', padx=12, pady=20)
    w.preferences = ctk.CTkFrame(parent, fg_color='transparent')
    w.preferences.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(w.preferences, text='Make yourself at home.', font=ctk.CTkFont(family='Outfit', size=30, weight='bold'),
                 anchor='w').grid(row=0, column=0, sticky='w', pady=(28, 8))
    ctk.CTkLabel(w.preferences, text='A few preferences. A workspace that feels like yours.', anchor='w',
                 text_color=('#777785', '#9493A3')).grid(row=1, column=0, sticky='w', pady=(0, 28))
    appearance=ctk.CTkFrame(w.preferences, corner_radius=14)
    appearance.grid(row=2, column=0, sticky='ew', pady=(0, 16));appearance.grid_columnconfigure(0,weight=1)
    ctk.CTkLabel(appearance, text='Appearance', font=ctk.CTkFont(size=15, weight='bold'), anchor='w').grid(row=0,column=0,sticky='w',padx=22,pady=(20,4))
    ctk.CTkLabel(appearance, text='Choose the light that works for you.', text_color=('#777785','#9493A3')).grid(row=1,column=0,sticky='w',padx=22,pady=(0,20))
    themes=ctk.CTkSegmentedButton(appearance, values=['Light','Dark','System'], command=app._set_theme)
    themes.set(app.theme_menu.get());themes.grid(row=0,column=1,rowspan=2,padx=22)
    for row,(label,copy,key) in enumerate((('Voices & models','Manage your local creative engines.','models'),('Engine status','Check that your tools are ready.','engines')),3):
        item=ctk.CTkFrame(w.preferences,corner_radius=14);item.grid(row=row,column=0,sticky='ew',pady=(0,12))
        ctk.CTkButton(item,text=label+'   ›',height=48,anchor='w',fg_color='transparent',text_color=('#282833','#F0EFF6'),
                      command=lambda k=key:app._open_studio_tools().open_tool(k,[])).pack(fill='x',padx=12,pady=(4,0))
        ctk.CTkLabel(item,text=copy,anchor='w',text_color=('#777785','#9493A3')).pack(fill='x',padx=22,pady=(0,16))
    def preferences():
        w.mode='preferences';w.refresh()
    nav_button(bottom,'Preferences',preferences,w._icons['Settings'])
    nav_button(bottom,'License',app._open_license_manager)
    nav_button(bottom,'About Shadow',app._open_about_dialog)
    ctk.CTkLabel(bottom,text='•  Private by design',anchor='w',font=ctk.CTkFont(size=10),
                 text_color=('#81758f','#8f859f')).pack(fill='x',padx=12,pady=(18,0))
    choose('Home',home)
    app.convert_button.configure(command=app._run_workspace_conversion)
    app.table.configure(height=3)
    for button in (app.preview_button, app.optimize_button, app.watch_folder_button, app.vip_downloader_button):button.pack_forget()
    app.add_button.configure(text='+ Add files')
