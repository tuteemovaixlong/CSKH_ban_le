"""The shared reason catalog must ship in the image and gate health (W3.2 production incident 2026-11-03).

The W3.2 image started without data/order_action_reasons.json: /healthz stayed 200, so the rollout passed,
while every signed-in request failed with 400. These tests keep the file in the build context and make a
missing or broken catalog fail health, so a rollout of such an image rolls back by itself.
"""
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops import order_reasons
from retailops_public import GuestSessions, PublicWeb

ROOT = Path(__file__).resolve().parents[1]
INVITE = 'fixture_invite_' + 'c' * 40
ORIGIN = 'https://retailops.example.com'


class HealthGatesReasonCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.web = PublicWeb(ORIGIN, GuestSessions(Path(temp.name) / 'public-guests', INVITE),
                             start_timer_worker=False)
        order_reasons.reset_catalog_cache()
        self.addCleanup(order_reasons.reset_catalog_cache)

    def healthz(self):
        env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/healthz', 'QUERY_STRING': '',
               'HTTP_HOST': 'retailops.example.com', 'HTTP_ORIGIN': ORIGIN, 'HTTP_COOKIE': '',
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': '0', 'wsgi.input': io.BytesIO(b'')}
        captured = {}

        def start(status, headers):
            captured['status'] = int(status.split()[0])

        body = json.loads(b''.join(self.web(env, start)))
        return captured['status'], body

    def test_health_is_ok_with_the_shipped_catalog(self):
        status, body = self.healthz()
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], 'ok')

    def test_missing_catalog_fails_health_with_503(self):
        missing = ROOT / 'data' / 'does_not_exist_order_action_reasons.json'
        with patch.object(order_reasons, 'CATALOG_PATH', missing):
            order_reasons.reset_catalog_cache()
            status, body = self.healthz()
        self.assertEqual(status, 503)
        self.assertEqual(body['error'], 'reason_catalog_unavailable')

    def test_invalid_catalog_fails_health_with_503(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / 'order_action_reasons.json'
            broken.write_text('{not json', encoding='utf-8')
            with patch.object(order_reasons, 'CATALOG_PATH', broken):
                order_reasons.reset_catalog_cache()
                status, body = self.healthz()
        self.assertEqual(status, 503)
        self.assertEqual(body['error'], 'reason_catalog_unavailable')


@unittest.skipUnless((ROOT / '.dockerignore').is_file() and (ROOT / '.github').is_dir(),
                     'repository build files are not shipped in the image; checked on the source tree')
class ReasonCatalogShipsInImageTests(unittest.TestCase):
    def test_every_copied_data_path_is_explicitly_allowed_by_dockerignore(self):
        allowed = {line.strip() for line in (ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()}
        sources = re.findall(r'^COPY\s+(data/\S+)\s', (ROOT / 'Dockerfile').read_text(encoding='utf-8'), re.M)
        self.assertIn('data/order_action_reasons.json', sources)
        for source in sources:
            if (ROOT / source).is_dir():
                self.assertIn('!' + source.rstrip('/') + '/', allowed, f'{source} is copied but not allowed')
            else:
                self.assertIn('!' + source, allowed, f'{source} is copied but not allowed')

    def test_both_image_checks_require_the_catalog(self):
        for workflow in ('ci.yml', 'deploy-ec2.yml'):
            text = (ROOT / '.github' / 'workflows' / workflow).read_text(encoding='utf-8')
            self.assertIn('test -f /app/data/order_action_reasons.json', text, workflow)


if __name__ == '__main__':
    unittest.main()
