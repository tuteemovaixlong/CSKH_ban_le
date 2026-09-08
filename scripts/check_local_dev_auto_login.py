#!/usr/bin/env python3
"""Deterministic regression checks for token-free localhost development.

This intentionally exercises the private HTTP adapter with no model and no external
network. Public HTTPS/session behavior remains covered by the existing public tests
and live smoke suite.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.http.private import Server


def request(http, base, path, *, body=None, headers=None):
    payload = None if body is None else json.dumps(body).encode()
    merged = dict(headers or {})
    if body is not None:
        merged.setdefault('Content-Type', 'application/json')
        merged.setdefault('Origin', base)
    req = urllib.request.Request(base + path, data=payload, headers=merged)
    try:
        response = http.open(req, timeout=3)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        content_type = response.headers.get_content_type()
        return response.status, json.loads(raw) if content_type == 'application/json' else raw


def run_server(app, *, auto):
    server = Server(('127.0.0.1', 0), app, local_auto_login=auto)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, 'http://127.0.0.1:' + str(server.server_port)


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    if thread.is_alive():
        raise AssertionError('local test server did not stop')


def main():
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory() as temp:
        store = BusinessStore(Path(temp) / 'business.sqlite3')
        store.seed()

        # Auto-login is deliberately server-owned and loopback-only.
        app = Application(store, {})
        server, thread, base = run_server(app, auto=True)
        try:
            status, page = request(http, base, '/')
            assert status == 200
            assert b'data-auth="cookie"' in page
            assert b'data-local-auto-login="true"' in page

            status, session = request(http, base, '/api/session')
            assert status == 200
            assert session['customer_id'] == 'C-001'
            assert session['role'] == 'customer'

            status, orders = request(http, base, '/api/orders')
            assert status == 200
            assert [item['id'] for item in orders['orders']] == ['O-101', 'O-102']

            status, denied = request(http, base, '/api/orders', headers={'Host': 'evil.example'})
            assert status == 403
            assert denied['error'] == 'invalid_host'

            status, logout = request(http, base, '/api/logout', body={})
            assert status == 200 and logout['local_auto_login'] is True
        finally:
            stop_server(server, thread)

        # The normal private Server contract still requires bearer auth when the
        # explicit local-auto-login switch is not enabled.
        token = 't' * 40
        protected = Application(store, {hashlib.sha256(token.encode()).hexdigest(): 'C-001'})
        server, thread, base = run_server(protected, auto=False)
        try:
            status, denied = request(http, base, '/api/session')
            assert status == 401 and denied['error'] == 'unauthorized'
            status, session = request(http, base, '/api/session', headers={'Authorization': 'Bearer ' + token})
            assert status == 200 and session['customer_id'] == 'C-001'
        finally:
            stop_server(server, thread)

        try:
            Server(('0.0.0.0', 0), app, local_auto_login=True)
        except ValueError as exc:
            assert 'loopback' in str(exc).lower()
        else:
            raise AssertionError('local auto-login must reject non-loopback binds')

    print('LOCAL_DEV_AUTO_LOGIN_OK')


if __name__ == '__main__':
    main()
