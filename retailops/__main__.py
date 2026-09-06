"""System entrypoint: python -m retailops {check-config,serve-public,serve-private}."""
import argparse
import json

from retailops.bootstrap import serve_private, serve_public
from retailops.config import Settings
from retailops.models import build_gateways


def main():
    parser = argparse.ArgumentParser(description='RetailOps system foundation (synthetic data only).')
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check-config', help='Validate settings locally; never prints secrets or calls a model.')
    check.add_argument('--interface', choices=('public', 'private'), default='public')
    commands.add_parser('serve-public', help='Serve HTTPS backend behind Caddy.')
    commands.add_parser('serve-private', help='Serve private localhost/SSM API.')
    args = parser.parse_args()
    try:
        if args.command == 'check-config':
            settings = Settings.from_environment(args.interface)
            build_gateways(settings)
            print(json.dumps({'result': 'CONFIG_VALID', **settings.summary(), 'connectivity_checked': False}))
        elif args.command == 'serve-public':
            serve_public()
        else:
            serve_private()
    except ValueError as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
