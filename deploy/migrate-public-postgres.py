"""One-time local EC2 cutover. Back up first; never delete source data or DB volumes.

Run as root after CD has delivered image >=0.9. The operator supplies the new
public hostname. Active guest workspaces require a deliberate identity mapping;
this helper refuses to flatten them into one shared customer account.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def env_update(path, values):
    lines = path.read_text().splitlines()
    lines = [line for line in lines if line.split('=', 1)[0] not in values]
    path.write_text('\n'.join(lines+[key+'='+value for key, value in values.items()])+'\n')
    path.chmod(0o600)


def migrate(root, host, project="retailops-web"):
    if os.geteuid() != 0:
        raise ValueError('Run this host deployment helper with sudo.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,250}[a-z0-9]', host) or '..' in host:
        raise ValueError('Invalid public hostname.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,60}', project):
        raise ValueError('Invalid Compose project.')
    root = root.resolve()
    os.chdir(root)
    current = json.loads(run(['docker', 'inspect', project+'-web-1']))[0]
    settings = dict(item.split('=', 1) for item in current['Config']['Env'])
    if settings.get('RETAILOPS_STORAGE_BACKEND') == 'postgresql':
        raise ValueError('Web already uses PostgreSQL; use database migrate, not this cutover helper.')
    data = Path(next(m['Source'] for m in current['Mounts'] if m['Destination'] == '/data'))
    persistent = settings.get('RETAILOPS_DATA_MODE') == 'persistent-demo'
    if not persistent and any(p.name != 'control.sqlite3' for p in (data/'public-guests').glob('*.sqlite3')):
        raise ValueError('Guest workspaces remain. Archive/map their identities before cutover; no data changed.')
    source = data/('persistent' if persistent else 'public-guests')
    if not (source/('identity.sqlite3' if persistent else 'control.sqlite3')).is_file():
        raise ValueError('Expected source database is missing; no data changed.')
    image = next(line.split('=', 1)[1] for line in (root/'deployed.env').read_text().splitlines()
                 if line.startswith('RETAILOPS_IMAGE='))
    version = run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python', image,
                   '-c', 'from retailops.core import VERSION; print(VERSION)'])
    if version not in ('0.9', '0.10'):
        raise ValueError('Expected a verified 0.9 or 0.10 deployment image.')
    base = ['docker', 'compose', '--project-name', project, '--env-file', 'deployed.env',
            '--env-file', 'public.env', '-f', 'compose.public.yaml']
    pg = base+['-f', 'compose.postgres.yaml']
    backup = root/'backups'/('postgres-cutover-'+time.strftime('%Y%m%d-%H%M%S', time.gmtime()))
    backup.mkdir(parents=True, mode=0o700)
    for name in ('public.env', 'deployed.env', 'compose.public.yaml', 'Caddyfile'):
        shutil.copy2(root/name, backup/name)
    shutil.copy2(root/'deployed.env', backup/'runtime.env')
    env_update(backup/'runtime.env', {'RETAILOPS_IMAGE': current['Config']['Image']})
    run(base+['stop', 'web'])
    try:
        if not persistent and any(p.name != 'control.sqlite3' for p in (data/'public-guests').glob('*.sqlite3')):
            raise ValueError('A guest workspace appeared before web stopped; keeping guest mode.')
        source = data/('persistent' if persistent else 'public-guests')
        if source.exists():
            shutil.copytree(source, backup/source.name)
        print('BACKUP_READY:', backup, flush=True)
        container = run(['docker', 'create', '--network', 'none', image])
        try:
            for name in ('compose.postgres.yaml', 'init-postgres.sh', 'configure-postgres.py', 'compose.rag.yaml', 'enable-pgvector.sql'):
                run(['docker', 'cp', container+':/app/deploy/'+name, str(root/name)])
        finally:
            run(['docker', 'rm', container])
        if not (root/'postgres-secrets').exists():
            run(['python3', str(root/'configure-postgres.py'), '--directory', str(root)])
        run(pg+['up', '-d', '--wait', '--wait-timeout', '90', 'postgres'])
        if persistent:
            # Read-only stopped snapshot, never the live SQLite workspace.
            run(pg+['run', '--rm', '--no-deps', '--user', '0:0', '-v', str(backup/'persistent')+':/snapshot:ro',
                    '--entrypoint', 'python', 'web', '-m', 'retailops', 'database', 'import-sqlite',
                    '--offline-snapshot', '/snapshot'])
        else:
            run(pg+['run', '--rm', '--no-deps', '--entrypoint', 'python', 'web', '-m', 'retailops', 'database', 'init'])
            provision = '''from pathlib import Path
from retailops.config import database_settings
from retailops.identity.postgres import PostgresSessions
from retailops.identity.cli import issue_credential
import os
s=PostgresSessions(database_settings(os.environ)[1])
s.provision_tenant('retailops-demo','RetailOps Demo',seed_demo=True)
mid=s.create_member('retailops-demo','owner','Chủ dự án','C-001')
p=Path('/data/access');p.mkdir(mode=0o700,exist_ok=True)
issue_credential(s.control,mid,p/'retailops-owner.code')
import sqlite3
with sqlite3.connect('file:/snapshot/control.sqlite3?mode=ro',uri=True) as old:
    rows=old.execute('SELECT day,provider_id,attempts FROM provider_daily_usage').fetchall()
with s.control.connection(write=True) as db:
    db.executemany('INSERT INTO provider_daily_usage VALUES (?,?,?) ON CONFLICT(day,provider_id) DO UPDATE SET attempts=excluded.attempts',rows)
print('PERSONAL_ACCOUNT_READY')
'''
            run(pg+['run', '--rm', '--no-deps', '--user', '0:0', '-v', str(backup/'public-guests')+':/snapshot:ro', '--entrypoint', 'python', 'web', '-c', provision])
        env_update(root/'public.env', {'RETAILOPS_PUBLIC_HOST': host, 'RETAILOPS_PUBLIC_ORIGIN': 'https://'+host,
                                      'RETAILOPS_DATA_MODE': 'persistent-demo'})
        run(pg+['up', '-d', '--no-build', '--pull', 'never', '--force-recreate', '--wait', '--wait-timeout', '90', 'web', 'caddy'])
        health = json.loads(run(['docker', 'exec', project+'-web-1', 'python', '-c',
            "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read().decode())"]))
        if health.get('storage_backend') != 'postgresql':
            raise ValueError('Web did not activate PostgreSQL.')
        print('POSTGRES_CUTOVER_OK:', json.dumps(health), flush=True)
        print('PUBLIC_URL: https://'+host, flush=True)
        if not persistent:
            print('ACCESS_CODE_FILE:', data/'access/retailops-owner.code', flush=True)
    except Exception as failure:
        detail = failure.output if isinstance(failure, subprocess.CalledProcessError) else str(failure)
        diagnostic = backup/'failure-details.txt'
        diagnostic.write_text(detail or type(failure).__name__)
        diagnostic.chmod(0o600)
        print('PRIVATE_DIAGNOSTIC_FILE:', diagnostic, flush=True)
        shutil.copy2(backup/'public.env', root/'public.env')
        rollback = ['docker', 'compose', '--project-name', project, '--env-file', str(backup/'runtime.env'),
                    '--env-file', 'public.env', '-f', 'compose.public.yaml']
        run(rollback+['up', '-d', '--no-build', '--pull', 'never', '--force-recreate', 'web', 'caddy'])
        print('CUTOVER_FAILED: restored previous web image/config; source and PostgreSQL volume retained.', flush=True)
        raise RuntimeError('Inspect deployment locally. Error output is suppressed because it can contain configuration.') from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('/opt/retailops'))
    parser.add_argument('--host', required=True)
    parser.add_argument('--project', default='retailops-web')
    args = parser.parse_args()
    try:
        migrate(args.directory, args.host, args.project)
    except Exception as exc:
        parser.exit(1, str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Deployment failed; inspect the local backup and container state.\n')
