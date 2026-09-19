"""Verify stale host code cannot silently mask a successfully rolled out image."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/source_consistency.py'
spec = importlib.util.spec_from_file_location('source_consistency', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseSourceTests(unittest.TestCase):
    def test_only_exact_legacy_code_mounts_are_removed(self):
        original = '''services:
  web:
    volumes:
      - ${RETAILOPS_DATA_DIR:-/opt/retailops/artifacts}:/data
      - /opt/retailops/patches/retailops:/app/retailops:ro
      - /opt/retailops/patches/web:/app/web:ro
      - '/opt/retailops/patches/retailops_providers.py:/app/retailops_providers.py:ro'
      - /opt/retailops/patches/data:/app/data:ro
      - /opt/retailops/patches/evals:/app/evals:ro
      - /opt/retailops/patches/mcp_config.json:/app/mcp_config.json:ro
      - /elsewhere/retailops:/app/retailops:ro
      - /opt/retailops/patches/retailops:/app/retailops:rw
'''
        result = module.strip_legacy_code_mounts(original)
        self.assertNotIn('/patches/retailops:/app/retailops:ro', result)
        self.assertNotIn('/patches/web:', result)
        self.assertNotIn('/patches/retailops_providers.py:', result)
        for expected in ('${RETAILOPS_DATA_DIR', '/patches/data:', '/patches/evals:',
                         '/patches/mcp_config.json:', '/elsewhere/retailops:', ':rw'):
            self.assertIn(expected, result)
        self.assertEqual(module.strip_legacy_code_mounts(result), result)

    def test_source_digest_detects_changes_without_reading_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'retailops/workflow').mkdir(parents=True)
            (root / 'web').mkdir()
            (root / 'data').mkdir()
            (root / 'retailops_providers.py').write_text('# provider')
            worker = root / 'retailops/workflow/agent.py'
            worker.write_text('# version one')
            first = module.source_digest(root)
            (root / 'data/business.sqlite3').write_text('never read real data')
            self.assertEqual(first, module.source_digest(root))
            worker.write_text('# version two')
            self.assertNotEqual(first, module.source_digest(root))

    def test_incomplete_source_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                module.source_digest(Path(directory))

    def test_rollout_verifies_actual_source_and_restores_compose_on_rollback(self):
        script = (SCRIPT.parent / 'rollout-public-web.sh').read_text()
        self.assertIn('PUBLIC_WEB_SOURCE_MATCH', script)
        self.assertIn('docker exec "$active_container"', script)
        self.assertIn('cp -p "$compose_backup" compose.public.yaml', script)


if __name__ == '__main__':
    unittest.main()
