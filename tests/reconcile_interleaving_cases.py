"""Shared P1.1 TOCTOU regression scenario: another principal grabs a target customer id AFTER the
Step 1 preflight of reconcile_collision(). Executed against both SQLite and PostgreSQL backends
(see test_pr_a_correctness.py and test_postgres.py). Not collected directly by unittest.

The interleaving is injected deterministically by wrapping sessions.control: the hook for the
N-th Identity write transaction runs right before that transaction opens, i.e. after the
previous one committed (#1 = Step 1 preflight/reservation, #2 = Step 2 lock, #3 = Step 3).
"""
import io
import json
import time
from contextlib import contextmanager

from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.reconcile import (_validate_business_targets, get_reconciliation_status,
                                          reconcile_collision)

COLLIDING = 'CG-ilv-shared'
TARGET_A = 'CG-ilv-alice'
TARGET_B = 'CG-ilv-bob'
INTRUDER_OWN = 'CG-ilv-intruder-own'
KEY = 'rec-ilv-toctou'


class _FaultInjectionConnectionContext:
    def __init__(self, orig_ctx, fault_fn):
        self._orig_ctx = orig_ctx
        self._fault_fn = fault_fn

    def __enter__(self):
        self._db = self._orig_ctx.__enter__()
        return _FaultInjectionDB(self._db, self._fault_fn)

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._orig_ctx.__exit__(exc_type, exc_val, exc_tb)


class _FaultInjectionDB:
    def __init__(self, db, fault_fn):
        self._db = db
        self._fault_fn = fault_fn

    def execute(self, statement, parameters=()):
        self._fault_fn(statement, parameters)
        return self._db.execute(statement, parameters)

    def __getattr__(self, name):
        return getattr(self._db, name)


@contextmanager
def inject_identity_fault(control, fault_fn):
    orig_conn = control.connection

    def patched_conn(write=False):
        return _FaultInjectionConnectionContext(orig_conn(write=write), fault_fn)

    control.connection = patched_conn
    try:
        yield
    finally:
        control.connection = orig_conn


class _InterleavingControl:
    def __init__(self, inner, hooks):
        self._inner = inner
        self._hooks = hooks
        self.writes = 0

    def connection(self, write=False):
        if write:
            self.writes += 1
            hook = self._hooks.get(self.writes)
            if hook:
                hook()
        return self._inner.connection(write=write)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class InterleavingSessions:
    def __init__(self, inner, hooks):
        self._inner = inner
        self.control = _InterleavingControl(inner.control, hooks)

    def business_store(self, tenant_id):
        return self._inner.business_store(tenant_id)


