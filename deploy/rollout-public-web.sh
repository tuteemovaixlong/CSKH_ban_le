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

# Build compose stack and capture the currently running live web image BEFORE
# refreshing sslip.io hostnames. In the 2026-11-09 incident, recreating web/caddy
# inside the sslip.io refresh block launched the unverified new image first
# (overwriting previous_image so rollback could not recover on schema mismatch)
# and dropped Caddy's compose.admin.yaml overlay.
test -f inference.env
test -f api.env
compose=(docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml)
if [[ -d postgres-secrets ]]; then
  test -f compose.postgres.yaml
  compose+=(-f compose.postgres.yaml)
fi
if [[ -f compose.clamav.yaml ]]; then
  compose+=(-f compose.clamav.yaml)
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

# Refresh auto-generated sslip.io hostname in public.env only; do not recreate
# web or caddy before web rollout and health verification.
host_changed=false
existing_host=$(sed -n 's/^RETAILOPS_PUBLIC_HOST=//p' public.env 2>/dev/null || true)
auto_host=""
if [[ "$existing_host" =~ ^retailops\.([0-9]{1,3}-){3}[0-9]{1,3}\.sslip\.io$ ]]; then
  metadata_token=$(curl --noproxy '*' --fail --silent --show-error --max-time 3 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)
  if [[ -n "$metadata_token" ]]; then
    current_ip=$(curl --noproxy '*' --fail --silent --show-error --max-time 3 -H "X-aws-ec2-metadata-token: $metadata_token" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)
    if [[ -n "$current_ip" ]]; then
      auto_host="retailops.${current_ip//./-}.sslip.io"
      if [[ "$existing_host" != "$auto_host" ]]; then
        echo "EC2 public IPv4 changed; refreshing hostname in public.env: $existing_host -> $auto_host"
        sed -i "s/^RETAILOPS_PUBLIC_HOST=.*/RETAILOPS_PUBLIC_HOST=$auto_host/" public.env
        sed -i "s|^RETAILOPS_PUBLIC_ORIGIN=.*|RETAILOPS_PUBLIC_ORIGIN=https://$auto_host|" public.env
        host_changed=true
      fi
    fi
  fi
fi

overlay_changed=false
compose_backup=""

recreate_caddy() {
  local env_file=${1:-deployed.env}
  local caddy_compose=(docker compose --project-name retailops-web --env-file "$env_file" --env-file public.env -f compose.public.yaml)
  if [[ -d postgres-secrets ]]; then caddy_compose+=(-f compose.postgres.yaml); fi
  if [[ -f compose.clamav.yaml ]]; then caddy_compose+=(-f compose.clamav.yaml); fi
  if [[ -f admin.env && -f compose.admin.yaml ]]; then
    caddy_compose+=(--env-file admin.env -f compose.admin.yaml)
  fi
  "${caddy_compose[@]}" config --quiet
  "${caddy_compose[@]}" up -d --no-deps --no-build --pull never --force-recreate caddy >/dev/null
}

restore_previous() {
  if [[ "$overlay_changed" == true && -f "$compose_backup" ]]; then
    cp -p "$compose_backup" compose.public.yaml
  fi
  if [[ -z "$previous_image" || ( "$previous_image" == "$image_ref" && "$overlay_changed" != true && "$host_changed" != true ) ]]; then
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
  if [[ -f compose.clamav.yaml ]]; then rollback+=(-f compose.clamav.yaml); fi
  "${rollback[@]}" config --quiet
  if ! "${rollback[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web; then
    rm -f "$rollback_env"
    return 1
  fi
  if [[ "$host_changed" == true ]]; then
    recreate_caddy "$rollback_env" || true
  else
    "${rollback[@]}" restart caddy >/dev/null || true
  fi
  mv "$rollback_env" deployed.env
  echo 'PUBLIC_WEB_ROLLBACK_OK'
}

verify_live() {
  local host target_hash live_hash health target_source live_source active_container
  host=$(sed -n 's/^RETAILOPS_PUBLIC_HOST=//p' public.env)
  [[ -n "$host" ]] || return 1
  # index.html is intentionally modified by the public adapter with auth/data-mode
  # attributes. chat-focus.js is served byte-for-byte and is therefore safe to hash.
  target_hash=$(docker run --rm --pull never --network none --entrypoint sha256sum "$image_ref" /app/web/chat-focus.js | awk '{print $1}')
  health=$(curl --noproxy '*' --fail --silent --show-error --max-time 15 --retry 5 --retry-delay 2 --retry-all-errors -H 'Cache-Control: no-cache' "https://$host/healthz") || return 1
  python3 - "$health" <<'PY'
import json,sys
payload=json.loads(sys.argv[1])
assert payload.get('status') == 'ok', payload
PY
  live_hash=$(curl --noproxy '*' --fail --silent --show-error --max-time 15 --retry 5 --retry-delay 2 --retry-all-errors -H 'Accept-Encoding: identity' -H 'Cache-Control: no-cache' "https://$host/chat-focus.js" | sha256sum | awk '{print $1}') || return 1
  [[ "$live_hash" == "$target_hash" ]] || return 1
  # An image ID is insufficient when a host code directory is mounted over /app.
  target_source=$(docker run --rm --pull never --network none --entrypoint python "$image_ref" /app/deploy/source_consistency.py digest) || return 1
  active_container=$("${compose[@]}" ps -q web) || return 1
  live_source=$(docker exec "$active_container" python /app/deploy/source_consistency.py digest) || return 1
  [[ "$live_source" == "$target_source" ]] || { echo 'PUBLIC_WEB_SOURCE_MISMATCH' >&2; return 1; }
  echo "PUBLIC_WEB_SOURCE_MATCH=$live_source"
}

# Retire ONLY the old script's exact read-only code mounts. Keep /data, secrets,
# custom configuration and DB mounts intact. Any other /opt/retailops/patches mount
# (data/, evals/, mcp_config.json) shadows release content and stops the rollout.
# Back up the original compose file so rollback restores code AND its mounts.
compose_candidate=$(mktemp /opt/retailops/compose.image-code.XXXXXX)
if ! docker run --rm -i --pull never --network none --entrypoint python "$image_ref" /app/deploy/source_consistency.py strip < compose.public.yaml > "$compose_candidate"; then
  rm -f "$compose_candidate"
  exit 1
fi
if ! cmp -s compose.public.yaml "$compose_candidate"; then
  compose_backup=$(mktemp /opt/retailops/compose.pre-image-code.XXXXXX)
  cp -p compose.public.yaml "$compose_backup"
  mv "$compose_candidate" compose.public.yaml
  overlay_changed=true
  if ! "${compose[@]}" config --quiet; then
    cp -p "$compose_backup" compose.public.yaml
    exit 1
  fi
  echo "PUBLIC_WEB_LEGACY_CODE_MOUNTS_REMOVED backup=$compose_backup"
else
  rm -f "$compose_candidate"
fi

if [[ "$running_image_id" != "$target_image_id" || "$overlay_changed" == true || "$host_changed" == true ]]; then
  echo "PUBLIC_WEB_ROLLOUT: ${previous_image:-none} -> $image_ref"
  if ! "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web; then
    echo 'PUBLIC_WEB_ROLLOUT_FAILED; attempting rollback' >&2
    restore_previous
    exit 1
  fi
  if [[ "$host_changed" == true ]]; then
    if ! recreate_caddy deployed.env; then
      echo 'PUBLIC_WEB_CADDY_RECREATE_FAILED; attempting rollback' >&2
      restore_previous
      exit 1
    fi
    sleep 2
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
