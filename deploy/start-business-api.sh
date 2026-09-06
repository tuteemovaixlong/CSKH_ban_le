#!/usr/bin/env bash
# Paste this entire file into an EC2 Session Manager terminal, or run with bash.
sudo bash <<'RETAILOPS_API_SETUP'
set -euo pipefail
cd /opt/retailops
test -f deployed.env
test -f inference.env
exec 9>deploy.lock
flock -n 9
image_ref=$(sed -n 's/^RETAILOPS_IMAGE=//p' deployed.env)
allowed_repo=$(cat allowed-ecr-repository)
if [[ ! "$image_ref" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || [[ "${image_ref%@*}" != "$allowed_repo" ]]; then
  echo 'Invalid deployed image. Complete CD first.' >&2
  exit 2
fi
docker image inspect "$image_ref" >/dev/null
container_id=$(docker create --network none "$image_ref")
staging_dir=$(mktemp -d /opt/retailops/api-setup.XXXXXX)
cleanup() { docker rm "$container_id" >/dev/null 2>&1 || true; rm -rf "$staging_dir"; }
trap cleanup EXIT
docker cp "$container_id:/app/deploy/compose.api.yaml" "$staging_dir/compose.api.yaml"
if [[ ! -f api.env ]]; then
  umask 077
  python3 - <<'PY'
from pathlib import Path
import secrets
with Path('api.env').open('x') as f:
    f.write('RETAILOPS_DEMO_TOKEN=' + secrets.token_urlsafe(32) + '\n')
    f.write('RETAILOPS_MODEL_ENABLED=false\n')
PY
fi
chmod 0600 api.env
chown root:root api.env
install -m 0644 "$staging_dir/compose.api.yaml" compose.api.yaml
install -d -o 10001 -g 10001 artifacts
docker compose --project-name retailops-api --env-file deployed.env -f compose.api.yaml config --quiet
docker compose --project-name retailops-api --env-file deployed.env -f compose.api.yaml up -d --no-build --pull never --wait --wait-timeout 60
curl --fail --silent --show-error http://127.0.0.1:8080/healthz
printf '\n%s\n' 'BUSINESS_API_READY' 'Use an SSM port-forwarding session to open http://localhost:8080.'
RETAILOPS_API_SETUP
