import copy
import json
import re
import unittest

from retailops.workflow import compaction
from retailops.workflow.compaction import compact_tool_result, dump


class W641CompactionTests(unittest.TestCase):
    def test_phase_a_shrinks_strings_before_dropping_list_items_f44_regression(self):
        payload = {
            'items': [
                {'id': f'ORD-{i}', 'a': 'a' * 300, 'b': 'b' * 300, 'c': 'c' * 300}
                for i in range(3)
            ]
        }
        snapshot = copy.deepcopy(payload)
        text = compact_tool_result(payload, limit=950)
        self.assertEqual(payload, snapshot, 'compact_tool_result must not mutate input')
        self.assertLessEqual(len(text), 950)
        data = json.loads(text)
        self.assertIs(data.get('_truncated'), True)
        self.assertEqual(len(data['items']), 3)
        self.assertTrue(all(isinstance(item, dict) for item in data['items']))
        self.assertEqual([item['id'] for item in data['items']], ['ORD-0', 'ORD-1', 'ORD-2'])

    def test_phase_b_strips_nested_metadata_before_dropping_list_items(self):
        payload = {
            'orders': [
                {
                    'id': f'O-{i}',
                    'name': 'Sản phẩm mẫu ' + ('x' * 75),
                    'metadata': {'trace': 't' * 80, 'debug': 'd' * 80},
                }
                for i in range(5)
            ]
        }
        # Phase A at string_cap=80 leaves metadata intact (~1500 chars), Phase B strips metadata (~650 chars).
        text = compact_tool_result(payload, limit=850)
        self.assertLessEqual(len(text), 850)
        data = json.loads(text)
        self.assertIs(data.get('_truncated'), True)
        self.assertEqual(len(data['orders']), 5)
        for order in data['orders']:
            self.assertNotIn('metadata', order)

    def test_phase_b_preserves_top_level_note_and_strips_nested_low_value_keys(self):
        low_keys = ('description', 'image_url', 'images', 'note', 'notes', 'raw', 'metadata', 'as_of', 'source')
        self.assertEqual(tuple(getattr(compaction, 'LOW_VALUE_KEYS', ())), low_keys)
        payload = {
            'orders': [
                {
                    'id': f'O-{i}',
                    'description': 'mô tả ' + ('d' * 60),
                    'image_url': 'https://example.com/' + ('u' * 50),
                    'images': ['img1', 'img2'],
                    'note': 'nested note to drop',
                    'notes': ['n1'],
                    'raw': {'k': 'v' * 40},
                    'metadata': {'m': '1' * 40},
                    'as_of': '2026-11-15T10:00:00+07:00',
                    'source': 'retailops_db/orders',
                }
                for i in range(4)
            ],
            'nested_dict': {'note': 'drop nested dict note', 'keep': 'ok'},
            'note': 'Đang hiện 4/10 đơn gần nhất.',
        }
        # Phase A leaves nested low-value keys (> 1100 chars); Phase B removes them and fits within 450 chars.
        text = compact_tool_result(payload, limit=450)
        self.assertLessEqual(len(text), 450)
        data = json.loads(text)
        self.assertIs(data.get('_truncated'), True)
        self.assertEqual(data.get('note'), 'Đang hiện 4/10 đơn gần nhất.')
        self.assertNotIn('note', data['nested_dict'])
        self.assertEqual(data['nested_dict'].get('keep'), 'ok')
        self.assertEqual(len(data['orders']), 4)
        for order in data['orders']:
            for k in low_keys:
                self.assertNotIn(k, order)

    def test_phase_c_uses_vietnamese_hidden_count_note_when_lists_cut(self):
        payload = {
            'variants': [{'id': f'V-{i}', 'label': f'Biến thể {i}', 'sku': f'SKU-{i:04d}'} for i in range(30)]
        }
        text = compact_tool_result(payload, limit=800)
        self.assertLessEqual(len(text), 800)
        data = json.loads(text)
        self.assertIs(data.get('_truncated'), True)
        self.assertGreaterEqual(len(data['variants']), 3)  # at least 2 kept + 1 note
        note_elem = data['variants'][-1]
        self.assertIsInstance(note_elem, str)
        m = re.fullmatch(
            r'…\(còn (\d+) mục bị ẩn do giới hạn hiển thị; hỏi hẹp hơn hoặc dùng tool xem chi tiết\)',
            note_elem,
        )
        self.assertIsNotNone(m, f'Unexpected Phase C note element: {note_elem!r}')
        kept_count = len(data['variants']) - 1
        self.assertEqual(int(m.group(1)), 30 - kept_count)

    def test_compaction_invariants_across_limits(self):
        small = {'id': 'O-1', 'status': 'pending', 'note': 'ok'}
        self.assertEqual(compact_tool_result(small, limit=500), dump(small))

        large = {
            'rows': [
                {
                    'id': f'ROW-{i}',
                    'text': 'nội dung dài ' + ('abc ' * 80),
                    'metadata': {'extra': 'z' * 120},
                }
                for i in range(40)
            ],
            'note': 'keep top note when possible',
        }
        for limit in (200, 350, 800, 1500, 5200, 12000):
            with self.subTest(limit=limit):
                out = compact_tool_result(large, limit=limit)
                self.assertLessEqual(len(out), limit)
                parsed = json.loads(out)
                self.assertIsInstance(parsed, dict)
                self.assertIs(parsed.get('_truncated'), True)


if __name__ == '__main__':
    unittest.main()
