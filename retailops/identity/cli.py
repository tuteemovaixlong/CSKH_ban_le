"""Operator-only account provisioning. No public administration or credential output."""
import os
import secrets
from pathlib import Path

from retailops.business.permissions import ACTIVE_BUSINESS_ROLES
from retailops.identity.persistent import PersistentSessions


def issue_credential(control, membership_id, destination):
    """Create a private delivery file before rotating; never overwrite an existing file."""
    destination = Path(destination)
    secret = secrets.token_urlsafe(32)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(secret + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        control.register_credential(membership_id, secret)
    except Exception:
        destination.unlink()
        raise
    return {'result': 'CREDENTIAL_WRITTEN', 'membership_id': membership_id,
            'credential_file': str(destination), 'existing_sessions_revoked': True}


def add_parser(commands):
    parser = commands.add_parser('identity', help='Provision persistent synthetic accounts on the server.')
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('RETAILOPS_OUTPUT', '/data')),
                        help='Same RETAILOPS_OUTPUT directory as the public web process.')
    actions = parser.add_subparsers(dest='identity_action', required=True)
    tenant = actions.add_parser('init-tenant', help='Create a tenant database; seeding is explicit.')
    tenant.add_argument('--tenant', required=True)
    tenant.add_argument('--name', required=True)
    tenant.add_argument('--seed-demo', action='store_true')
    customer = actions.add_parser('add-customer')
    customer.add_argument('--tenant', required=True)
    customer.add_argument('--customer', required=True)
    customer.add_argument('--name', required=True)
    member = actions.add_parser('create-member')
    for name in ('tenant', 'principal', 'name', 'customer'):
        member.add_argument('--'+name, required=True)
    member.add_argument('--role', choices=ACTIVE_BUSINESS_ROLES, default='customer')
    issue = actions.add_parser('issue-credential', help='Rotate personal code into a new mode-0600 file.')
    issue.add_argument('--membership', required=True)
    issue.add_argument('--credential-file', type=Path, required=True)
    role = actions.add_parser('set-role', help='Change role and invalidate existing sessions.')
    role.add_argument('--membership', required=True)
    role.add_argument('--role', choices=ACTIVE_BUSINESS_ROLES, required=True)
    revoke = actions.add_parser('revoke', help='Revoke login and sessions; retain business data.')
    revoke.add_argument('--membership', required=True)
    reconcile = actions.add_parser('reconcile-collision', help='Operator execution for account collision reconciliation.')
    reconcile.add_argument('--tenant', required=True)
    reconcile.add_argument('--customer', required=True)
    reconcile.add_argument('--plan-file', type=Path, required=True, help='Path to JSON reconciliation plan file.')
    reconcile.add_argument('--idempotency-key', default=None)
    status = actions.add_parser('reconciliation-status', help='Query reconciliation status by idempotency key.')
    status.add_argument('--idempotency-key', required=True)
    migrate_v5 = actions.add_parser(
        'migrate-v5',
        help='Explicit operator upgrade of an existing identity store to R1 W1 schema v5.',
    )
    migrate_v5.add_argument(
        '--confirm-preflight',
        action='store_true',
        help='Confirm unified preflight inventory (§11.5) has completed.',
    )
    migrate_v5.add_argument(
        '--confirm-backup',
        action='store_true',
        help='Confirm backup/snapshot and restore rehearsal (§11.5) have completed.',
    )


def run(args):
    import json
    from retailops.config import database_settings
    backend, dsn = database_settings(os.environ)
    action = args.identity_action
    if action == 'migrate-v5':
        if backend == 'postgresql':
            from retailops.storage.pg_repositories import migrate_postgres_identity_v5
            return migrate_postgres_identity_v5(
                dsn,
                preflight_confirmed=bool(args.confirm_preflight),
                backup_confirmed=bool(args.confirm_backup),
            )
        from retailops.identity.store import migrate_sqlite_identity_v5
        id_path = args.output / 'persistent' / 'identity.sqlite3'
        return migrate_sqlite_identity_v5(
            id_path,
            preflight_confirmed=bool(args.confirm_preflight),
            backup_confirmed=bool(args.confirm_backup),
        )
    if backend == 'postgresql':
        from retailops.identity.postgres import PostgresSessions
        sessions = PostgresSessions(dsn)
    else:
        sessions = PersistentSessions(args.output/'persistent')
    if action == 'init-tenant':
        sessions.provision_tenant(args.tenant, args.name, seed_demo=args.seed_demo)
        return {'result': 'TENANT_READY', 'tenant_id': args.tenant, 'demo_seed_requested': args.seed_demo}
    if action == 'add-customer':
        sessions.business_store(args.tenant).add_customer(args.customer, args.name)
        return {'result': 'CUSTOMER_CREATED', 'customer_id': args.customer}
    if action == 'create-member':
        mid = sessions.create_member(args.tenant, args.principal, args.name, args.customer, args.role)
        return {'result': 'MEMBERSHIP_CREATED', 'membership_id': mid, 'role': args.role}
    if action == 'issue-credential':
        return issue_credential(sessions.control, args.membership, args.credential_file)
    if action == 'set-role':
        sessions.control.set_role(args.membership, args.role)
        return {'result': 'MEMBERSHIP_UPDATED', 'membership_id': args.membership, 'existing_sessions_revoked': True}
    if action == 'revoke':
        sessions.control.revoke(args.membership)
        return {'result': 'MEMBERSHIP_UPDATED', 'membership_id': args.membership, 'existing_sessions_revoked': True}
    if action == 'reconcile-collision':
        from retailops.identity.reconcile import reconcile_collision
        plan_content = json.loads(args.plan_file.read_text(encoding='utf-8'))
        result = reconcile_collision(
            sessions,
            tenant_id=args.tenant,
            colliding_customer_id=args.customer,
            plan=plan_content,
            idempotency_key=args.idempotency_key,
        )
        return {'result': 'COLLISION_RECONCILED', **result}
    if action == 'reconciliation-status':
        from retailops.identity.reconcile import get_reconciliation_status
        status_res = get_reconciliation_status(sessions, args.idempotency_key)
        return {'result': 'RECONCILIATION_STATUS', 'journal': status_res}
    return {'result': 'UNKNOWN_ACTION'}
