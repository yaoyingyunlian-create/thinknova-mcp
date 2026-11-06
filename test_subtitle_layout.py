"""Subtitle safety tests; no accounts, generation or publishing."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'render'))
from captions import safe_subtitle_text
import assemble
import tempfile

class SubtitleLayoutTests(unittest.TestCase):
    def test_cjk_wrap_and_long_tokens(self):
        for text in ['这是一条较长的中文字幕需要自动换行显示', 'W' * 28, '这是 English mixed 混合文本测试']:
            result = safe_subtitle_text(text, 1080, 1920, 72, 537)
            self.assertIn(r'\N', result)
            self.assertLessEqual(result.count(r'\N'), 1)
    def test_unrenderable_text_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SUBTITLE_TOO_LONG'):
            safe_subtitle_text('字' * 1000, 1080, 1920, 72, 537)
    def test_explicit_lines_and_override_safety(self):
        result = safe_subtitle_text('{bad}第一行\n第二行', 1080, 1920, 72, 537)
        self.assertIn(r'\N', result)
        self.assertNotIn('{bad}', result)
    def test_assemble_uses_safe_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'captions.ass')
            assemble.write_ass(path, {}, [{'start':0,'end':3,'text':'长字幕' * 8}], None, 'Arial')
            data = Path(path).read_text(encoding='utf-8')
            self.assertIn('WrapStyle: 0',data)
            self.assertIn(r'\N',data)
