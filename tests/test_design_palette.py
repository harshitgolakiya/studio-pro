import ast
from pathlib import Path
import unittest


class DesignPaletteTests(unittest.TestCase):
    def test_auxiliary_windows_do_not_embed_legacy_brand_colors(self):
        root = Path(__file__).resolve().parents[1]
        legacy = {'#16a394', '#12877a', '#17a594', '#0e756b', '#059669',
                  '#16a34a', '#d4a03c', '#e8b750', '#d8f3ef', '#123a36',
                  '#facc15', '#eab308', '#1d4ed8', '#70e1d4'}
        names = ('main.py', 'workspace_ui.py', 'studio_dialog.py',
                 'url_downloader_dialog.py', 'watch_folder_dialog.py',
                 'video_trimmer_dialog.py', 'license_dialog.py',
                 'preview_modal.py', 'optimizer_dialog.py', 'recipe_dialog.py',
                 'format_browser.py', 'command_palette.py', 'history_dialog.py')
        for name in names:
            with self.subTest(window=name):
                tree = ast.parse((root / name).read_text(encoding='utf-8'))
                colors = {node.value.lower() for node in ast.walk(tree)
                          if isinstance(node, ast.Constant) and isinstance(node.value, str)}
                self.assertFalse(colors & legacy, colors & legacy)
