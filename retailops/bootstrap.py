"""Composition root: configuration -> gateways -> identity/storage -> HTTP adapter.

Only this module wires concrete backends for process startup. Business transactions
remain usable without an HTTP server, model credentials or a login session.
"""
import hashlib

from retailops.config import Settings
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.identity.demo import GuestSessions
from retailops.http.private import Server
from retailops.http.public import PublicWeb
from retailops.models import build_gateways


def build_public_app(settings: Settings | None = None) -> PublicWeb:
    settings = settings or Settings.from_environment('public')
    if settings.interface != 'public':
        raise ValueError('Public startup requires public settings.')
    gateways = build_gateways(settings)  # Validate all enabled adapters before writing data.
    sessions = GuestSessions(settings.output/'public-guests', settings.access_token,
                             gateways.custom, gateways.api, settings.api_daily_turn_limit)
    return PublicWeb(settings.origin, sessions)


def build_private_app(settings: Settings | None = None) -> Application:
    settings = settings or Settings.from_environment('private')
    if settings.interface != 'private':
        raise ValueError('Private startup requires private settings.')
    gateways = build_gateways(settings)
    store = BusinessStore(settings.output/'business.sqlite3')
    store.seed()
    token_hash = hashlib.sha256(settings.access_token.encode()).hexdigest()
    return Application(store, {token_hash: 'C-001'}, gateways.custom, gateways.api, settings.api_daily_turn_limit)


def serve_public():
    from waitress import serve
    app = build_public_app()
    print('RetailOps synthetic HTTPS backend ready; awaiting Caddy.', flush=True)
    serve(app, host='0.0.0.0', port=8000, threads=8, connection_limit=100,
          channel_timeout=30, max_request_header_size=16384, max_request_body_size=16384,
          clear_untrusted_proxy_headers=True, expose_tracebacks=False, ident='RetailOps')


def serve_private():
    settings = Settings.from_environment('private')
    app = build_private_app(settings)
    print('RetailOps synthetic API started; model configured:', app.infer is not None, flush=True)
    with Server((settings.bind, settings.port), app) as server:
        server.serve_forever()
