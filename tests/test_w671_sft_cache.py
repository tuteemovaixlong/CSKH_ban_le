"""Bảo trì cache chỉ trên dữ liệu giả dạng token, không sinh lời khách."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.sft_utterances import drop_cache, migrate_injection


def write_jsonl(path, rows):
    path.write_bytes(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode('utf-8'))


class TestCacheMaintenance(unittest.TestCase):
    def setup_data(self, directory):
        old = [
            {'brief_id': 'keep', 'notes': 'A'},
            {'brief_id': 'redo', 'notes': 'B'},
            {'brief_id': 'inj', 'notes': 'C', 'injection': '[OLD]'},
            {'brief_id': 'both', 'notes': 'D', 'injection': '[OLD]'},
        ]
        current = [dict(b) for b in old]
        current[1]['notes'] = 'B2'
        current[2]['injection'] = '[NEW]'
        current[3].update(notes='D2', injection='[NEW]')
        old_path = directory / 'old.jsonl'
        write_jsonl(old_path, old)
        write_jsonl(directory / 'briefs_sft_v1.jsonl', current)
        cache = [dict(brief_id=b['brief_id'], user='AAA[OLD]ZZZ', writer='fixture-writer', model='fixture-model', extra=7)
                 for b in old]
        cache_path = directory / 'utterances_cache.jsonl'
        # Dòng không đổi có định dạng riêng và CRLF: phải giữ đúng từng byte.
        cache_path.write_bytes(b'\r\n'.join(json.dumps(r, ensure_ascii=False, indent=None).encode('utf-8')
                                           for r in cache) + b'\r\n')
        return old_path, cache_path

    @mock.patch('scripts.sft_utterances.urllib.request.urlopen', side_effect=AssertionError('không được gọi mạng'))
    def test_drop_and_migrate_preserve_other_lines_and_metadata(self, _network):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            old, cache = self.setup_data(directory)
            before = cache.read_bytes()
            old_before = old.read_bytes()
            result = drop_cache(directory, old)
            self.assertEqual(result['brief_ids'], ['both', 'redo'])
            self.assertEqual(result['removed'], 2)
            self.assertEqual(Path(result['backup']).read_bytes(), before)
            kept = before.splitlines(keepends=True)
            self.assertEqual(cache.read_bytes(), kept[0] + kept[2])
            result = migrate_injection(directory, old)
            self.assertEqual(result, {'migrated': 1, 'brief_ids': ['inj']})
            lines = cache.read_bytes().splitlines(keepends=True)
            self.assertEqual(lines[0], kept[0])
            row = json.loads(lines[1])
            self.assertEqual(row, dict(brief_id='inj', user='AAA[NEW]ZZZ', writer='fixture-writer',
                                      model='fixture-model', extra=7, migrated='injection'))
            self.assertEqual(old.read_bytes(), old_before)

    def test_migrate_rejects_zero_or_multiple_matches_without_partial_write(self):
        for payload in ('AAA', '[OLD][OLD]'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as td:
                directory = Path(td)
                old, cache = self.setup_data(directory)
                old_rows = [json.loads(x) for x in old.read_text().splitlines()]
                old_rows.append({'brief_id': 'bad', 'injection': '[OLD]'})
                write_jsonl(old, old_rows)
                current = [json.loads(x) for x in (directory / 'briefs_sft_v1.jsonl').read_text().splitlines()]
                current.append({'brief_id': 'bad', 'injection': '[NEW]'})
                write_jsonl(directory / 'briefs_sft_v1.jsonl', current)
                cache.write_bytes(cache.read_bytes() + (json.dumps({'brief_id': 'bad', 'user': payload}) + '\n').encode())
                before = cache.read_bytes()
                with self.assertRaisesRegex(ValueError, 'bad: injection cũ xuất hiện'):
                    migrate_injection(directory, old)
                self.assertEqual(cache.read_bytes(), before)

    def test_backup_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            old, cache = self.setup_data(directory)
            result = drop_cache(directory, old)
            before, backup = cache.read_bytes(), Path(result['backup']).read_bytes()
            with self.assertRaises(FileExistsError):
                drop_cache(directory, old)
            self.assertEqual(cache.read_bytes(), before)
            self.assertEqual(Path(result['backup']).read_bytes(), backup)

    def test_duplicate_briefs_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            old, cache = self.setup_data(directory)
            old.write_bytes(old.read_bytes() * 2)
            before = cache.read_bytes()
            with self.assertRaisesRegex(ValueError, 'trùng brief_id'):
                drop_cache(directory, old)
            self.assertEqual(cache.read_bytes(), before)
            self.assertFalse((directory / 'utterances_cache.before_drop.jsonl').exists())

    def test_added_and_removed_briefs_are_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            write_jsonl(directory / 'old.jsonl', [{'brief_id': 'removed'}])
            write_jsonl(directory / 'briefs_sft_v1.jsonl', [{'brief_id': 'added'}])
            write_jsonl(directory / 'utterances_cache.jsonl', [{'brief_id': b, 'user': 'TOKEN'}
                                                              for b in ('removed', 'added')])
            result = drop_cache(directory, directory / 'old.jsonl')
            self.assertEqual(result['brief_ids'], ['added', 'removed'])
            self.assertEqual((directory / 'utterances_cache.jsonl').read_bytes(), b'')

    def test_t11_email_only_keeps_clean_cache_but_drops_other_changes_or_contamination(self):
        previous = 'ketoan-uynhiem-181@fake-retailops-mail.com'
        following = 'ketoan-uynhiem-181@thanhtoan-ncc.example'
        for payload, extra, drop in [
            ('TOKEN', False, False), ('TOKEN', True, True),
            (previous, False, True), (following, False, True), ('retailops-mail', False, True),
            ('RETAILOPS-MAIL', False, True),
        ]:
            with self.subTest(payload=payload, extra=extra), tempfile.TemporaryDirectory() as td:
                directory = Path(td)
                before = {'brief_id': 't11', 'template': 't11_pdf_email_la', 'notes': 'A',
                          'must_not_include': [previous, '<draft_reply>']}
                after = dict(before, must_not_include=[following, '<draft_reply>'])
                if extra:
                    after['notes'] = 'B'
                write_jsonl(directory / 'old.jsonl', [before])
                write_jsonl(directory / 'briefs_sft_v1.jsonl', [after])
                cache = directory / 'utterances_cache.jsonl'
                write_jsonl(cache, [dict(brief_id='t11', user=payload, writer='fixture', model='fixture')])
                original = cache.read_bytes()
                result = drop_cache(directory, directory / 'old.jsonl')
                self.assertEqual(result['removed'], int(drop))
                self.assertEqual(result['retained_t11_brief_ids'], [] if drop else ['t11'])
                self.assertEqual(cache.read_bytes(), b'' if drop else original)

    def test_t11_requires_other_bytes_identical_and_never_applies_to_other_templates(self):
        previous = 'ketoan-uynhiem-1@fake-retailops-mail.com'
        following = 'ketoan-uynhiem-1@thanhtoan-ncc.example'
        for template, alter_whitespace in [('t11_pdf_email_la', True), ('other', False)]:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as td:
                directory = Path(td)
                row = {'brief_id': 'b', 'template': template, 'must_not_include': [previous]}
                write_jsonl(directory / 'old.jsonl', [row])
                row['must_not_include'] = [following]
                current = directory / 'briefs_sft_v1.jsonl'
                write_jsonl(current, [row])
                if alter_whitespace:
                    current.write_bytes(b' ' + current.read_bytes())
                write_jsonl(directory / 'utterances_cache.jsonl', [{'brief_id': 'b', 'user': 'TOKEN'}])
                self.assertEqual(drop_cache(directory, directory / 'old.jsonl')['removed'], 1)


if __name__ == '__main__':
    unittest.main()
