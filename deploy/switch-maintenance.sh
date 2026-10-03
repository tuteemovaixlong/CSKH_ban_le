#!/usr/bin/env bash
# Operator utility to switch Caddy between standard operation and emergency auth maintenance mode.
# Usage: ./deploy/switch-maintenance.sh [enable|disable|status]
set -euo pipefail

cd /opt/retailops 2>/dev/null || true

ACTION="${1:-status}"

if [[ "$ACTION" == "enable" ]]; then
    echo "Enabling emergency authentication maintenance mode (fail-closed 503 for login routes)..."
    test -f Caddyfile.maintenance || { echo "Caddyfile.maintenance not found!" >&2; exit 1; }
    cp -p Caddyfile Caddyfile.normal.bak 2>/dev/null || true
    cp -f Caddyfile.maintenance Caddyfile
    if command -v docker >/dev/null 2>&1; then
        docker compose -f compose.public.yaml exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || \
        docker compose -f compose.public.yaml restart caddy
    fi
    echo "AUTH_MAINTENANCE_ENABLED"
elif [[ "$ACTION" == "disable" ]]; then
    echo "Disabling auth maintenance mode (restoring normal login flows)..."
    if [[ -f Caddyfile.normal.bak ]]; then
        cp -f Caddyfile.normal.bak Caddyfile
    fi
    if command -v docker >/dev/null 2>&1; then
        docker compose -f compose.public.yaml exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || \
        docker compose -f compose.public.yaml restart caddy
    fi
    echo "AUTH_MAINTENANCE_DISABLED"
elif [[ "$ACTION" == "status" ]]; then
    if grep -q '@auth_maintenance' Caddyfile 2>/dev/null; then
        echo "MAINTENANCE_MODE_ACTIVE"
    else
        echo "NORMAL_MODE_ACTIVE"
    fi
else
    echo "Usage: $0 [enable|disable|status]" >&2
    exit 1
fi
