"""Shared P1.1 regression scenario: reconciliation must never assign a target customer that
already belongs to another principal. Executed against both SQLite and PostgreSQL backends
(see test_pr_a_correctness.py and test_postgres.py). Not collected directly by unittest."""
import time

from retailops.core import ApiError
from retailops.identity.reconcile import get_reconciliation_status, reconcile_collision

COLLIDING = 'CG-tgt-shared'
VICTIM_CUSTOMER = 'CG-tgt-victim'
ORPHAN_CUSTOMER = 'CG-tgt-orphan'
OWN_CUSTOMER = 'CG-tgt-x1-own'
KEY = 'rec-p11-target-guard'


def seed(sessions, tenant):
    now = time.time()
    with sessions.control.connection(write=True) as db:
        for pid, name in (('p-tgt-x1', 'Colliding One'), ('p-tgt-x2', 'Colliding Two'), ('p-tgt-victim', 'Victim')):
            db.execute('INSERT INTO principals (id, name) VALUES (?, ?)', (pid, name))
        for mid, pid, cid in (('m-tgt-x1', 'p-tgt-x1', COLLIDING), ('m-tgt-x2', 'p-tgt-x2', COLLIDING),
                              ('m-tgt-victim', 'p-tgt-victim', VICTIM_CUSTOMER)):
            db.execute(
                'INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) '
                "VALUES (?, ?, ?, ?, 'customer', 1, 1)", (mid, tenant, pid, cid))
        # p-tgt-x1 already owns OWN_CUSTOMER through a customer_link (proven ownership path).
        db.execute('INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                   'VALUES (?, ?, ?, ?, ?)', ('cl-tgt-x1', tenant, 'p-tgt-x1', OWN_CUSTOMER, now))
        db.execute('INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?, ?, ?)',
                   (tenant, COLLIDING, now))
    with sessions.business_store(tenant).connection(write=True) as b:
        for cid, name in ((COLLIDING, 'Shared'), (VICTIM_CUSTOMER, 'Victim Name'),
                          (ORPHAN_CUSTOMER, 'Orphan Name'), (OWN_CUSTOMER, 'X1 Own')):
            b.execute('INSERT INTO customers (id, name) VALUES (?, ?)', (cid, name))
        for oid, cid in (('O-TGT-X1', COLLIDING), ('O-TGT-VICTIM', VICTIM_CUSTOMER),
                         ('O-TGT-ORPHAN', ORPHAN_CUSTOMER), ('O-TGT-X1-OWN', OWN_CUSTOMER)):
            b.execute("INSERT INTO orders (id, customer_id, name, variant, amount, status, version) "
                      "VALUES (?, ?, 'Item', 'M', 1000, 'pending', 1)", (oid, cid))
        b.execute('INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) '
                  'VALUES (?, ?, ?, NULL, 1, ?)', ('conv-tgt-x1', COLLIDING, 'O-TGT-X1', now + 3600))


def plan(target_x1, target_x2):
    return {'reassignments': [
        {'membership_id': 'm-tgt-x1', 'target_customer_id': target_x1, 'target_customer_name': 'Hijacked?',
         'order_ids': ['O-TGT-X1'], 'conversation_ids': ['conv-tgt-x1']},
        {'membership_id': 'm-tgt-x2', 'target_customer_id': target_x2, 'target_customer_name': 'X2 New',
         'order_ids': [], 'conversation_ids': []},
    ]}


def snapshot(sessions, tenant):
    with sessions.control.connection() as db:
        members = {r['id']: (r['customer_id'], r['auth_version']) for r in db.execute(
            "SELECT id, customer_id, auth_version FROM memberships WHERE id LIKE 'm-tgt-%'").fetchall()}
        links = {r['principal_id']: r['customer_id'] for r in db.execute(
            "SELECT principal_id, customer_id FROM customer_links WHERE principal_id LIKE 'p-tgt-%'").fetchall()}
        unresolved = [r['customer_id'] for r in db.execute(
            'SELECT customer_id FROM unresolved_collisions WHERE tenant_id = ?', (tenant,)).fetchall()]
    with sessions.business_store(tenant).connection() as b:
        orders = {r['id']: r['customer_id'] for r in b.execute(
            "SELECT id, customer_id FROM orders WHERE id LIKE 'O-TGT-%'").fetchall()}
        convs = {r['id']: r['customer_id'] for r in b.execute(
            "SELECT id, customer_id FROM conversations WHERE id LIKE 'conv-tgt-%'").fetchall()}
        customers = {r['id']: r['name'] for r in b.execute(
            "SELECT id, name FROM customers WHERE id LIKE 'CG-tgt-%'").fetchall()}
    return {'members': members, 'links': links, 'unresolved': sorted(unresolved),
            'orders': orders, 'convs': convs, 'customers': customers}


def run(case, sessions, tenant):
    """case: unittest.TestCase. sessions: PersistentSessions or PostgresSessions."""
    seed(sessions, tenant)
    before = snapshot(sessions, tenant)
    case.assertIn(COLLIDING, before['unresolved'])

    rejected = {
        # Target already owned by another principal's membership (the P1.1 hijack).
        'victim_membership': plan(VICTIM_CUSTOMER, 'CG-tgt-x2-new'),
        # Two colliding principals merged into one target again.
        'shared_target': plan('CG-tgt-same', 'CG-tgt-same'),
        # Unowned existing customer holding foreign business data: neither new nor proven.
        'orphan_with_data': plan(ORPHAN_CUSTOMER, 'CG-tgt-x2-new'),
        # The ambiguous colliding id itself.
        'colliding_id': plan(COLLIDING, 'CG-tgt-x2-new'),
    }
    for label, bad_plan in rejected.items():
        with case.subTest(rejected=label):
            with case.assertRaises(ApiError) as ctx:
                reconcile_collision(sessions, tenant, COLLIDING, bad_plan, idempotency_key=KEY)
            case.assertEqual(ctx.exception.status, 409)
            case.assertEqual(ctx.exception.code, 'target_customer_conflict')
            # Nothing changed in either database; collision stays unresolved.
            case.assertEqual(snapshot(sessions, tenant), before)
            # The journal insert was rolled back, so the idempotency key is not bound/stuck.
            case.assertIsNone(get_reconciliation_status(sessions, KEY))
            for mid in ('m-tgt-x1', 'm-tgt-x2'):
                with case.assertRaises(ApiError) as blocked:
                    sessions.control.create_session_for_membership(mid, 3600, 10)
                case.assertEqual((blocked.exception.status, blocked.exception.code), (503, 'collision_unresolved'))

    # Retry with a corrected plan under the SAME idempotency key: proven target for x1 (its own
    # customer_link) and a brand-new target for x2.
    good = plan(OWN_CUSTOMER, 'CG-tgt-x2-new')
    result = reconcile_collision(sessions, tenant, COLLIDING, good, idempotency_key=KEY)
    case.assertEqual(result['status'], 'completed')
    case.assertEqual(get_reconciliation_status(sessions, KEY)['status'], 'completed')
    after = snapshot(sessions, tenant)
    case.assertNotIn(COLLIDING, after['unresolved'])
    case.assertEqual(after['members']['m-tgt-x1'][0], OWN_CUSTOMER)
    case.assertEqual(after['members']['m-tgt-x2'][0], 'CG-tgt-x2-new')
    case.assertEqual(after['members']['m-tgt-victim'], before['members']['m-tgt-victim'])
    case.assertEqual(after['links'].get('p-tgt-victim'), before['links'].get('p-tgt-victim'))
    case.assertEqual(after['orders']['O-TGT-X1'], OWN_CUSTOMER)
    case.assertEqual(after['orders']['O-TGT-X1-OWN'], OWN_CUSTOMER)
    case.assertEqual(after['orders']['O-TGT-VICTIM'], VICTIM_CUSTOMER)
    case.assertEqual(after['orders']['O-TGT-ORPHAN'], ORPHAN_CUSTOMER)
    case.assertEqual(after['convs']['conv-tgt-x1'], OWN_CUSTOMER)
    case.assertEqual(after['customers'][VICTIM_CUSTOMER], 'Victim Name')
    case.assertEqual(after['customers'][ORPHAN_CUSTOMER], 'Orphan Name')
    # Idempotent replay of the completed key.
    again = reconcile_collision(sessions, tenant, COLLIDING, good, idempotency_key=KEY)
    case.assertTrue(again.get('already_completed'))
