"""Create private PostgreSQL deployment secrets once; never print or overwrite them."""
import argparse
import os
from pathlib import Path
import secrets


def configure(directory):
    root = Path(directory)/'postgres-secrets'
    root.mkdir(mode=0o700)  # Refuse an existing deployment; do not rotate a live DB password.
    try:
        admin, app = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        values = {'admin-password': admin, 'app-password': app,
                  'database-url': 'postgresql://retailops:'+app+'@postgres:5432/retailops'}
        for name, value in values.items():
            with (root/name).open('x') as output:
                output.write(value+'\n')
            # Files are readable at their explicit container mounts. The host directory
            # remains mode 0700, so other host users cannot traverse to these files.
            (root/name).chmod(0o444)
    except Exception:
        for name in ('admin-password', 'app-password', 'database-url'):
            (root/name).unlink(missing_ok=True)
        root.rmdir()
        raise
    return 'POSTGRES_CONFIG_CREATED: secrets saved; no database or container was started.'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('/opt/retailops'))
    args = parser.parse_args()
    try:
        print(configure(args.directory))
    except OSError:
        parser.exit(2, 'Configuration already exists or cannot be written. Existing secrets were not changed.\n')
