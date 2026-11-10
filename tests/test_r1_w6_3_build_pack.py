"""Only generated blocks can change; knowledge drift is detected by the same renderer."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import build_eval_pack as build


class BuildPackTests(unittest.TestCase):
    def test_preserves_handwritten_bytes_and_requires_unique_markers(self):
        text = 'Handwritten\n<!-- BEGIN GENERATED: x -->\nold\n<!-- END GENERATED: x -->\nEnd\n'
        expected = text.replace('\nold\n', '\nnew\n')
        self.assertEqual(build.replace_blocks(text, {'x': 'new'}), expected)
        with self.assertRaises(ValueError):
            build.replace_blocks(text + text, {'x': 'new'})

    def test_generation_is_stable_and_knowledge_edit_drifts(self):
        first = build.generate()
        self.assertEqual(first, build.generate())
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for source in build.KNOWLEDGE.glob('*.md'):
                (folder / source.name).write_bytes(source.read_bytes())
            source = folder / 'returns.md'
            source.write_text(source.read_text(encoding='utf-8') + '\nMột chữ đổi.\n', encoding='utf-8')
            with patch.object(build, 'KNOWLEDGE', folder):
                changed = build.generate()
            self.assertNotEqual(first['knowledge'], changed['knowledge'])
            with patch.object(build, 'TARGET', folder / 'target.md'), patch.object(build, 'generate', return_value=changed):
                template = '\n'.join(f'<!-- BEGIN GENERATED: {k} -->\n<!-- END GENERATED: {k} -->' for k in first)
                build.TARGET.write_text(build.replace_blocks(template, first), encoding='utf-8')
                self.assertEqual(build.main(['--check']), 1)
