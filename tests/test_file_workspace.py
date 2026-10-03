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
