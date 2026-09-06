"""System entrypoint: python -m retailops {check-config,serve-public,serve-private}."""
import argparse
import json

from retailops.bootstrap import serve_private, serve_public
from retailops.config import Settings
from retailops.models import build_gateways
from retailops.core import ApiError
from retailops.identity import cli as identity_cli
from retailops.storage import cli as database_cli


def main():
    parser = argparse.ArgumentParser(description='RetailOps system foundation (synthetic data only).')
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check-config', help='Validate settings locally; never prints secrets or calls a model.')
    check.add_argument('--interface', choices=('public', 'private'), default='public')
    commands.add_parser('serve-public', help='Serve HTTPS backend behind Caddy.')
    commands.add_parser('serve-private', help='Serve private localhost/SSM API.')
    identity_cli.add_parser(commands)
    database_cli.add_parser(commands)
    args = parser.parse_args()
    try:
        if args.command == 'check-config':
            settings = Settings.from_environment(args.interface)
            build_gateways(settings)
            print(json.dumps({'result': 'CONFIG_VALID', **settings.summary(), 'connectivity_checked': False}))
        elif args.command == 'serve-public':
            serve_public()
        elif args.command == 'identity':
            print(json.dumps(identity_cli.run(args), ensure_ascii=False))
        elif args.command == 'database':
            print(json.dumps(database_cli.run(args), ensure_ascii=False))
        else:
            serve_private()
    except ValueError as error:
        parser.exit(2, str(error) + '\n')
    except ApiError as error:
        parser.exit(2, error.code + ': ' + error.message + '\n')
    except OSError:
        parser.exit(2, 'Cannot access the configured data or credential file. Check permissions and use a new credential filename.\n')


if __name__ == '__main__':
    main()
