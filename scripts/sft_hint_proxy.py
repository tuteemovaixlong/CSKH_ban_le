"""Proxy gợi ý lúc sinh; không ghi nội dung lời nhắc hay thông tin xác thực."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_telemetry import safe_payload

START = '<<<GOI_Y_SINH_DU_LIEU>>>'
END = '<<<HET_GOI_Y>>>'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prompt_for_turn(case: dict, turn: dict) -> str:
    """Dùng cùng định dạng tin user mà ứng dụng gửi cho model."""
    if case.get('actor') == 'staff_case_assist':
        from retailops.workflow.case_assist import format_case_assist_user_prompt
        return format_case_assist_user_prompt(turn['mode'], turn['user'])
    return turn['user']


class HintIndex:
    def __init__(self, cases: list[dict], hints: list[dict], only: set[str] | None = None,
                 scopes: dict[str, set[str]] | None = None):
        self.matches = defaultdict(list)
        self.hints = {}
        self.cases = {case['id']: case for case in cases}
        self.scopes = scopes or {}
        for scope, ids in self.scopes.items():
            if not re.fullmatch(r'[A-Za-z0-9_-]+', scope) or not ids or ids - self.cases.keys():
                raise ValueError(f'Scope không hợp lệ hoặc chứa mã ca không tồn tại: {scope}')
        for case in cases:
            for number, turn in enumerate(case.get('turns') or [], 1):
                self.matches[prompt_for_turn(case, turn)].append((case['id'], number, case['meta']['template']))
        self.only = only
        for row in hints:
            kind = 'case_id' if row.get('case_id') else 'template'
            key = (kind, row[kind], row.get('turn'))
            if key in self.hints:
                raise ValueError(f'Gợi ý trùng khóa: {key}')
            digest = sha256(row['hint'].encode('utf-8'))
            if row.get('sha256') != digest:
                raise ValueError(f'SHA256 gợi ý không khớp: {key}')
            self.hints[key] = row['hint']

    def inject(self, payload: dict, scope: str | None = None) -> tuple[dict, dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get('messages', []), list):
            raise ValueError('Yêu cầu phải có danh sách messages')
        if not all(isinstance(m, dict) for m in payload.get('messages', [])):
            raise ValueError('Mỗi tin nhắn phải là object')
        users = [m for m in payload.get('messages', []) if m.get('role') == 'user']
        matches = self.matches.get(users[-1].get('content') if users and isinstance(users[-1].get('content'), str) else '', [])
        if scope is not None:
            allowed = self.scopes[scope]
            if self.only is not None:
                allowed = allowed & self.only
            matches = [match for match in matches if match[0] in allowed]
            if len(allowed) == 1 and len(matches) != 1:
                cid = next(iter(allowed))
                case = self.cases[cid]
                # Không suy đoán lượt trong ca nhiều lượt. T11 draft có một lượt.
                if len(case.get('turns') or []) == 1:
                    matches = [(cid, 1, case['meta']['template'])]
        info = {'case_id': None, 'turn': None, 'hinted': False, 'hint_sha256': None, 'reason': 'no_hint'}
        if len(matches) != 1:
            return payload, info
        cid, turn, template = matches[0]
        info.update(case_id=cid, turn=turn)
        if self.only is not None and cid not in self.only:
            return payload, info
        hint = next((self.hints[k] for k in (
            ('case_id', cid, turn), ('case_id', cid, None),
            ('template', template, turn), ('template', template, None)) if k in self.hints), None)
        systems = [m for m in payload.get('messages', []) if m.get('role') == 'system']
        if hint is None or not systems or not isinstance(systems[0].get('content'), str):
            return payload, info
        changed = copy.deepcopy(payload)
        system = next(m for m in changed['messages'] if m.get('role') == 'system')
        system['content'] += '\n\n' + START + '\n' + hint + '\n' + END
        info.update(hinted=True, hint_sha256=sha256(hint.encode('utf-8')), reason='hinted')
        return changed, info


def make_server(listen: tuple[str, int], upstream: str, index: HintIndex, log: Path,
                *, timeout: float = 600, ssl_context=None) -> ThreadingHTTPServer:
    if listen[0] != '127.0.0.1':
        raise ValueError('Proxy chỉ được nghe 127.0.0.1')
    parsed = urlsplit(upstream)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Upstream phải là HTTP/HTTPS, không chứa thông tin xác thực')
    lock = threading.Lock()
    hop = {'host', 'content-length', 'connection', 'transfer-encoding', 'keep-alive',
           'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'upgrade'}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            path = self.path
            scope = None
            if path.startswith('/s/'):
                match = re.fullmatch(r'/s/([A-Za-z0-9_-]+)(/.*)', path)
                if not match or match[1] not in index.scopes:
                    self.send_error(404, explain='Scope không tồn tại')
                    return
                scope, path = match[1], match[2]
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            original = body
            info = {'case_id': None, 'turn': None, 'hinted': False, 'hint_sha256': None, 'reason': 'no_hint'}
            if self.command == 'POST' and path == '/v1/chat/completions':
                try:
                    raw_payload = json.loads(body)
                    payload, info = index.inject(raw_payload, scope=scope)
                    if info['hinted']:
                        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                    info['trace_request_sha256'] = sha256(
                        json.dumps(safe_payload(raw_payload), ensure_ascii=False).encode('utf-8')
                    )
                except (ValueError, TypeError, KeyError):
                    self.send_error(400, explain='Yêu cầu JSON không hợp lệ')
                    return
            info.update(timestamp=datetime.now(timezone.utc).isoformat(), request_sha256=sha256(original))
            if scope is not None:
                info['scope'] = scope
            with lock:
                with log.open('a', encoding='utf-8', newline='\n') as fh:
                    fh.write(json.dumps(info, ensure_ascii=False) + '\n')
            headers = {k: v for k, v in self.headers.items() if k.lower() not in hop}
            request = urllib.request.Request(upstream.rstrip('/') + path, data=body if self.command == 'POST' else None,
                                             headers=headers, method=self.command)
            try:
                options = {'timeout': timeout}
                if ssl_context is not None:
                    options['context'] = ssl_context
                try:
                    response = urllib.request.urlopen(request, **options)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    data = response.read()
                    self.send_response(response.status)
                    for k, v in response.headers.items():
                        if k.lower() not in hop:
                            self.send_header(k, v)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except (OSError, urllib.error.URLError):
                self.send_error(502, explain='Không kết nối được upstream')

    return ThreadingHTTPServer(listen, Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listen', default='127.0.0.1:8002')
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--hints', required=True, type=Path)
    parser.add_argument('--log', required=True, type=Path)
    parser.add_argument('--only-file', type=Path)
    parser.add_argument('--scopes', type=Path, help='Thư mục <scope>.txt, mỗi dòng một case_id')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args(argv)
    read = lambda p: [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
    only = set(args.only_file.read_text(encoding='utf-8').split()) if args.only_file else None
    scopes = load_scopes(args.scopes) if args.scopes else None
    host, port = args.listen.rsplit(':', 1)
    server = make_server((host, int(port)), args.upstream, HintIndex(read(args.cases), read(args.hints), only, scopes),
                         args.log, timeout=args.timeout)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def load_scopes(directory: Path) -> dict[str, set[str]]:
    if not directory.is_dir():
        raise ValueError(f'Thư mục scope không tồn tại: {directory}')
    return {path.stem: set(path.read_text(encoding='utf-8-sig').split())
            for path in sorted(directory.glob('*.txt'))}


if __name__ == '__main__':
    raise SystemExit(main())
