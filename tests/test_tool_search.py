import unittest
from file_context import tool_catalog
from tool_search import search_tools


class ToolSearchTests(unittest.TestCase):
    def setUp(self):self.tools = tool_catalog()

    def keys(self, query):return [tool.key for tool in search_tools(self.tools, query)]

    def test_everyday_phrases_find_the_right_tool_first(self):
        cases = {'transcript':'transcribe', 'voiceover':'speak', 'make video smaller':'convert-video',
                 'word to pdf':'convert-document', 'remove noise':'audio', 'unzip':'archive-extract',
                 'combine PDF files':'pdf-merge', 'scan to text':'ocr', 'cut video':'trim'}
        for query, key in cases.items():
            with self.subTest(query=query):self.assertEqual(self.keys(query)[0], key)

    def test_exact_names_preserve_conversion_direction(self):
        self.assertEqual(self.keys('text to audio'), ['speak'])
        self.assertEqual(self.keys('audio to text'), ['transcribe'])
        self.assertEqual(self.keys('pdf-merge'), ['pdf-merge'])

    def test_words_match_in_any_order_and_ignore_filler(self):
        self.assertEqual(self.keys('please reduce the size of my video')[0], 'convert-video')
        self.assertEqual(self.keys('video transcript')[0], 'transcribe')

    def test_conservative_typo_and_prefix_matching(self):
        self.assertEqual(self.keys('transcibe')[0], 'transcribe')
        self.assertIn('subtitle-edit', self.keys('subtit'))
        self.assertEqual(self.keys('unicorn spaceship'), [])
        self.assertEqual(self.keys('please the'), [])

    def test_search_does_not_expand_input_or_favorite_scope(self):
        scoped = [tool for tool in self.tools if tool.key == 'speak']
        self.assertEqual(search_tools(scoped, 'transcript'), [])
        self.assertEqual(search_tools(scoped, 'voiceover'), scoped)
        self.assertEqual(search_tools(scoped, ''), scoped)
