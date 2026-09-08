#!/usr/bin/env python3
"""Install/refresh the optional read-only EC2 console from the activated image.

Credential provisioning is local to this host. No credential is printed or sent to CI.
Snapshots are metadata-only; refresh never runs model inference or business mutations.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time

ROOT = Path('/opt/retailops')
DATA = ROOT / 'console-data'
PRIVATE = ROOT / 'admin-secrets'
STEP = 'startup'


def step(name):
    global STEP
    STEP = name
    print('ADMIN_STEP=' + name, flush=True)


def command(args, *, input_data=None, check=True, timeout=120):
    p = subprocess.run(args, cwd=ROOT, input=input_data, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError('Console operation failed; no command arguments or private output logged')
    return p


def value(path, key):
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return ''


def compose(admin=False):
    args = ['docker', 'compose', '--project-name', 'retailops-web',
            '--env-file', 'deployed.env', '--env-file', 'public.env', '-f', 'compose.public.yaml']
    if (ROOT / 'postgres-secrets').is_dir():
        args += ['-f', 'compose.postgres.yaml']
    if admin:
        args += ['--env-file', 'admin.env', '-f', 'compose.admin.yaml']
    return args


def pinned_image(expected=None):
    image = value(ROOT / 'deployed.env', 'RETAILOPS_IMAGE')
    allowed = (ROOT / 'allowed-ecr-repository').read_text().strip()
    if not re.fullmatch(r'[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}', image) or image.split('@')[0] != allowed:
        raise ValueError('Invalid activated image')
    if expected and image != expected:
        raise ValueError('Release changed; retry after deployment settles')
    web = command(compose() + ['ps', '-q', 'web']).stdout.strip()
    actual = command(['docker', 'inspect', '--format', '{{.Config.Image}}', web]).stdout.strip()
    if actual != image:
        raise ValueError('Web image differs from activated release')
    return image


def secure_write(path, content, mode=0o600, group=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        name = Path(handle.name)
        handle.write(content.encode() if isinstance(content, str) else content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(name, mode)
    os.chown(name, 0, group)
    os.replace(name, path)


def docker_eval(image, args, source=None):
    command_args = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
        '--read-only', '--tmpfs', '/tmp', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--memory', '192m', '--pids-limit', '48', '--user', '0:10001',
        '-v', str(DATA) + ':/console-data']
    if source:
        command_args += ['--mount', 'type=bind,source=' + str(source) + ',target=/source.json,readonly']
    command(command_args + ['--entrypoint', 'python', image, '-m', 'opsconsole.cli'] + args)
    for folder, _, files in os.walk(DATA / 'runs'):
        os.chown(folder, 0, 10001)
        os.chmod(folder, 0o750)
        for name in files:
            path = Path(folder) / name
            os.chown(path, 0, 10001)
            os.chmod(path, 0o640)


def refresh(image=None):
    image = pinned_image(image)
    salt = (PRIVATE / 'telemetry-key').read_text(encoding='ascii')
    p = command(compose() + ['exec', '-T', 'web', 'python', '-m', 'opsconsole.usage'], input_data=salt)
    snapshot = json.loads(p.stdout)
    if snapshot.get('schema') != 'retailops-usage-v1':
        raise ValueError('Invalid usage export')
    secure_write(DATA / 'usage.json', json.dumps(snapshot, ensure_ascii=False, allow_nan=False), 0o640, 10001)
    state = {}
    for service in ('web', 'postgres'):
        cid = command(compose() + ['ps', '-q', service], check=False).stdout.strip()
        if cid:
            state[service] = command(['docker', 'inspect', '--format',
                '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}', cid]).stdout.strip()
    secure_write(DATA / 'deployment.json', json.dumps({'collected_at': time.time(),
        'image_digest': image.split('@')[-1], 'services': state,
        'scope': 'Docker health snapshot, not CloudWatch/provider availability'}), 0o640, 10001)
    reports = sorted((ROOT / 'e2e-reports').glob('LIVE_*.json'), key=lambda p: p.name, reverse=True)[:20]
    for source in reports:
        if source.is_symlink() or source.stat().st_size > 5_000_000:
            continue
        run_id = 'live-' + hashlib.sha256(source.read_bytes()).hexdigest()[:24]
        if not (DATA / 'runs' / run_id / 'report.json').exists():
            docker_eval(image, ['import-live', '--source', '/source.json', '--out', '/console-data/runs'], source)
    print('ADMIN_SNAPSHOT_REFRESH_OK')


def https(host, path, password=None):
    with tempfile.TemporaryDirectory(prefix='retailops-admin-check-') as tmp:
        config, output = Path(tmp) / 'curl.conf', Path(tmp) / 'body'
        args = ['curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '15',
                '--resolve', host + ':443:127.0.0.1', '--output', str(output), '--write-out', '%{http_code}']
        if password:
            config.write_text('user = "opsadmin:' + password + '"\n', encoding='ascii')
            os.chmod(config, 0o600)
            args += ['--config', str(config)]
        p = command(args + ['https://' + host + path], check=False, timeout=20)
        return p.stdout.strip(), output.read_text(encoding='utf-8') if output.exists() else ''


def verify():
    host = value(ROOT / 'admin.env', 'RETAILOPS_ADMIN_HOST')
    login = json.loads((PRIVATE / 'initial-login.json').read_text())
    for _ in range(20):
        status, _ = https(host, '/api/runs')
        if status == '401':
            break
        time.sleep(3)
    if status != '401':
        raise RuntimeError('Admin must deny anonymous reads before acceptance')
    status, data = https(host, '/api/runs', login['password'])
    if status != '200' or not isinstance(json.loads(data).get('runs'), list):
        raise RuntimeError('Authenticated console read failed')
    status, _ = https(host, '/api/usage', 'invalid-password')
    if status != '401':
        raise RuntimeError('Incorrect password was not denied')
    cid = command(compose(True) + ['ps', '-q', 'admin']).stdout.strip()
    port_bindings = command(['docker', 'inspect', '--format', '{{json .HostConfig.PortBindings}}', cid]).stdout.strip()
    if json.loads(port_bindings) not in (None, {}):
        raise RuntimeError('Admin has a published host port')
    print('ADMIN_CONSOLE_SMOKE_OK (anonymous=401; authenticated=200; wrong-password=401; no host port)')


def install(image, commit):
    step('validate_release')
    image = pinned_image(image)
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Explicit release commit required')
    host = value(ROOT / 'public.env', 'RETAILOPS_PUBLIC_HOST')
    if value(ROOT / 'public.env', 'RETAILOPS_PUBLIC_ORIGIN') != 'https://' + host:
        raise ValueError('Public host/origin mismatch')
    admin_host = 'admin-' + host
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{2,245}', admin_host):
        raise ValueError('Invalid admin host')
    DATA.mkdir(mode=0o750, exist_ok=True)
    os.chown(DATA, 0, 10001)
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    os.chmod(PRIVATE, 0o700)
    config_dir = ROOT / 'admin-caddy'
    config_dir.mkdir(mode=0o700, exist_ok=True)
    step('install_compose')
    cid = command(['docker', 'create', '--network', 'none', image]).stdout.strip()
    try:
        command(['docker', 'cp', cid + ':/app/deploy/compose.admin.yaml', str(ROOT / 'compose.admin.yaml')])
    finally:
        command(['docker', 'rm', cid], check=False)
    if not (PRIVATE / 'telemetry-key').exists():
        secure_write(PRIVATE / 'telemetry-key', secrets.token_hex(32))
    if not (PRIVATE / 'initial-login.json').exists():
        secure_write(PRIVATE / 'initial-login.json', json.dumps({'username': 'opsadmin', 'password': secrets.token_urlsafe(24)}))
    step('configure_admin_auth')
    login = json.loads((PRIVATE / 'initial-login.json').read_text())
    caddy = command(compose() + ['ps', '-q', 'caddy']).stdout.strip()
    hashed = command(['docker', 'exec', caddy, 'caddy', 'hash-password', '--plaintext', login['password']]).stdout.strip()
    if not re.fullmatch(r'\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}', hashed):
        raise ValueError('Unexpected password hash')
    site = admin_host + ' {\n    basic_auth {\n        opsadmin ' + hashed + '\n    }\n' + '''    encode zstd gzip
    header {
        -Server
        Strict-Transport-Security "max-age=86400"
    }
    request_body {
        max_size 1KB
    }
    reverse_proxy admin:8100 {
        header_up -Authorization
        header_up -Cookie
    }
}
'''
    secure_write(config_dir / 'console.caddy', site)
    secure_write(ROOT / 'admin.env', 'RETAILOPS_ADMIN_HOST=' + admin_host + '\n')
    caddyfile = ROOT / 'Caddyfile'
    previous = caddyfile.read_text()
    marker = 'import /etc/caddy/admin/*.caddy'
    if marker not in previous:
        secure_write(ROOT / ('Caddyfile.before-admin-' + str(int(time.time()))), previous)
        secure_write(caddyfile, previous.rstrip() + '\n\n' + marker + '\n', 0o644)
    step('validate_caddy')
    try:
        command(compose(True) + ['config', '--quiet'])
        command(compose(True) + ['run', '--rm', '--no-deps', 'caddy', 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'])
    except Exception:
        secure_write(caddyfile, previous, 0o644)
        raise
    step('collect_snapshots')
    refresh(image)
    step('router_evaluation')
    marker_file = PRIVATE / ('router-' + image.split(':')[-1])
    if not marker_file.exists():
        docker_eval(image, ['router', '--source', '/app/evals/scenarios/baseline_v1.jsonl', '--out', '/console-data/runs', '--commit', commit])
        secure_write(marker_file, 'complete\n')
    step('start_admin')
    command(compose(True) + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '90', 'admin', 'caddy'])
    command(compose(True) + ['restart', 'caddy'])
    step('verify_admin')
    verify()
    public_status, public_body = https(host, '/healthz')
    if public_status != '200' or json.loads(public_body).get('status') != 'ok':
        raise RuntimeError('Customer health failed after admin rollout')
    step('enable_refresh_timer')
    secure_write(Path('/etc/systemd/system/retailops-console-refresh.service'), '''[Unit]
Description=RetailOps metadata-only console refresh
After=docker.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/retailops/admin-console.py refresh
TimeoutStartSec=180
UMask=0077
''', 0o644)
    secure_write(Path('/etc/systemd/system/retailops-console-refresh.timer'), '''[Unit]
Description=Refresh RetailOps console metadata every two minutes
[Timer]
OnBootSec=90
OnUnitActiveSec=120
Persistent=true
[Install]
WantedBy=timers.target
''', 0o644)
    command(['systemctl', 'daemon-reload'])
    command(['systemctl', 'enable', '--now', 'retailops-console-refresh.timer'])
    print('ADMIN_CONSOLE_READY host=' + admin_host)
    print('Admin credential file: /opt/retailops/admin-secrets/initial-login.json (operator only; never paste into chat)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('install', 'refresh', 'verify'))
    parser.add_argument('--image')
    parser.add_argument('--commit')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Run through sudo on the EC2 host')
    with (ROOT / 'console-refresh.lock').open('w') as lock:
        deadline = time.monotonic() + (180 if args.operation == 'install' else 1)
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Console refresh lock busy')
                time.sleep(1)
        if args.operation == 'install':
            install(args.image, args.commit or '')
        elif args.operation == 'refresh':
            refresh(args.image)
        else:
            verify()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('ADMIN_CONSOLE_FAILED step=' + STEP + '; private command output was not logged')
        raise SystemExit(1)
