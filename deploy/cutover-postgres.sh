#!/usr/bin/env bash
# Safely switch the existing persistent demo from SQLite to PostgreSQL.
# If verified import cannot be used and the PostgreSQL target is still empty,
# pass --seed-demo-fallback to provision a fresh synthetic tenant instead.
set -euo pipefail
umask 077

SEED_FALLBACK=false
if [[ ${1:-} == "--seed-demo-fallback" ]]; then
  SEED_FALLBACK=true
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--seed-demo-fallback]" >&2
  exit 2
fi

cd /opt/retailops
exec 9>deploy.lock
flock -n 9

test -f deployed.env
test -f public.env
test -f inference.env
test -f api.env
image_ref=$(sed -n 's/^RETAILOPS_IMAGE=//p' deployed.env)
test -n "$image_ref"
docker image inspect "$image_ref" >/dev/null

extract=$(docker create --network none "$image_ref")
staging=$(mktemp -d /opt/retailops/pg-cutover.XXXXXX)
cleanup() { docker rm "$extract" >/dev/null 2>&1 || true; rm -rf "$staging"; }
trap cleanup EXIT
for name in compose.postgres.yaml configure-postgres.py init-postgres.sh; do
  docker cp "$extract:/app/deploy/$name" "$staging/$name"
done
install -m 0644 "$staging/compose.postgres.yaml" compose.postgres.yaml
install -m 0644 "$staging/init-postgres.sh" init-postgres.sh
install -m 0700 "$staging/configure-postgres.py" configure-postgres.py

if [[ ! -d postgres-secrets ]]; then
  python3 configure-postgres.py
fi

python3 - <<'PY'
from pathlib import Path
p=Path('public.env')
lines=p.read_text().splitlines()
out=[]
seen=False
for line in lines:
    if line.startswith('RETAILOPS_DATA_MODE='):
        out.append('RETAILOPS_DATA_MODE=persistent-demo')
        seen=True
    else:
        out.append(line)
if not seen:
    out.append('RETAILOPS_DATA_MODE=persistent-demo')
p.write_text('\n'.join(out)+'\n')
PY

pg() {
  docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml -f compose.postgres.yaml "$@"
}

pg config --quiet
postgres_image='postgres:16.15-bookworm'
if ! docker image inspect "$postgres_image" >/dev/null 2>&1; then
  echo "Pulling required PostgreSQL image: $postgres_image"
  docker pull "$postgres_image" >/dev/null
fi
docker image inspect "$postgres_image" >/dev/null
echo 'POSTGRES_IMAGE_READY'
pg up -d --no-build --pull never --wait --wait-timeout 90 postgres

# Stop web before taking any SQLite snapshot or importing it.
pg stop web >/dev/null 2>&1 || true

snapshot=""
if [[ -d artifacts/persistent ]]; then
  snapshot=$(mktemp -d /opt/retailops/artifacts/pg-import.XXXXXX)
  cp -a artifacts/persistent "$snapshot/persistent"
  chown -R 10001:10001 "$snapshot"
fi

imported=false
if [[ -n "$snapshot" ]]; then
  set +e
  import_output=$(pg run --rm --no-deps --entrypoint python web -m retailops database import-sqlite --offline-snapshot "/data/$(basename "$snapshot")/persistent" 2>&1)
  import_rc=$?
  set -e
  printf '%s\n' "$import_output"
  if [[ $import_rc -eq 0 ]] && grep -q 'POSTGRES_IMPORT_VERIFIED' <<<"$import_output"; then
    imported=true
  fi
fi

if [[ "$imported" != true ]]; then
  if [[ "$SEED_FALLBACK" != true ]]; then
    echo 'SQLite import was not verified. PostgreSQL was left without fallback demo data.' >&2
    echo 'Re-run with --seed-demo-fallback only if replacing old demo state is acceptable.' >&2
    exit 3
  fi

  # import-sqlite is transactional and only accepts an empty target. If it failed,
  # database init is safe only when identity has not already been populated.
  init_output=$(pg run --rm --no-deps --entrypoint python web -m retailops database init 2>&1)
  printf '%s\n' "$init_output"

  tenant_id="demo-retail"
  tenant_name="RetailOps Demo Store"
  pg run --rm --no-deps --entrypoint python web -m retailops identity init-tenant --tenant "$tenant_id" --name "$tenant_name" --seed-demo
  echo 'POSTGRES_DEMO_SEEDED'
fi

# Ensure every tenant business schema is at the current v0.9 schema version.
pg run --rm --no-deps --entrypoint python web -m retailops database migrate
pg run --rm --no-deps --entrypoint python web -m retailops database check
pg up -d --no-build --pull never --wait --wait-timeout 90 web caddy

host=$(sed -n 's/^RETAILOPS_PUBLIC_HOST=//p' public.env)
test -n "$host"
health=''
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if health=$(curl --noproxy '*' --fail --silent --show-error --max-time 15 "https://$host/healthz" 2>/dev/null); then
    break
  fi
  sleep 5
done
if [[ -z "$health" ]]; then
  echo 'Public HTTPS did not become ready after PostgreSQL cutover.' >&2
  curl --noproxy '*' --fail --silent --show-error --max-time 15 "https://$host/healthz" || true
  exit 4
fi
printf '%s\n' "$health"
python3 - "$health" <<'PY'
import json,sys
payload=json.loads(sys.argv[1])
assert payload.get('version') == '0.9', payload
assert payload.get('data_mode') == 'persistent-demo', payload
assert payload.get('storage_backend') == 'postgresql', payload
print('POSTGRES_CUTOVER_HEALTH_OK')
PY

echo 'POSTGRES_CUTOVER_COMPLETE'
