"""Small, explicit role policy for the persistent synthetic pilot."""
READ = 'orders:read'
CANCEL = 'orders:cancel'
STAFF = 'staff:desk'
MANAGER = 'store:manage'
PLATFORM_ADMIN = 'platform:admin'

ROLE_PERMISSIONS = {
    'customer': frozenset((READ, CANCEL)),
    'viewer': frozenset((READ,)),
    'staff': frozenset((READ, CANCEL, STAFF)),
    'manager': frozenset((READ, CANCEL, STAFF, MANAGER)),
    'platform_admin': frozenset((READ, CANCEL, STAFF, MANAGER, PLATFORM_ADMIN)),
}