def seed(sessions, tenant):
    now = time.time()
    with sessions.control.connection(write=True) as db:
        for pid, name in (('p-ilv-a', 'ILV Alice'), ('p-ilv-b', 'ILV Bob'), ('p-ilv-intruder', 'ILV Intruder')):
            db.execute('INSERT INTO principals (id, name) VALUES (?, ?)', (pid, name))
        for mid, pid, cid in (('m-ilv-a', 'p-ilv-a', COLLIDING), ('m-ilv-b', 'p-ilv-b', COLLIDING),
                              ('m-ilv-intruder', 'p-ilv-intruder', INTRUDER_OWN)):
            db.execute(
                'INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) '
                "VALUES (?, ?, ?, ?, 'customer', 1, 1)", (mid, tenant, pid, cid))
        db.execute('INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                   'VALUES (?, ?, ?, ?, ?)', ('cl-ilv-intruder', tenant, 'p-ilv-intruder', INTRUDER_OWN, now))
        db.execute('INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?, ?, ?)',
                   (tenant, COLLIDING, now))
    with sessions.business_store(tenant).connection(write=True) as b:
        for cid, name in ((COLLIDING, 'ILV Shared'), (INTRUDER_OWN, 'ILV Intruder')):
            b.execute('INSERT INTO customers (id, name) VALUES (?, ?)', (cid, name))
        for oid, cid in (('O-ILV-A', COLLIDING), ('O-ILV-B', COLLIDING), ('O-ILV-INTRUDER', INTRUDER_OWN)):
            b.execute("INSERT INTO orders (id, customer_id, name, variant, amount, status, version) "
                      "VALUES (?, ?, 'Item', 'M', 1000, 'pending', 1)", (oid, cid))
        for conv, cid, oid in (('conv-ilv-a', COLLIDING, 'O-ILV-A'), ('conv-ilv-intruder', INTRUDER_OWN, 'O-ILV-INTRUDER')):
            b.execute('INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) '
                      'VALUES (?, ?, ?, NULL, 1, ?)', (conv, cid, oid, now + 3600))
        b.execute('INSERT INTO agent_turns (conversation_id, customer_id, request_id, input_hash, messages, result, created_at) '
                  'VALUES (?, ?, ?, ?, ?, ?, ?)', ('conv-ilv-a', COLLIDING, 'req-ilv-a', 'h-ilv', '[]', '{}', now))
        b.execute('INSERT INTO conversation_feedback (conversation_id, customer_id, feedback_type, rating, created_at) '
                  "VALUES (?, ?, 'turn_rating', 5, ?)", ('conv-ilv-a', COLLIDING, now))
        b.execute('INSERT INTO proposals (id, customer_id, order_id, order_version, reason, expires_at) '
                  'VALUES (?, ?, ?, 1, ?, ?)', ('prop-ilv-a', COLLIDING, 'O-ILV-A', 'ILV cancel', now + 3600))
        b.execute('INSERT INTO business_events (customer_id, created_at, kind, order_id, payload) '
                  "VALUES (?, ?, 'order_created', ?, '{}')", (COLLIDING, now, 'O-ILV-A'))


def plan():
    return {'reassignments': [
        {'membership_id': 'm-ilv-a', 'target_customer_id': TARGET_A, 'target_customer_name': 'ILV Alice',
         'order_ids': ['O-ILV-A'], 'conversation_ids': ['conv-ilv-a']},
        {'membership_id': 'm-ilv-b', 'target_customer_id': TARGET_B, 'target_customer_name': 'ILV Bob',
         'order_ids': ['O-ILV-B'], 'conversation_ids': []},
    ]}


def snapshot(sessions, tenant):
    """Every customer-scoped row the reconciliation can touch (bound LIKE patterns for psycopg)."""
    with sessions.control.connection() as db:
        identity = {
            'members': {r['id']: (r['customer_id'], r['auth_version'], r['active']) for r in db.execute(
                'SELECT id, customer_id, auth_version, active FROM memberships WHERE id LIKE ?', ('m-ilv-%',)).fetchall()},
            'links': {r['principal_id']: r['customer_id'] for r in db.execute(
                'SELECT principal_id, customer_id FROM customer_links WHERE principal_id LIKE ?', ('p-ilv-%',)).fetchall()},
            'unresolved': sorted(r['customer_id'] for r in db.execute(
                'SELECT customer_id FROM unresolved_collisions WHERE tenant_id = ?', (tenant,)).fetchall()),
        }
    with sessions.business_store(tenant).connection() as b:
        business = {
            'customers': {r['id']: r['name'] for r in b.execute(
                'SELECT id, name FROM customers WHERE id LIKE ?', ('CG-ilv-%',)).fetchall()},
            'orders': {r['id']: r['customer_id'] for r in b.execute(
                'SELECT id, customer_id FROM orders WHERE id LIKE ?', ('O-ILV-%',)).fetchall()},
            'conversations': {r['id']: r['customer_id'] for r in b.execute(
                'SELECT id, customer_id FROM conversations WHERE id LIKE ?', ('conv-ilv-%',)).fetchall()},
            'agent_turns': {r['request_id']: r['customer_id'] for r in b.execute(
                'SELECT request_id, customer_id FROM agent_turns WHERE request_id LIKE ?', ('req-ilv-%',)).fetchall()},
            'conversation_feedback': sorted((r['conversation_id'], r['customer_id'], r['feedback_type']) for r in b.execute(
                'SELECT conversation_id, customer_id, feedback_type FROM conversation_feedback WHERE conversation_id LIKE ?',
                ('conv-ilv-%',)).fetchall()),
            'proposals': {r['id']: r['customer_id'] for r in b.execute(
                'SELECT id, customer_id FROM proposals WHERE id LIKE ?', ('prop-ilv-%',)).fetchall()},
            'business_events': sorted((r['order_id'], r['customer_id'], r['kind']) for r in b.execute(
                'SELECT order_id, customer_id, kind FROM business_events WHERE order_id LIKE ?', ('O-ILV-%',)).fetchall()),
        }
    return {'identity': identity, 'business': business}


def _identity_write(sessions, statements):
    with sessions.control.connection(write=True) as db:
        for sql, params in statements:
            db.execute(sql, params)


def _business_write(sessions, tenant, statements):
    with sessions.business_store(tenant).connection(write=True) as b:
        for sql, params in statements:
            b.execute(sql, params)


def _intrusions(sessions, tenant):
    """Non-cooperative writers (raw SQL that bypasses the repository) taking TARGET_A after the
    preflight. Each entry: (apply, revert)."""
    now = time.time()
    return {
        'membership_takeover': (
            lambda: _identity_write(sessions, [(
                'UPDATE memberships SET customer_id = ? WHERE id = ?', (TARGET_A, 'm-ilv-intruder'))]),
            lambda: _identity_write(sessions, [(
                'UPDATE memberships SET customer_id = ? WHERE id = ?', (INTRUDER_OWN, 'm-ilv-intruder'))]),
        ),
        'customer_link_takeover': (
            lambda: _identity_write(sessions, [(
                'UPDATE customer_links SET customer_id = ? WHERE tenant_id = ? AND principal_id = ?',
                (TARGET_A, tenant, 'p-ilv-intruder'))]),
            lambda: _identity_write(sessions, [(
                'UPDATE customer_links SET customer_id = ? WHERE tenant_id = ? AND principal_id = ?',
                (INTRUDER_OWN, tenant, 'p-ilv-intruder'))]),
        ),
        'business_customers_row': (
            lambda: _business_write(sessions, tenant, [(
                'INSERT INTO customers (id, name) VALUES (?, ?)', (TARGET_A, 'ILV Squatter'))]),
            lambda: _business_write(sessions, tenant, [(
                'DELETE FROM customers WHERE id = ?', (TARGET_A,))]),
        ),
        # PostgreSQL enforces customers(id) FKs, so the squatter row comes with its feedback row.
        'business_feedback_row': (
            lambda: _business_write(sessions, tenant, [
                ('INSERT INTO customers (id, name) VALUES (?, ?)', (TARGET_A, 'ILV Squatter')),
                ('INSERT INTO conversation_feedback (conversation_id, customer_id, feedback_type, rating, created_at) '
                 "VALUES (?, ?, 'session_csat', 1, ?)", ('conv-ilv-intruder', TARGET_A, now)),
            ]),
            lambda: _business_write(sessions, tenant, [
                ('DELETE FROM conversation_feedback WHERE customer_id = ?', (TARGET_A,)),
                ('DELETE FROM customers WHERE id = ?', (TARGET_A,)),
            ]),
        ),
    }


def _request(web, path, cookie='', method='GET', body=None):
    raw = json.dumps(body).encode() if body is not None else b''
    env = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path,
        'QUERY_STRING': '',
        'HTTP_HOST': 'retailops.example.com',
        'HTTP_ORIGIN': 'https://retailops.example.com',
        'HTTP_COOKIE': cookie,
        'CONTENT_TYPE': 'application/json',
        'CONTENT_LENGTH': str(len(raw)),
        'wsgi.input': io.BytesIO(raw),
    }
    captured = {}

    def start(status, headers):
        captured['status'] = int(status.split()[0])
        captured['headers'] = dict(headers)

    resp_body = b''.join(web(env, start))
    if captured.get('headers', {}).get('Content-Type', '').startswith('application/json'):
        resp_data = json.loads(resp_body)
    else:
        resp_data = resp_body
    return captured.get('status'), resp_data


