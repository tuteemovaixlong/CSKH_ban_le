#!/usr/bin/env bash
# Attended upgrade of an existing RetailOps PostgreSQL 16 volume to pgvector.
# The application remains compatible with business schema v2 until this migration runs.
set -euo pipefail
umask 077

INGEST_DEMO=false
if [[ ${1:-} == "--ingest-demo" ]]; then
  INGEST_DEMO=true
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--ingest-demo]" >&2
  exit 2
fi

cd /opt/retailops
exec 9>deploy.lock
flock -n 9 || { echo 'Another deployment is running. Stop here.' >&2; exit 1; }

for file in deployed.env public.env inference.env api.env compose.public.yaml postgres-secrets/database-url; do
  test -e "$file" || { echo "Missing required file: $file" >&2; exit 1; }
done

image_ref=$(sed -n 's/^RETAILOPS_IMAGE=//p' deployed.env)
test -n "$image_ref"
docker image inspect "$image_ref" >/dev/null

# Always use deployment helpers from the exact activated RetailOps release image.
extract=$(docker create --network none "$image_ref")
staging=$(mktemp -d /opt/retailops/pgvector-stage.XXXXXX)
cleanup() { docker rm "$extract" >/dev/null 2>&1 || true; rm -rf "$staging"; }
trap cleanup EXIT
for name in compose.postgres.yaml init-postgres.sh; do
  docker cp "$extract:/app/deploy/$name" "$staging/$name"
done
install -m 0644 "$staging/compose.postgres.yaml" compose.postgres.yaml
install -m 0755 "$staging/init-postgres.sh" init-postgres.sh
docker rm "$extract" >/dev/null
extract=''
rm -rf "$staging"
staging=''
trap - EXIT

PGVECTOR_IMAGE='pgvector/pgvector:0.8.6-pg16-bookworm@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b'
grep -Fq "image: $PGVECTOR_IMAGE" compose.postgres.yaml || {
  echo 'Activated compose.postgres.yaml does not contain the expected pinned pgvector image.' >&2
  exit 2
}

pg() {
  docker compose --project-name retailops-web --env-file deployed.env --env-file public.env \
    -f compose.public.yaml -f compose.postgres.yaml "$@"
}
pg config --quiet

postgres_container=$(pg ps -q postgres 2>/dev/null || true)
test -n "$postgres_container" || { echo 'PostgreSQL service is not running.' >&2; exit 2; }
previous_image=$(docker inspect --format '{{.Config.Image}}' "$postgres_container")
printf 'CURRENT_POSTGRES_IMAGE=%s\nTARGET_POSTGRES_IMAGE=%s\n' "$previous_image" "$PGVECTOR_IMAGE"

backup_dir=/opt/retailops/backups
mkdir -p "$backup_dir"
chmod 0700 "$backup_dir"
backup="$backup_dir/retailops-pre-pgvector-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg exec -T postgres pg_dump -U postgres -d retailops -Fc > "$backup"
test -s "$backup"
chmod 0600 "$backup"
printf 'PRE_PGVECTOR_BACKUP=%s\n' "$backup"

if ! docker image inspect "$PGVECTOR_IMAGE" >/dev/null 2>&1; then
  echo 'Pulling pinned pgvector/PostgreSQL image.'
  docker pull "$PGVECTOR_IMAGE" >/dev/null
fi
docker image inspect "$PGVECTOR_IMAGE" >/dev/null
echo 'PGVECTOR_IMAGE_READY'

# Brief maintenance window: web is stopped before the database container is replaced.
pg stop web >/dev/null 2>&1 || true
restart_web_on_error=true
on_error() {
  rc=$?
  if [[ "$restart_web_on_error" == true ]]; then
    echo 'PGVECTOR_MIGRATION_FAILED; attempting to bring web back on the current database state.' >&2
    pg up -d --no-build --pull never --wait --wait-timeout 90 web caddy >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap on_error ERR

pg up -d --no-build --pull never --force-recreate --wait --wait-timeout 90 postgres
postgres_container=$(pg ps -q postgres)
target_id=$(docker image inspect --format '{{.Id}}' "$PGVECTOR_IMAGE")
running_id=$(docker inspect --format '{{.Image}}' "$postgres_container")
[[ "$running_id" == "$target_id" ]] || { echo 'PostgreSQL container did not switch to the pinned pgvector image.' >&2; false; }
echo 'PGVECTOR_CONTAINER_OK'

cat <<'SQL' | pg exec -T postgres psql -U postgres -d retailops --set ON_ERROR_STOP=1
CREATE SCHEMA IF NOT EXISTS retailops_extensions AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA retailops_extensions FROM PUBLIC;
GRANT USAGE ON SCHEMA retailops_extensions TO retailops;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA retailops_extensions;
SQL

extension=$(pg exec -T postgres psql -U postgres -d retailops -At --set ON_ERROR_STOP=1 -c \
  "SELECT n.nspname||':'||e.extversion FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'")
[[ "$extension" == retailops_extensions:* ]] || { echo "Unexpected vector extension location: $extension" >&2; false; }
printf 'PGVECTOR_EXTENSION=%s\n' "$extension"

# Schema changes are explicit and atomic per tenant. No web request runs migrations.
pg run --rm --no-deps --entrypoint python web -m retailops database migrate
if [[ "$INGEST_DEMO" == true ]]; then
  pg run --rm --no-deps --entrypoint python web -m retailops knowledge ingest \
    --tenant demo-retail --path /app/data/knowledge
fi
pg run --rm --no-deps --entrypoint python web -m retailops database check

pg up -d --no-build --pull never --wait --wait-timeout 90 web caddy
restart_web_on_error=false
trap - ERR

host=$(sed -n 's/^RETAILOPS_PUBLIC_HOST=//p' public.env)
test -n "$host"
health=''
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if health=$(curl --noproxy '*' --fail --silent --show-error --max-time 15 \
      -H 'Cache-Control: no-cache' "https://$host/healthz" 2>/dev/null); then
    break
  fi
  sleep 5
done
[[ -n "$health" ]] || { echo 'Public HTTPS did not recover after pgvector migration.' >&2; exit 4; }
printf '%s\n' "$health"
python3 - "$health" <<'PY'
import json,sys
payload=json.loads(sys.argv[1])
assert payload.get('status') == 'ok', payload
assert payload.get('data_mode') == 'persistent-demo', payload
assert payload.get('storage_backend') == 'postgresql', payload
print('PGVECTOR_PUBLIC_HEALTH_OK')
PY

if [[ "$INGEST_DEMO" == true ]]; then
  pg run --rm --no-deps --entrypoint python web -m retailops knowledge search \
    --tenant demo-retail --query 'chính sách hủy đơn' --limit 2
  echo 'PGVECTOR_DEMO_KNOWLEDGE_OK'
fi

echo 'PGVECTOR_ENABLE_COMPLETE'
