"""Composition root: configuration -> gateways -> identity/storage -> HTTP adapter.

Only this module wires concrete backends for process startup. Business transactions
remain usable without an HTTP server, model credentials or a login session.
"""
import hashlib

from retailops.config import Settings
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.identity.demo import GuestSessions
from retailops.identity.persistent import PersistentSessions
from retailops.integration.connectors import warn_unready_connectors_on_startup
from retailops.http.private import Server
from retailops.http.public import PublicWeb
from retailops.models import build_gateways


def build_public_app(settings: Settings | None = None) -> PublicWeb:
    settings = settings or Settings.from_environment('public')
    if settings.interface != 'public':
        raise ValueError('Public startup requires public settings.')
    gateways = build_gateways(settings)  # Validate all enabled adapters before writing data.
    if settings.data_mode in ('persistent-demo', 'production', 'live'):
        if settings.storage_backend == 'postgresql':
            from retailops.identity.postgres import PostgresSessions
            sessions = PostgresSessions(settings.database_url, gateways.custom, gateways.api,
                                         settings.api_daily_turn_limit, data_mode=settings.data_mode,
                                         default_tenant_id=settings.demo_tenant_id or None,
                                         data_root=settings.output)
        else:
            sessions = PersistentSessions(settings.output/'persistent', gateways.custom, gateways.api,
                                          settings.api_daily_turn_limit, data_mode=settings.data_mode,
                                          default_tenant_id=settings.demo_tenant_id or None)
    else:
        sessions = GuestSessions(settings.output/'public-guests', settings.access_token,
                                 gateways.custom, gateways.api, settings.api_daily_turn_limit)
    tcfg = settings.case_timer_config
    sessions.case_timer_config = tcfg
    if settings.customer_ref_key:
        sessions.customer_ref_key = settings.customer_ref_key
    warn_unready_connectors_on_startup(sessions)
    return PublicWeb(settings.origin, sessions, start_timer_worker=True, timer_scan_seconds=tcfg.scan_seconds)


def build_private_app(settings: Settings | None = None) -> Application:
    settings = settings or Settings.from_environment('private')
    if settings.interface != 'private':
        raise ValueError('Private startup requires private settings.')
    gateways = build_gateways(settings)
    store = BusinessStore(settings.output/'business.sqlite3')
    store.data_mode = settings.data_mode
    store.tenant_id = 'default'
    store.data_root = settings.output
    store.case_timer_config = settings.case_timer_config
    if settings.customer_ref_key:
        store.customer_ref_key = settings.customer_ref_key
    store.seed()
    token_hash = hashlib.sha256(settings.access_token.encode()).hexdigest()
    return Application(store, {token_hash: 'C-001'}, gateways.custom, gateways.api, settings.api_daily_turn_limit)


def serve_public():
    from waitress import serve
    from retailops.core import CHAT_ATTACHMENT_JSON_MAX_BYTES
    app = build_public_app()
    print('RetailOps synthetic HTTPS backend ready; awaiting Caddy.', flush=True)
    serve(app, host='0.0.0.0', port=8000, threads=8, connection_limit=100,
          channel_timeout=30, max_request_header_size=16384, max_request_body_size=CHAT_ATTACHMENT_JSON_MAX_BYTES,
          clear_untrusted_proxy_headers=True, expose_tracebacks=False, ident='RetailOps')


def serve_private():
    settings = Settings.from_environment('private')
    app = build_private_app(settings)
    print('RetailOps synthetic API started; model configured:', app.infer is not None, flush=True)
    with Server((settings.bind, settings.port), app) as server:
        server.serve_forever()
