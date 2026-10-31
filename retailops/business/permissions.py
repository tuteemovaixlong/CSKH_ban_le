"""Small, explicit role policy for the persistent synthetic pilot."""
READ = 'orders:read'
CANCEL = 'orders:cancel'
STAFF = 'staff:desk'
MANAGER = 'store:manage'
PLATFORM_ADMIN = 'platform:admin'

ACTIVE_BUSINESS_ROLES = ('customer', 'staff', 'manager')
LEGACY_DISABLED_ROLES = ('viewer', 'platform_admin')

ROLE_PERMISSIONS = {
    'customer': frozenset((READ, CANCEL)),
    'viewer': frozenset(),
    'staff': frozenset((READ, CANCEL, STAFF)),
    'manager': frozenset((READ, CANCEL, STAFF, MANAGER)),
    'platform_admin': frozenset(),
}

