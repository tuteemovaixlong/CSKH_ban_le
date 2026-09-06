"""Small, explicit role policy for the persistent synthetic pilot."""
READ = 'orders:read'
CANCEL = 'orders:cancel'
ROLE_PERMISSIONS = {
    'customer': frozenset((READ, CANCEL)),
    'viewer': frozenset((READ,)),
}
