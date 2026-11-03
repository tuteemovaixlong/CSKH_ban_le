"""Release-source verification and narrowly scoped legacy code-overlay removal.

Does not change database, catalog, credentials, volumes or inference configuration.
The only removable mounts are literal read-only code mounts left by the retired
scripts/update_ec2.py helper. Unknown/custom mounts remain and cause a digest mismatch.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

CODE_MOUNTS = frozenset((
    'web', 'retailops', 'retailops_providers.py', 'agent_protocol.py',
    'retailops_agent.py', 'retailops_tools.py', 'retailops_conversation.py',
    'retailops_mcp_server.py', 'inference_proxy.py', 'retailops_public.py',
))


def strip_legacy_code_mounts(source):
    lines = []
    for line in source.splitlines(keepends=True):
        value = line.strip()
        if value.startswith('- '):
            value = value[2:].split(' #', 1)[0].strip().strip('\"\'')
            if any(value == f'/opt/retailops/patches/{name}:/app/{name}:ro'
                   for name in CODE_MOUNTS):
                continue
        lines.append(line)
    return ''.join(lines)


def legacy_patch_mounts(source):
    """Mounts from /opt/retailops/patches that remain after the code mounts are stripped.

    Such a mount shadows release content (for example data/, evals/, mcp_config.json) with an old host
    copy. Incident 2026-11-03: /app/data from September hid data/order_action_reasons.json, so every
    signed-in request of W3.2 failed. A rollout must stop until an operator removes them.
    """
    found = []
    for line in source.splitlines():
        value = line.strip()
        if value.startswith('- '):
            value = value[2:].split(' #', 1)[0].strip().strip('\"\'')
            if value.startswith('/opt/retailops/patches'):
                found.append(value)
    return found


def source_digest(root):
    root = Path(root)
    paths = list(root.glob('*.py')) + list((root / 'retailops').rglob('*.py'))
    paths += [p for p in (root / 'web').glob('*') if p.is_file()]
    if not paths or not (root / 'retailops_providers.py').is_file():
        raise ValueError('Release source is incomplete')
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(paths)}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('strip', 'digest'))
    args = parser.parse_args()
    if args.operation == 'strip':
        stripped = strip_legacy_code_mounts(sys.stdin.read())
        leftovers = legacy_patch_mounts(stripped)
        if leftovers:
            for mount in leftovers:
                print(f'PUBLIC_WEB_LEGACY_PATCH_MOUNT_REJECTED {mount}', file=sys.stderr)
            print('Remove every /opt/retailops/patches mount from compose.public.yaml (keep a backup), '
                  'then run the rollout again.', file=sys.stderr)
            sys.exit(3)
        sys.stdout.write(stripped)
    else:
        print(source_digest(Path(__file__).resolve().parents[1]))


if __name__ == '__main__':
    main()
