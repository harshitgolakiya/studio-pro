from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _headless

from file_context import file_tags, tool_catalog
from studio_actions import ACTION_LABELS


class FileContextTests(unittest.TestCase):
    def test_every_existing_action_is_discoverable(self):
        keys = [t.key for t in tool_catalog()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(set(ACTION_LABELS).issubset(keys))

    def test_mixed_inputs_are_explicitly_filtered_per_tool(self):
        paths = [Path('photo.png'), Path('voice.wav'), Path('document.pdf'), Path('bundle.zip')]
        tools = {t.key: t for t in tool_catalog()}
        self.assertEqual(tools['transcribe'].inputs(paths), [paths[1]])
        self.assertEqual(tools['ocr'].inputs(paths), [paths[0], paths[2]])
        self.assertEqual(tools['archive-extract'].inputs(paths), [paths[3]])
        self.assertEqual(tools['convert-image'].inputs(paths), [paths[0]])

    def test_spreadsheet_exposes_data_and_office_but_subtitles_do_not(self):
        self.assertTrue({'data', 'office', 'document', 'workbook'}.issubset(file_tags(Path('budget.xlsx'))))
        tools = {t.key: t for t in tool_catalog()}
        self.assertFalse(tools['data-export-sheets'].inputs([Path('table.csv')]))
        self.assertEqual(tools['subtitle-edit'].inputs([Path('captions.srt')]), [Path('captions.srt')])
        self.assertFalse(tools['ocr'].inputs([Path('recording.wav')]))


class WorkspaceFlowTests(unittest.TestCase):
    def setUp(self):
        import main
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.enterContext(patch('settings.SETTINGS_FILE', Path(self.tmp.name) / 'settings.json'))
        with patch.object(main.WebPCompressorApp, '_show_setup_status_if_needed'), patch.object(main.WebPCompressorApp, '_show_missing_runtime_warning_if_needed'):
            self.app = main.WebPCompressorApp()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def add(self, names):
        paths = [Path(self.tmp.name) / n for n in names]
        for path in paths: path.write_bytes(b'fixture')
        self.app._ingest_image_paths(paths)
        return [p.resolve() for p in paths]

    def test_empty_home_and_context_after_import_and_clear(self):
        workspace = self.app._file_workspace
        self.assertEqual(workspace.home.winfo_manager(), 'grid')
        self.assertEqual(self.app.settings_tabview.winfo_manager(), '')
        self.assertEqual(workspace.queue.winfo_manager(), '')
        self.add(['recording.wav', 'captions.srt', 'delivery.zip'])
        self.assertIn('transcribe', workspace.visible_tools)
        self.assertIn('subtitle-edit', workspace.visible_tools)
        self.assertIn('archive-extract', workspace.visible_tools)
        self.assertNotIn('ocr', workspace.visible_tools)
        self.app._clear_all()
        self.assertEqual(workspace.home.winfo_manager(), 'grid')
        self.assertEqual(workspace.browser.winfo_manager(), '')

    def test_conversion_uses_only_matching_inputs_and_returns_to_actions(self):
        paths = self.add(['recording.wav', 'photo.png'])
        workspace = self.app._file_workspace
        workspace.open(next(t for t in workspace.tools if t.key == 'convert-audio'))
        self.assertEqual(self.app._conversion_inputs, [paths[0]])
        self.assertEqual(self.app.settings_tabview.winfo_manager(), 'grid')
        self.assertNotIn('Watermark', self.app.settings_tabview._segmented_button.cget('values'))
        with patch.object(self.app, '_start_conversion') as start:
            self.app._run_workspace_conversion()
        start.assert_called_once_with(only=[paths[0]])
        workspace.back_to_actions()
        self.assertEqual(self.app.settings_tabview.winfo_manager(), '')
        self.assertEqual(workspace.browser.winfo_manager(), 'grid')

    def test_action_opens_matching_form_with_inputs_already_selected(self):
        paths = self.add(['captions.srt'])
        workspace = self.app._file_workspace
        workspace.open(next(t for t in workspace.tools if t.key == 'subtitle-edit'))
        dialog = self.app._studio_dialog
        panel = dialog.panels['Advanced workflows']
        self.assertEqual(dialog.tabs.get(), 'Advanced workflows')
        self.assertEqual(panel.sources, paths)
        self.assertEqual(panel.action.get(), ACTION_LABELS['subtitle-edit'])
        dialog.show_page('Data')
        dialog.show_page('Text to Audio')
        self.app.update()
        self.assertEqual(dialog.tabs.get(), 'Text to Audio')
        dialog.destroy()

    def test_tool_library_exposes_creation_without_input(self):
        workspace = self.app._file_workspace
        workspace.show_library()
        workspace.query.set('text to audio')
        workspace.render_tools()
        self.assertEqual(workspace.visible_tools, ['speak'])
        workspace.open(next(t for t in workspace.tools if t.key == 'speak'))
        self.assertEqual(self.app._studio_dialog.tabs.get(), 'Text to Audio')
        self.app._studio_dialog.destroy()

    def test_categories_and_search_keep_all_tools_accessible(self):
        from workspace_ui import SECTIONS
        workspace = self.app._file_workspace
        workspace.show_library()
        self.assertEqual(workspace.visible_tools, [])
        discovered = set()
        for section in SECTIONS:
            workspace._show_section(section)
            discovered.update(workspace.visible_tools)
        self.assertEqual(discovered, {t.key for t in workspace.tools})
        workspace._show_section('Video')
        self.assertIn('subtitle-edit', workspace.visible_tools)
        self.assertIn('transcribe', workspace.visible_tools)
        workspace._categories()
        self.assertEqual(workspace.visible_tools, [])

    def test_one_file_shows_four_actions_and_more_is_available(self):
        self.add(['recording.wav'])
        workspace = self.app._file_workspace
        self.assertEqual(workspace.queue.winfo_manager(), '')
        self.assertEqual(len(workspace.visible_tools), 4)
        self.assertEqual(workspace.filters.winfo_manager(), '')
        workspace._toggle_more()
        self.assertIn('audio-isolate', workspace.visible_tools)
        workspace._toggle_more()
        self.assertEqual(len(workspace.visible_tools), 4)
        before = list(self.app.selected_files)
        with patch('tkinter.filedialog.askopenfilenames', return_value=()):
            workspace._change_files()
        self.assertEqual(self.app.selected_files, before)

    def test_sidebar_navigation_preserves_files_and_opens_preferences(self):
        self.add(['recording.wav'])
        workspace = self.app._file_workspace
        before = list(self.app.selected_files)
        workspace.nav_buttons['Preferences'].invoke()
        self.assertEqual(workspace.preferences.winfo_manager(), 'grid')
        self.assertEqual(workspace.browser.winfo_manager(), '')
        workspace.nav_buttons['Home'].invoke()
        self.assertEqual(workspace.home.winfo_manager(), 'grid')
        self.assertEqual(workspace.preferences.winfo_manager(), '')
        self.assertEqual(self.app.selected_files, before)
        workspace.nav_buttons['Audio'].invoke()
        self.assertEqual(workspace.section, 'Audio')
        self.assertIn('speak', workspace.visible_tools)
        self.assertEqual(workspace.home.winfo_manager(), '')
        self.assertTrue(workspace.breadcrumb.cget('text').endswith('Audio'))
        self.app.conversion_running = True
        try:
            workspace.nav_buttons['Preferences'].invoke()
            self.assertEqual(workspace.mode, 'library')
            self.assertEqual(workspace.section, 'Audio')
        finally:
            self.app.conversion_running = False

    def test_collection_groups_and_cached_rows_stay_in_order(self):
        workspace = self.app._file_workspace
        with patch.object(workspace, 'render_tools', wraps=workspace.render_tools) as render:
            workspace.nav_buttons['Video'].invoke()
        self.assertEqual(render.call_count, 1)
        self.assertEqual(workspace.tool_groups, ['Convert & edit', 'Audio & transcription', 'Subtitles'])
        keys = workspace.visible_tools
        self.assertLess(keys.index('trim'), keys.index('transcribe'))
        self.assertLess(keys.index('transcribe'), keys.index('subtitle-edit'))
        previous = workspace._tool_rows['trim'][0]
        workspace.nav_buttons['Audio'].invoke()
        workspace.nav_buttons['Video'].invoke()
        self.assertIs(workspace._tool_rows['trim'][0], previous)
        self.assertEqual(workspace.visible_tools, keys)

    def test_search_coalesces_fast_typing(self):
        import time
        workspace = self.app._file_workspace
        workspace.show_library()
        with patch.object(workspace, 'render_tools') as render:
            for query in ('s', 'su', 'sub', 'subtitle'):
                workspace.query.set(query)
                workspace._schedule_search()
            self.assertEqual(render.call_count, 0)
            deadline = time.monotonic() + .2
            while time.monotonic() < deadline:
                self.app.update()
                time.sleep(.005)
            render.assert_called_once()

    def test_completion_opens_actual_output_and_handles_removed_file(self):
        from converter import ConversionResult
        source = self.add(['photo.png'])[0]
        output = Path(self.tmp.name) / 'actual-output.webp'
        output.write_bytes(b'output')
        workspace = self.app._file_workspace
        workspace.open(next(t for t in workspace.tools if t.key == 'convert-image'))
        result = ConversionResult(source, output, 100, 60, '40%', 'Completed')
        workspace.show_batch_result([result], False, 1.2)
        self.assertEqual(workspace.result_card.winfo_manager(), 'grid')
        self.assertNotEqual(workspace.result_card.grid_info()['row'], workspace.queue.grid_info()['row'])
        self.assertEqual(workspace.result_title.cget('text'), 'Your files are ready')
        self.assertEqual(self.app.settings_tabview.winfo_manager(), '')
        self.assertEqual(workspace.output.winfo_manager(), '')
        with patch('utils.open_file_or_folder') as opened:
            workspace.result_open.invoke()
            opened.assert_called_once_with(output)
            output.unlink()
            workspace.result_open.invoke()
            self.assertEqual(opened.call_count, 1)
        self.assertIn('moved or deleted', self.app.status_text.get())
        workspace.back_to_actions()
        self.assertEqual(workspace.result_card.winfo_manager(), '')

    def test_partial_and_cancelled_batches_do_not_claim_all_files_ready(self):
        from converter import ConversionResult
        source, second = self.add(['first.png', 'second.png'])
        output = Path(self.tmp.name) / 'first.webp'
        output.write_bytes(b'output')
        workspace = self.app._file_workspace
        workspace.open(next(t for t in workspace.tools if t.key == 'convert-image'))
        results = [ConversionResult(source, output, 100, 50, '50%', 'Completed'),
                   ConversionResult(second, None, 100, None, '-', 'Failed', 'bad input')]
        for result in results:self.app._display_result(result)
        self.app.events.put(('complete', (results, False, 2.0)))
        with patch('main.record_batch'), patch('main.play_completion_sound'):
            self.app._process_events()
        self.assertEqual(workspace.result_title.cget('text'), 'Some files need attention')
        self.assertIn('1 failed', workspace.result_detail.cget('text'))
        with patch.object(self.app, '_start_conversion') as start:
            workspace.result_retry.invoke()
        start.assert_called_once_with(only=[second])
        workspace.show_batch_result([], True, .1)
        self.assertEqual(workspace.result_title.cget('text'), 'Conversion stopped')
        self.assertEqual(workspace.result_open.winfo_manager(), '')
        self.assertEqual(workspace.result_card.winfo_manager(), 'grid')
        self.app._clear_all()
        self.assertIsNone(workspace._batch_result)

    def test_favorites_save_order_and_remove_without_losing_other_settings(self):
        import settings
        settings.update_setting('theme', 'Light')
        workspace = self.app._file_workspace
        workspace.nav_buttons['Audio'].invoke()
        workspace._favorite_buttons['speak'].invoke()
        workspace._favorite_buttons['transcribe'].invoke()
        workspace.nav_buttons['Favorites'].invoke()
        self.assertEqual(workspace.visible_tools, ['speak', 'transcribe'])
        self.assertEqual(settings.load_settings()['favorite_tools'], ['speak', 'transcribe'])
        self.assertEqual(settings.load_settings()['theme'], 'Light')
        workspace._favorite_buttons['speak'].invoke()
        self.assertEqual(workspace.visible_tools, ['transcribe'])
        self.assertEqual(settings.load_settings()['favorite_tools'], ['transcribe'])
        workspace._favorite_buttons['transcribe'].invoke()
        self.assertEqual(workspace.visible_tools, [])
        self.assertIn('No favorites yet', workspace._layout_items[0][1].cget('text'))

    def test_favorites_survive_restart_and_ignore_obsolete_or_invalid_keys(self):
        import settings, main
        settings.update_setting('favorite_tools', ['speak', 'removed-tool', 'speak', None, 'transcribe'])
        self.app.destroy()
        with patch.object(main.WebPCompressorApp, '_show_setup_status_if_needed'), patch.object(main.WebPCompressorApp, '_show_missing_runtime_warning_if_needed'):
            restored = main.WebPCompressorApp()
        restored.withdraw()
        try:
            workspace = restored._file_workspace
            workspace.nav_buttons['Favorites'].invoke()
            self.assertEqual(workspace.visible_tools, ['speak', 'transcribe'])
            with patch.object(restored, '_open_studio_tools', wraps=restored._open_studio_tools):
                workspace._tool_rows['speak'][1].invoke()
            self.assertEqual(restored._studio_dialog.tabs.get(), 'Text to Audio')
            restored._studio_dialog.destroy()
        finally:restored.destroy()

    def test_favorite_search_is_scoped_and_write_failure_keeps_session_working(self):
        workspace = self.app._file_workspace
        with patch('settings.update_setting', return_value=False):
            workspace._toggle_favorite('speak')
        self.assertIn('this session', self.app.status_text.get())
        workspace.nav_buttons['Favorites'].invoke()
        workspace.query.set('transcribe');workspace.render_tools()
        self.assertEqual(workspace.visible_tools, [])
        workspace.query.set('voice');workspace.render_tools()
        self.assertEqual(workspace.visible_tools, ['speak'])
        workspace.show_library('Audio')
        self.assertEqual(workspace._favorite_buttons['speak'].cget('text'), '\u2605')
