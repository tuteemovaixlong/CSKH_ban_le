"""Only generated blocks can change; knowledge drift is detected by the same renderer."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import build_eval_pack as build


class BuildPackTests(unittest.TestCase):
    def test_compact_order_table_and_completed_refund_group(self):
        blocks = build.generate()
        # The production test image excludes thesis prose; source-checkout CI checks the full file.
        self.assertLess(sum(len(block.encode('utf-8')) for block in blocks.values()), 150000)
        if build.TARGET.is_file():
            text = build.replace_blocks(build.TARGET.read_text(encoding='utf-8'), blocks)
            self.assertLess(len(text.encode('utf-8')), 150000)
        table = blocks['customers_orders']
        self.assertIn('| Khách | Tên hiển thị | Mã đơn |', table)
        refunded = next(line for line in table.splitlines() if line.startswith('| đã hoàn tiền |'))
        self.assertIn('SIM-O-', refunded)
        self.assertNotIn('Không có', refunded)
        order_rows = [line for line in table.splitlines() if line.startswith('| SIM-C-')]
        self.assertEqual(len(order_rows), 128)
        self.assertEqual(len({line.split('|')[3].strip() for line in order_rows}), 128)
        self.assertNotIn('"internal_order_id"', blocks['tool_results'])
        self.assertIn('"tool":', blocks['tool_results'])

    def test_refund_summary_classification_and_remaining_days(self):
        self.assertEqual(build.refund_groups({'latest_status': 'completed', 'refunded_total': 0}), ['đã hoàn tiền'])
        self.assertEqual(build.refund_groups({'latest_status': 'failed', 'refunded_total': 100}),
                         ['đã hoàn tiền', 'hoàn tiền thất bại hoặc đang chờ'])
        for status in ('failed', 'pending', 'processing'):
            self.assertEqual(build.refund_groups({'latest_status': status}), ['hoàn tiền thất bại hoặc đang chờ'])
        self.assertEqual(build.refund_groups(None), [])
        result = build.eligibility_text(dict(can_self_service_cancel=False, days_since_delivery=3.25,
            within_return_window=True, return_window_days=7, within_size_exchange_window=True,
            size_exchange_window_days=15, within_warranty=True, warranty_window_days=90))
        self.assertEqual(result, 'hủy: không; trả: còn 3.8 ngày; đổi size: còn 11.8 ngày; bảo hành: còn 86.8 ngày')

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
