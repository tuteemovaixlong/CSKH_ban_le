"""Host cutover failure handling without operating on the developer's Docker daemon."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class CutoverTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1]/'deploy/migrate-public-postgres.py'
        if not path.exists():
            self.skipTest('Host deploy helper is not part of the Colab runtime bundle.')
        spec = importlib.util.spec_from_file_location('cutover_fixture', path)
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old = Path.cwd(); self.addCleanup(os.chdir, old)
        self.data = self.root/'data'; (self.data/'public-guests').mkdir(parents=True)
        (self.data/'public-guests/control.sqlite3').write_bytes(b'fixture')
        for name in ('public.env','deployed.env','compose.public.yaml','Caddyfile'):
            (self.root/name).write_text('RETAILOPS_IMAGE=ready-image\n')
        self.current = {'Config':{'Env':[], 'Image':'old-image'}, 'Mounts':[{'Source':str(self.data),'Destination':'/data'}]}
        self.calls = []

    def fake_run(self, args):
        self.calls.append(args)
        if args[:2] == ['docker','inspect']:
            return json.dumps([self.current])
        if args[:2] == ['docker','run']:
            return '0.10'
        if args[:2] == ['docker','create']:
            return 'fixture-extraction'
        if 'up' in args and args[-1] == 'postgres':
            raise RuntimeError('fixture start failure')
        return ''

    def test_refuses_nonroot_without_docker_or_file_changes(self):
        with patch.object(self.module.os,'geteuid',return_value=1000), patch.object(self.module,'run') as run:
            with self.assertRaises(ValueError):
                self.module.migrate(self.root, 'retailops.example.test')
            run.assert_not_called()

    def test_refuses_guest_workspaces_before_stopping_web(self):
        (self.data/'public-guests/session.sqlite3').write_bytes(b'guest')
        with patch.object(self.module.os,'geteuid',return_value=0), patch.object(self.module,'run',side_effect=self.fake_run):
            with self.assertRaises(ValueError):
                self.module.migrate(self.root, 'retailops.example.test')
        self.assertEqual(len(self.calls),1)
        self.assertFalse((self.root/'backups').exists())

    def test_guest_login_race_after_preflight_rolls_back_before_database_init(self):
        def racing(args):
            result = self.fake_run(args)
            if args[-2:] == ['stop','web']:
                (self.data/'public-guests/new-session.sqlite3').write_bytes(b'new guest')
            return result
        with patch.object(self.module.os,'geteuid',return_value=0), patch.object(self.module,'run',side_effect=racing):
            with self.assertRaises(RuntimeError):
                self.module.migrate(self.root, 'retailops.example.test')
        self.assertFalse(any(args[-1:] == ['postgres'] for args in self.calls))
        self.assertEqual((self.data/'public-guests/new-session.sqlite3').read_bytes(),b'new guest')

    def test_failure_preserves_source_backup_and_restores_active_image(self):
        before = (self.root/'public.env').read_text()
        with patch.object(self.module.os,'geteuid',return_value=0), patch.object(self.module,'run',side_effect=self.fake_run):
            with self.assertRaises(RuntimeError):
                self.module.migrate(self.root, 'retailops.example.test')
        backups = list((self.root/'backups').iterdir())
        self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/'public-guests/control.sqlite3').read_bytes(), b'fixture')
        self.assertEqual((self.data/'public-guests/control.sqlite3').read_bytes(), b'fixture')
        self.assertEqual((self.root/'public.env').read_text(),before)
        self.assertIn('old-image', (backups[0]/'runtime.env').read_text())
        self.assertIn(str(backups[0]/'runtime.env'), self.calls[-1])
        self.assertNotIn('--volumes', sum(self.calls, []))
