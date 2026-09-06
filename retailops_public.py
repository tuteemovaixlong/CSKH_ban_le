"""Compatibility imports and public entrypoint; implementation lives in retailops/."""
from retailops.config import public_origin
from retailops.identity.demo import COOKIE, SESSION_SECONDS, GuestSessions
from retailops.http.public import CSP, PublicWeb

def create_application():
    from retailops.bootstrap import build_public_app
    return build_public_app()

def main():
    from retailops.bootstrap import serve_public
    serve_public()

if __name__ == '__main__':
    main()
