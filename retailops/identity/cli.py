"""Operator-only account provisioning. No public administration or credential output."""
import os
import secrets
from pathlib import Path

from retailops.business.permissions import ROLE_PERMISSIONS
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
    member.add_argument('--role', choices=tuple(ROLE_PERMISSIONS), default='customer')
    issue = actions.add_parser('issue-credential', help='Rotate personal code into a new mode-0600 file.')
    issue.add_argument('--membership', required=True)
    issue.add_argument('--credential-file', type=Path, required=True)
    role = actions.add_parser('set-role', help='Change role and invalidate existing sessions.')
    role.add_argument('--membership', required=True)
    role.add_argument('--role', choices=tuple(ROLE_PERMISSIONS), required=True)
    revoke = actions.add_parser('revoke', help='Revoke login and sessions; retain business data.')
    revoke.add_argument('--membership', required=True)


def run(args):
    from retailops.config import database_settings
    backend, dsn = database_settings(os.environ)
    if backend == 'postgresql':
        from retailops.identity.postgres import PostgresSessions
        sessions = PostgresSessions(dsn)
    else:
        sessions = PersistentSessions(args.output/'persistent')
    action = args.identity_action
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
    elif action == 'revoke':
        sessions.control.revoke(args.membership)
    return {'result': 'MEMBERSHIP_UPDATED', 'membership_id': args.membership, 'existing_sessions_revoked': True}
