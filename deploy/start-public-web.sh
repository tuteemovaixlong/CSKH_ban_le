#!/usr/bin/env bash
# Paste the entire file into the EC2 Session Manager terminal, or run with bash.
sudo bash <<'RETAILOPS_HTTPS_SETUP'
set -euo pipefail
umask 077
cd /opt/retailops
if [[ -d postgres-secrets ]]; then
  echo 'PostgreSQL is configured. Use compose.public.yaml together with compose.postgres.yaml; see docs/POSTGRESQL.md.' >&2
  exit 2
fi
# Optional: set an owned hostname whose A record already points to this EC2.
# Empty on the first run uses retailops.<public IPv4 with dashes>.sslip.io.
PUBLIC_HOSTNAME=""
test -f deployed.env
test -f inference.env
test -f api.env
exec 9>deploy.lock
flock -n 9
image_ref=$(sed -n 's/^RETAILOPS_IMAGE=//p' deployed.env)
allowed_repo=$(cat allowed-ecr-repository)
if [[ ! "$image_ref" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || [[ "${image_ref%@*}" != "$allowed_repo" ]]; then
  echo 'Invalid deployed image. Complete CD first.' >&2
  exit 2
fi
docker image inspect "$image_ref" >/dev/null
metadata_token=$(curl --noproxy '*' --fail --silent --show-error --max-time 5 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token)
instance_id=$(curl --noproxy '*' --fail --silent --show-error --max-time 5 -H "X-aws-ec2-metadata-token: $metadata_token" http://169.254.169.254/latest/meta-data/instance-id)
if [[ "$instance_id" != i-0fd116d8927d0e412 ]]; then
  echo 'This setup is for the existing retailops-dev EC2 instance only.' >&2
  exit 2
fi
public_ip=$(curl --noproxy '*' --fail --silent --show-error --max-time 5 -H "X-aws-ec2-metadata-token: $metadata_token" http://169.254.169.254/latest/meta-data/public-ipv4)
unset metadata_token
if [[ -z "$PUBLIC_HOSTNAME" && -f public.env ]]; then
  PUBLIC_HOSTNAME=$(sed -n 's/^RETAILOPS_PUBLIC_HOST=//p' public.env)
fi
if [[ -z "$PUBLIC_HOSTNAME" ]]; then
  PUBLIC_HOSTNAME="retailops.${public_ip//./-}.sslip.io"
fi
python3 - "$PUBLIC_HOSTNAME" "$public_ip" <<'PY'
import ipaddress,re,socket,sys
host, address = sys.argv[1:]
assert ipaddress.ip_address(address).is_global, 'EC2 needs a public IPv4 address.'
assert len(host) <= 253 and '.' in host and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in host.split('.')), 'Invalid DNS hostname.'
resolved = {r[4][0] for r in socket.getaddrinfo(host, 443, socket.AF_INET)}
assert resolved == {address}, 'DNS must resolve only to this EC2 public IPv4. Check DNS. If the EC2 IP changed, set PUBLIC_HOSTNAME to retailops.NEW-IP-WITH-DASHES.sslip.io.'
print('DNS_OK:', host)
PY
container_id=$(docker create --network none "$image_ref")
staging_dir=$(mktemp -d /opt/retailops/https-setup.XXXXXX)
cleanup() { docker rm "$container_id" >/dev/null 2>&1 || true; rm -rf "$staging_dir"; }
trap cleanup EXIT
for name in compose.public.yaml Caddyfile; do
  docker cp "$container_id:/app/deploy/$name" "$staging_dir/$name"
done
# Validate imports/config without API calls, paid inference or modifying the owner DB.
docker run --rm --network none --entrypoint python "$image_ref" -c 'import retailops_public,waitress; print("PUBLIC_IMAGE_OK")'
docker pull caddy:2.11.4-alpine
docker run --rm --network none -e "RETAILOPS_PUBLIC_HOST=$PUBLIC_HOSTNAME" -v "$staging_dir/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.11.4-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
python3 - "$PUBLIC_HOSTNAME" "$staging_dir/public.env" <<'PY'
from pathlib import Path
import re,secrets,sys
host, destination = sys.argv[1:]
values = {}
if Path('public.env').exists():
    for line in Path('public.env').read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=',1)
            if key in values: raise SystemExit('Duplicate public.env key: ' + key)
            values[key] = value
values['RETAILOPS_PUBLIC_HOST'] = host
values['RETAILOPS_PUBLIC_ORIGIN'] = 'https://' + host
values.setdefault('RETAILOPS_PUBLIC_INVITE_TOKEN', secrets.token_urlsafe(32))
values.setdefault('RETAILOPS_PUBLIC_CUSTOM_ENABLED', 'false')
values.setdefault('RETAILOPS_DATA_MODE', 'synthetic-demo')
assert re.fullmatch(r'[A-Za-z0-9_-]{32,128}', values['RETAILOPS_PUBLIC_INVITE_TOKEN']), 'Invalid public invite token.'
assert values['RETAILOPS_PUBLIC_CUSTOM_ENABLED'] in ('true','false'), 'Custom flag must be true or false.'
assert values['RETAILOPS_DATA_MODE'] in ('synthetic-demo','persistent-demo'), 'Invalid data mode.'
allowed={'RETAILOPS_PUBLIC_HOST','RETAILOPS_PUBLIC_ORIGIN','RETAILOPS_PUBLIC_INVITE_TOKEN','RETAILOPS_PUBLIC_CUSTOM_ENABLED','RETAILOPS_DATA_MODE'}
assert set(values) == allowed, 'public.env contains unsupported settings. Put API settings in api.env.'
Path(destination).write_text(''.join(key+'='+value+'\n' for key,value in values.items()))
PY
if [[ -f public.env ]]; then
  backup_dir=$(mktemp -d /opt/retailops/https-config-backup.XXXXXX)
  for name in public.env compose.public.yaml Caddyfile; do
    if [[ -f "$name" ]]; then cp -p "$name" "$backup_dir/"; fi
  done
  printf 'Previous HTTPS config saved at %s\n' "$backup_dir"
fi
install -m 0600 "$staging_dir/public.env" public.env
install -m 0644 "$staging_dir/compose.public.yaml" compose.public.yaml
install -m 0644 "$staging_dir/Caddyfile" Caddyfile
chmod 0600 api.env inference.env
install -d -o 10001 -g 10001 artifacts/public-guests
docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml config --quiet
docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml up -d --no-build --pull never --wait --wait-timeout 60
printf '\nHTTPS is provisioning for https://%s\n' "$PUBLIC_HOSTNAME"
printf '%s\n' 'EC2 Security Group must allow inbound TCP 80 and 443. If UFW is active, allow these two ports there too.'
tls_ready=false
for attempt in 1 2 3 4 5 6; do
  if curl --noproxy '*' --fail --silent --show-error --max-time 10 --resolve "$PUBLIC_HOSTNAME:443:127.0.0.1" "https://$PUBLIC_HOSTNAME/healthz"; then
    tls_ready=true
    break
  fi
  sleep 5
done
if [[ "$tls_ready" == true ]]; then
  printf '\n%s\n' 'PUBLIC_HTTPS_READY'
  printf 'Open https://%s\n' "$PUBLIC_HOSTNAME"
  printf '%s\n' 'Check this URL from your phone using mobile data. No SSM tunnel or laptop is needed.'
else
  printf '\n%s\n' 'PUBLIC_TLS_PENDING: backend started, but a trusted HTTPS certificate is not confirmed yet.'
  printf '%s\n' 'Check inbound 80/443, host firewall and Caddy logs. Do not bypass browser certificate warnings.'
  exit 1
fi
if [[ $(sed -n 's/^RETAILOPS_DATA_MODE=//p' public.env) == persistent-demo ]]; then
  printf '%s\n' 'Persistent accounts use individual codes provisioned with python -m retailops identity. See docs/PERSISTENT_IDENTITY.md.'
else
  printf '%s\n' 'Read RETAILOPS_PUBLIC_INVITE_TOKEN from /opt/retailops/public.env privately, and share it only with invited demo users.'
fi
printf '%s\n' 'API needs its own valid configuration in api.env. HTTPS readiness does not test paid inference.'
RETAILOPS_HTTPS_SETUP