def _assert_collision_blocked(case, sessions):
    for mid in ('m-ilv-a', 'm-ilv-b'):
        with case.assertRaises(ApiError) as blocked:
            sessions.control.create_session_for_membership(mid, 3600, 10)
        case.assertEqual((blocked.exception.status, blocked.exception.code), (503, 'collision_unresolved'))


def run(case, sessions, tenant):
    """case: unittest.TestCase. sessions: PersistentSessions or PostgresSessions."""
    seed(sessions, tenant)
    before = snapshot(sessions, tenant)
    case.assertIn(COLLIDING, before['identity']['unresolved'])
    case.assertNotIn(TARGET_A, before['identity']['unresolved'])

    # 1. A raw writer takes TARGET_A between the preflight (Step 1) and the Business commit.
    for label, (apply, revert) in _intrusions(sessions, tenant).items():
        with case.subTest(intrusion=label):
            seen = {}

            def after_preflight(label=label, apply=apply):
                with sessions.control.connection() as db:
                    seen['reserved'] = {r['customer_id'] for r in db.execute(
                        'SELECT customer_id FROM unresolved_collisions WHERE tenant_id = ?', (tenant,)).fetchall()}
                # Cooperative writers must refuse the reserved id.
                try:
                    sessions.control.create_membership(tenant, f'p-ilv-coop-{label}', 'ILV Coop', TARGET_A, 'customer')
                    seen['coop'] = 'accepted'
                except ApiError as exc:
                    seen['coop'] = (exc.status, exc.code)
                apply()
                seen['at_intrusion'] = snapshot(sessions, tenant)

            with case.assertRaises(ApiError) as ctx:
                reconcile_collision(InterleavingSessions(sessions, {2: after_preflight}), tenant, COLLIDING, plan(),
                                    idempotency_key=KEY)
            case.assertEqual((ctx.exception.status, ctx.exception.code), (409, 'target_customer_conflict'))
            # The reservation was in place right after the preflight and was honoured.
            case.assertTrue({TARGET_A, TARGET_B} <= seen['reserved'])
            case.assertEqual(seen['coop'], (409, 'customer_reserved'))
            after = snapshot(sessions, tenant)
            # Stopped before moving data: every customer-scoped Business row (customers,
            # orders, conversations, agent_turns, conversation_feedback, proposals,
            # business_events) and every membership/link is exactly as the intruder left it.
            case.assertEqual(after['business'], seen['at_intrusion']['business'])
            case.assertEqual(after['identity']['members'], seen['at_intrusion']['identity']['members'])
            case.assertEqual(after['identity']['links'], seen['at_intrusion']['identity']['links'])
            # Collision stays unresolved, reservations are released, journal is not stuck.
            case.assertEqual(after['identity']['unresolved'], before['identity']['unresolved'])
            case.assertIsNone(get_reconciliation_status(sessions, KEY))
            _assert_collision_blocked(case, sessions)
            if label == 'business_feedback_row':
                # The feedback row alone is foreign data even when the customers-row rule is off.
                with sessions.business_store(tenant).connection() as b:
                    with case.assertRaises(ApiError) as fb:
                        _validate_business_targets(b, plan()['reassignments'], set(), fresh_run=False)
                case.assertEqual(fb.exception.code, 'target_customer_conflict')
            revert()
            case.assertEqual(snapshot(sessions, tenant), before)

    # 2. Cooperative writers during the window are refused/diverted; a raw membership takeover
    #    after the Business commit is caught by the Step 3 re-check (fail-closed, resumable).
    seen = {}
    web = PublicWeb('https://retailops.example.com', sessions)

    # Pre-takeover: intruder has an existing valid session issued before the intrusion
    intruder_token = sessions.control.create_session_for_membership('m-ilv-intruder', 3600, 10)
    intruder_cookie = f'{sessions.cookie_name}={intruder_token}'

    # Before takeover, intruder session resolves normally and sees intruder's own orders
    with sessions.resolve(intruder_cookie) as binding:
        case.assertEqual(binding.customer_id, INTRUDER_OWN)
    status, data = _request(web, '/api/orders', cookie=intruder_cookie)
    case.assertEqual(status, 200)
    case.assertEqual([o['id'] for o in data['orders']], ['O-ILV-INTRUDER'])

    def before_step2():
        try:
            sessions.control.create_membership(tenant, 'p-ilv-coop-final', 'ILV Coop', TARGET_A, 'customer')
            seen['coop'] = 'accepted'
        except ApiError as exc:
            seen['coop'] = (exc.status, exc.code)
        _, seen['google_cid'] = sessions.control.get_or_create_google_member(
            tenant, 'ilv.google@example.com', 'ILV Google', customer_id=TARGET_A, sub='sub-ilv-google')

    takeover, undo_takeover = _intrusions(sessions, tenant)['membership_takeover']
    with case.assertRaises(ApiError) as late:
        reconcile_collision(InterleavingSessions(sessions, {2: before_step2, 3: takeover}), tenant, COLLIDING,
                            plan(), idempotency_key=KEY)
    case.assertEqual((late.exception.status, late.exception.code), (409, 'target_customer_conflict'))
    case.assertEqual(seen['coop'], (409, 'customer_reserved'))
    case.assertNotEqual(seen['google_cid'], TARGET_A)
    case.assertEqual(get_reconciliation_status(sessions, KEY)['status'], 'business_committed')
    mid_state = snapshot(sessions, tenant)
    case.assertEqual(mid_state['identity']['members']['m-ilv-a'], before['identity']['members']['m-ilv-a'])
    case.assertEqual(mid_state['identity']['members']['m-ilv-b'], before['identity']['members']['m-ilv-b'])
    case.assertTrue({COLLIDING, TARGET_A, TARGET_B} <= set(mid_state['identity']['unresolved']))
    _assert_collision_blocked(case, sessions)

    # P1.1 regression: Pre-existing session must fail-closed after takeover while TARGET_A is unresolved.
    # Intruder's session must NOT resolve and GET /api/orders must NOT return moved orders (O-ILV-A).
    with case.assertRaises(ApiError) as res_err:
        with sessions.resolve(intruder_cookie) as binding:
            pass
    case.assertEqual((res_err.exception.status, res_err.exception.code), (503, 'collision_unresolved'))

    status, orders_after_takeover = _request(web, '/api/orders', cookie=intruder_cookie)
    case.assertEqual(status, 503)
    case.assertEqual(orders_after_takeover.get('error'), 'collision_unresolved')
    case.assertNotIn('orders', orders_after_takeover)

    # Collision and journal remain safe (unresolved, business_committed).
    case.assertEqual(get_reconciliation_status(sessions, KEY)['status'], 'business_committed')
    case.assertTrue({COLLIDING, TARGET_A, TARGET_B} <= set(snapshot(sessions, tenant)['identity']['unresolved']))

    undo_takeover()
    result = reconcile_collision(sessions, tenant, COLLIDING, plan(), idempotency_key=KEY)
    case.assertEqual(result['status'], 'completed')
    case.assertEqual(get_reconciliation_status(sessions, KEY)['status'], 'completed')
    final = snapshot(sessions, tenant)
    ident, biz = final['identity'], final['business']
    case.assertEqual(ident['members']['m-ilv-a'][0], TARGET_A)
    case.assertEqual(ident['members']['m-ilv-b'][0], TARGET_B)
    case.assertEqual(ident['members']['m-ilv-intruder'], before['identity']['members']['m-ilv-intruder'])
    case.assertEqual(ident['links'], {'p-ilv-a': TARGET_A, 'p-ilv-b': TARGET_B, 'p-ilv-intruder': INTRUDER_OWN})
    case.assertFalse({COLLIDING, TARGET_A, TARGET_B} & set(ident['unresolved']))
    case.assertEqual(biz['customers'], {TARGET_A: 'ILV Alice', TARGET_B: 'ILV Bob', COLLIDING: 'ILV Shared',
                                        INTRUDER_OWN: 'ILV Intruder'})
    case.assertEqual(biz['orders'], {'O-ILV-A': TARGET_A, 'O-ILV-B': TARGET_B, 'O-ILV-INTRUDER': INTRUDER_OWN})
    case.assertEqual(biz['conversations'], {'conv-ilv-a': TARGET_A, 'conv-ilv-intruder': INTRUDER_OWN})
    case.assertEqual(biz['agent_turns'], {'req-ilv-a': TARGET_A})
    case.assertEqual(biz['conversation_feedback'], [('conv-ilv-a', TARGET_A, 'turn_rating')])
    case.assertEqual(biz['proposals'], {'prop-ilv-a': TARGET_A})
    case.assertEqual(biz['business_events'], [('O-ILV-A', TARGET_A, 'order_created')])

    # After completion and undo: intruder session resolves to INTRUDER_OWN again and sees only O-ILV-INTRUDER
    with sessions.resolve(intruder_cookie) as binding:
        case.assertEqual(binding.customer_id, INTRUDER_OWN)
    status, data = _request(web, '/api/orders', cookie=intruder_cookie)
    case.assertEqual(status, 200)
    case.assertEqual([o['id'] for o in data['orders']], ['O-ILV-INTRUDER'])

    # Alice can now create session and access her newly reconciled orders O-ILV-A
    alice_secret = sessions.control.create_session_for_membership('m-ilv-a', 3600, 10)
    alice_cookie = f'{sessions.cookie_name}={alice_secret}'
    status, data = _request(web, '/api/orders', cookie=alice_cookie)
    case.assertEqual(status, 200)
    case.assertEqual([o['id'] for o in data['orders']], ['O-ILV-A'])

    case.assertTrue(reconcile_collision(sessions, tenant, COLLIDING, plan(), idempotency_key=KEY).get('already_completed'))

    # 3. P1.1b: customer_links.customer_id differs from memberships.customer_id and is unresolved.
    #    IdentityStore.resolve() must refuse with 503 collision_unresolved (ApiError not swallowed).
    link_test_pid = 'p-ilv-link-mismatch'
    link_test_mid = 'm-ilv-link-mismatch'
    link_test_cid = 'CG-ilv-link-clean'
    link_unres_target = 'CG-ilv-link-unresolved'

    with sessions.control.connection(write=True) as db:
        db.execute('INSERT INTO principals (id, name) VALUES (?, ?)', (link_test_pid, 'ILV Link Test'))
        db.execute(
            'INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) '
            "VALUES (?, ?, ?, ?, 'customer', 1, 1)", (link_test_mid, tenant, link_test_pid, link_test_cid)
        )
        db.execute(
            'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) VALUES (?, ?, ?, ?, ?)',
            ('cl-ilv-mismatch', tenant, link_test_pid, link_unres_target, time.time())
        )
        db.execute(
            'INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?, ?, ?)',
            (tenant, link_unres_target, time.time())
        )
    with sessions.business_store(tenant).connection(write=True) as b:
        b.execute('INSERT INTO customers (id, name) VALUES (?, ?)', (link_test_cid, 'ILV Link Clean'))
        b.execute("INSERT INTO orders (id, customer_id, name, variant, amount, status, version) "
                  "VALUES (?, ?, 'Link Order', 'M', 2000, 'pending', 1)", ('O-ILV-LINK', link_test_cid))

    link_token = sessions.control.create_session_for_membership(link_test_mid, 3600, 10)
    link_cookie = f'{sessions.cookie_name}={link_token}'

    # Must fail-closed because customer_links points to unresolved customer ID
    with case.assertRaises(ApiError) as link_err:
        with sessions.resolve(link_cookie):
            pass
    case.assertEqual((link_err.exception.status, link_err.exception.code), (503, 'collision_unresolved'))

    status, link_resp = _request(web, '/api/orders', cookie=link_cookie)
    case.assertEqual(status, 503)
    case.assertEqual(link_resp.get('error'), 'collision_unresolved')
    case.assertNotIn('orders', link_resp)

    # When unresolved_collisions entry is cleared, session resolves normally
    with sessions.control.connection(write=True) as db:
        db.execute('DELETE FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?',
                   (tenant, link_unres_target))

    with sessions.resolve(link_cookie) as binding:
        case.assertEqual(binding.customer_id, link_test_cid)
    status, link_resp = _request(web, '/api/orders', cookie=link_cookie)
    case.assertEqual(status, 200)
    case.assertEqual([o['id'] for o in link_resp['orders']], ['O-ILV-LINK'])

    # 4. P1.1d: Role non-customer (staff, manager, viewer) must not be blocked by customer unresolved collisions
    staff_pid = 'p-ilv-staff-guard'
    staff_mid = 'm-ilv-staff-guard'
    staff_cid = 'CG-ilv-staff-collision'
    mgr_pid = 'p-ilv-mgr-guard'
    mgr_mid = 'm-ilv-mgr-guard'
    viewer_pid = 'p-ilv-viewer-guard'
    viewer_mid = 'm-ilv-viewer-guard'
    viewer_cid = 'CG-ilv-viewer-collision'

    with sessions.control.connection(write=True) as db:
        db.execute('INSERT INTO principals (id, name) VALUES (?, ?)', (staff_pid, 'ILV Staff Member'))
        db.execute('INSERT INTO principals (id, name) VALUES (?, ?)', (mgr_pid, 'ILV Manager Member'))
        db.execute('INSERT INTO principals (id, name) VALUES (?, ?)', (viewer_pid, 'ILV Viewer Member'))
        db.execute(
            'INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) '
            "VALUES (?, ?, ?, ?, 'staff', 1, 1)", (staff_mid, tenant, staff_pid, staff_cid)
        )
        db.execute(
            'INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) '
            "VALUES (?, ?, ?, ?, 'manager', 1, 1)", (mgr_mid, tenant, mgr_pid, 'mgr-clean-cid')
        )
        db.execute(
            'INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) '
            "VALUES (?, ?, ?, ?, 'viewer', 1, 1)", (viewer_mid, tenant, viewer_pid, viewer_cid)
        )
        # Even if staff_cid or viewer_cid is in unresolved_collisions, staff and viewer are not role='customer'
        db.execute(
            'INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?, ?, ?)',
            (tenant, staff_cid, time.time())
        )
        db.execute(
            'INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?, ?, ?)',
            (tenant, viewer_cid, time.time())
        )

    staff_token = sessions.control.create_session_for_membership(staff_mid, 3600, 10)
    staff_cookie = f'{sessions.cookie_name}={staff_token}'
    with sessions.resolve(staff_cookie) as binding:
        case.assertEqual(binding.principal_id, staff_pid)
        case.assertEqual(binding.application.role, 'staff')

    mgr_token = sessions.control.create_session_for_membership(mgr_mid, 3600, 10)
    mgr_cookie = f'{sessions.cookie_name}={mgr_token}'
    with sessions.resolve(mgr_cookie) as binding:
        case.assertEqual(binding.principal_id, mgr_pid)
        case.assertEqual(binding.application.role, 'manager')

    viewer_token = sessions.control.create_session_for_membership(viewer_mid, 3600, 10)
    viewer_cookie = f'{sessions.cookie_name}={viewer_token}'
    with sessions.resolve(viewer_cookie) as binding:
        case.assertEqual(binding.principal_id, viewer_pid)
        case.assertEqual(binding.application.role, 'viewer')

    # 5. P1.1c: Any query failure during safety checks must fail-closed 503 for customer,
    #    while non-customer roles remain unaffected because they do not run the customer guard.
    def fail_unres_lookup(statement, parameters=()):
        if 'FROM unresolved_collisions' in statement:
            raise RuntimeError('Simulated database failure during unresolved_collisions lookup')

    with inject_identity_fault(sessions.control, fail_unres_lookup):
        # Customer session fails closed
        with case.assertRaises(ApiError) as query_err:
            with sessions.resolve(alice_cookie):
                pass
        case.assertEqual((query_err.exception.status, query_err.exception.code), (503, 'collision_unresolved'))
        status, query_resp = _request(web, '/api/orders', cookie=alice_cookie)
        case.assertEqual(status, 503)
        case.assertEqual(query_resp.get('error'), 'collision_unresolved')
        case.assertNotIn('orders', query_resp)

        # Staff, manager, and viewer sessions are unaffected by customer safety check query failures
        with sessions.resolve(staff_cookie) as binding:
            case.assertEqual(binding.principal_id, staff_pid)
        with sessions.resolve(mgr_cookie) as binding:
            case.assertEqual(binding.principal_id, mgr_pid)
        with sessions.resolve(viewer_cookie) as binding:
            case.assertEqual(binding.principal_id, viewer_pid)

    def fail_link_lookup(statement, parameters=()):
        if 'FROM customer_links' in statement:
            raise RuntimeError('Simulated database failure during customer_links lookup')

    with inject_identity_fault(sessions.control, fail_link_lookup):
        with case.assertRaises(ApiError) as link_query_err:
            with sessions.resolve(alice_cookie):
                pass
        case.assertEqual((link_query_err.exception.status, link_query_err.exception.code), (503, 'collision_unresolved'))
        status, link_query_resp = _request(web, '/api/orders', cookie=alice_cookie)
        case.assertEqual(status, 503)
        case.assertEqual(link_query_resp.get('error'), 'collision_unresolved')

    def fail_col_cnt_lookup(statement, parameters=()):
        if 'FROM memberships' in statement and 'count(*)' in statement:
            raise RuntimeError('Simulated database failure during memberships count lookup')

    with inject_identity_fault(sessions.control, fail_col_cnt_lookup):
        with case.assertRaises(ApiError) as col_query_err:
            with sessions.resolve(alice_cookie):
                pass
        case.assertEqual((col_query_err.exception.status, col_query_err.exception.code), (503, 'collision_unresolved'))
        status, col_query_resp = _request(web, '/api/orders', cookie=alice_cookie)
        case.assertEqual(status, 503)
        case.assertEqual(col_query_resp.get('error'), 'collision_unresolved')

    # Without fault injection, Alice session resolves cleanly again
    with sessions.resolve(alice_cookie) as binding:
        case.assertEqual(binding.customer_id, TARGET_A)
    status, ok_resp = _request(web, '/api/orders', cookie=alice_cookie)
    case.assertEqual(status, 200)
    case.assertEqual([o['id'] for o in ok_resp['orders']], ['O-ILV-A'])
