"""Read-only report server on a private Docker network, behind Caddy basic_auth.

No database/model credential, Docker socket or execution endpoint is available here.
"""
import json
import os
from pathlib import Path
import re
from opsconsole.evaluation import load_json, SCHEMA

WEB = Path(__file__).parent / 'web'
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/admin.js': ('admin.js', 'text/javascript; charset=utf-8'),
          '/admin.css': ('admin.css', 'text/css; charset=utf-8')}
RUN_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')


class Console:
    def __init__(self, root, host):
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{2,252}', host):
            raise ValueError('Explicit admin hostname required')
        self.root = Path(root).resolve()
        self.host = host

    def read_run(self, run_id):
        if not RUN_ID.fullmatch(run_id):
            raise ValueError('Invalid run ID')
        path = self.root / 'runs' / run_id / 'report.json'
        if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(self.root / 'runs'):
            raise ValueError('Unsafe artifact path')
        result = load_json(path)
        if result.get('schema') != SCHEMA or result.get('run_id') != run_id:
            raise ValueError('Unsupported report')
        return result

    def route(self, env):
        path = env.get('PATH_INFO', '/')
        method = env.get('REQUEST_METHOD', '')
        if path == '/healthz' and method == 'GET':
            return 200, {'status': 'ok', 'service': 'retailops-admin', 'mode': 'read-only'}, None
        if env.get('HTTP_HOST') != self.host:
            return 403, {'error': 'invalid_host'}, None
        if method != 'GET':
            return 405, {'error': 'read_only_console'}, None
        if env.get('QUERY_STRING'):
            return 400, {'error': 'unexpected_query'}, None
        if path in ASSETS:
            name, mime = ASSETS[path]
            return 200, (WEB / name).read_bytes(), mime
        if path == '/api/runs':
            rows, invalid = [], 0
            root = self.root / 'runs'
            paths = sorted(root.iterdir(), key=lambda p: p.name, reverse=True) if root.exists() else []
            if len(paths) > 1000:
                paths = paths[:1000]
            for directory in paths:
                if directory.name.startswith('.'):
                    continue
                try:
                    run = self.read_run(directory.name)
                    rows.append({key: run[key] for key in ('run_id', 'kind', 'created_at', 'manifest', 'metrics')})
                except (ValueError, OSError, KeyError):
                    invalid += 1
            rows.sort(key=lambda r: r['created_at'], reverse=True)
            return 200, {'runs': rows[:100], 'invalid_reports': invalid, 'listing_limit': 100}, None
        if path.startswith('/api/runs/'):
            return 200, self.read_run(path.removeprefix('/api/runs/')), None
        if path == '/api/deployment':
            filename = self.root / 'deployment.json'
            if not filename.exists():
                return 200, {'available': False}, None
            if filename.is_symlink():
                raise ValueError('Unsafe snapshot path')
            return 200, load_json(filename), None
        if path == '/api/usage':
            filename = self.root / 'usage.json'
            if not filename.exists():
                return 200, {'schema': 'retailops-usage-v1', 'available': False}, None
            if filename.is_symlink():
                raise ValueError('Unsafe usage path')
            result = load_json(filename)
            if result.get('schema') != 'retailops-usage-v1':
                raise ValueError('Unsupported usage snapshot')
            return 200, result, None
        return 404, {'error': 'not_found'}, None

    def __call__(self, env, start_response):
        try:
            status, body, mime = self.route(env)
        except FileNotFoundError:
            status, body, mime = 404, {'error': 'report_not_found'}, None
        except (ValueError, OSError, KeyError, TypeError):
            status, body, mime = 503, {'error': 'report_unavailable'}, None
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        from http import HTTPStatus
        start_response(f'{status} {HTTPStatus(status).phrase}', [
            ('Content-Type', mime or 'application/json; charset=utf-8'), ('Content-Length', str(len(data))),
            ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
            ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
            ('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")])
        return [data]


if __name__ == '__main__':
    from waitress import serve
    serve(Console(os.environ.get('RETAILOPS_CONSOLE_DATA', '/console-data'), os.environ['RETAILOPS_ADMIN_HOST']),
          host='0.0.0.0', port=8100, threads=2, connection_limit=32,
          max_request_header_size=8192, max_request_body_size=1024, expose_tracebacks=False)
