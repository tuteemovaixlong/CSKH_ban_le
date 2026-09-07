#!/usr/bin/env bash
# Roll the already-activated RetailOps image into the live public web service.
# This script is copied from the release image by publish_and_activate.py.
set -euo pipefail
umask 077

image_ref=${1:?Pass the activated ECR image pinned to its sha256 digest}
deployment_dir=/opt/retailops
cd "$deployment_dir"

exec 9>deploy.lock
flock -n 9

test -f deployed.env
test -f allowed-ecr-repository
allowed_repo=$(cat allowed-ecr-repository)
if [[ ! "$image_ref" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]; then
  echo 'Invalid ECR image reference' >&2
  exit 2
fi
if [[ "${image_ref%@*}" != "$allowed_repo" ]]; then
  echo 'Image repository is not the configured RetailOps repository' >&2
  exit 2
fi
activated_image=$(sed -n 's/^RETAILOPS_IMAGE=//p' deployed.env)
data_dir=$(sed -n 's/^RETAILOPS_DATA_DIR=//p' deployed.env)
if [[ "$activated_image" != "$image_ref" || -z "$data_dir" ]]; then
  echo 'Refusing rollout: deployed.env is incomplete or does not point at the activated image' >&2
  exit 2
fi
docker image inspect "$image_ref" >/dev/null

# Baseline-only installations intentionally have no public web configuration.
if [[ ! -f public.env || ! -f compose.public.yaml ]]; then
  echo 'PUBLIC_WEB_NOT_CONFIGURED'
  exit 0
fi

test -f inference.env
test -f api.env
compose=(docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml)
if [[ -d postgres-secrets ]]; then
  test -f compose.postgres.yaml
  compose+=(-f compose.postgres.yaml)
fi
"${compose[@]}" config --quiet

web_container=$("${compose[@]}" ps -q web 2>/dev/null || true)
previous_image=""
running_image_id=""
if [[ -n "$web_container" ]]; then
  previous_image=$(docker inspect --format '{{.Config.Image}}' "$web_container")
  running_image_id=$(docker inspect --format '{{.Image}}' "$web_container")
fi
target_image_id=$(docker image inspect --format '{{.Id}}' "$image_ref")

restore_previous() {
  if [[ -z "$previous_image" || "$previous_image" == "$image_ref" ]]; then
    echo 'No distinct previous live image is available for automatic rollback' >&2
    return 1
  fi
  if [[ ! "$previous_image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || [[ "${previous_image%@*}" != "$allowed_repo" ]]; then
    echo 'Previously running web image is not an allowed pinned RetailOps release; refusing rollback' >&2
    return 1
  fi
  docker image inspect "$previous_image" >/dev/null
  rollback_env=$(mktemp /opt/retailops/deployed.rollback.XXXXXX)
  printf 'RETAILOPS_IMAGE=%s\nRETAILOPS_DATA_DIR=%s\n' "$previous_image" "$data_dir" > "$rollback_env"
  chmod 0644 "$rollback_env"
  rollback=(docker compose --project-name retailops-web --env-file "$rollback_env" --env-file public.env -f compose.public.yaml)
  if [[ -d postgres-secrets ]]; then rollback+=(-f compose.postgres.yaml); fi
  "${rollback[@]}" config --quiet
  if ! "${rollback[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web; then
    rm -f "$rollback_env"
    return 1
  fi
  mv "$rollback_env" deployed.env
  echo 'PUBLIC_WEB_ROLLBACK_OK'
}

verify_live() {
  local host target_hash live_hash health
  host=$(sed -n 's/^RETAILOPS_PUBLIC_HOST=//p' public.env)
  [[ -n "$host" ]] || return 1
  target_hash=$(docker run --rm --pull never --network none --entrypoint sha256sum "$image_ref" /app/web/index.html | awk '{print $1}')
  health=$(curl --noproxy '*' --fail --silent --show-error --max-time 15 --retry 5 --retry-delay 2 --retry-all-errors -H 'Cache-Control: no-cache' "https://$host/healthz") || return 1
  python3 - "$health" <<'PY'
import json,sys
payload=json.loads(sys.argv[1])
assert payload.get('status') == 'ok', payload
PY
  live_hash=$(curl --noproxy '*' --fail --silent --show-error --max-time 15 --retry 5 --retry-delay 2 --retry-all-errors -H 'Accept-Encoding: identity' -H 'Cache-Control: no-cache' "https://$host/" | sha256sum | awk '{print $1}') || return 1
  [[ "$live_hash" == "$target_hash" ]]
}

if [[ "$running_image_id" != "$target_image_id" ]]; then
  echo "PUBLIC_WEB_ROLLOUT: ${previous_image:-none} -> $image_ref"
  if ! "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web; then
    echo 'PUBLIC_WEB_ROLLOUT_FAILED; attempting rollback' >&2
    restore_previous
    exit 1
  fi
else
  echo 'PUBLIC_WEB_ALREADY_USES_ACTIVATED_IMAGE'
fi

if ! verify_live; then
  # Caddy can retain a connection to the replaced container briefly. Restart it once
  # before treating a live asset mismatch as a failed rollout.
  "${compose[@]}" restart caddy >/dev/null
  sleep 2
  if ! verify_live; then
    echo 'PUBLIC_WEB_LIVE_VERIFY_FAILED; attempting rollback' >&2
    restore_previous
    exit 1
  fi
fi

final_container=$("${compose[@]}" ps -q web)
[[ -n "$final_container" ]]
[[ $(docker inspect --format '{{.Image}}' "$final_container") == "$target_image_id" ]]
echo 'PUBLIC_WEB_ROLLOUT_OK'
