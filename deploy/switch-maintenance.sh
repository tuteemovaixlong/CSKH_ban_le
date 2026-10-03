#!/usr/bin/env bash
# Operator utility to switch Caddy between standard operation and emergency auth maintenance mode.
# Usage: ./deploy/switch-maintenance.sh [enable|disable|status]
set -euo pipefail

TARGET_DIR="${RETAILOPS_DIR:-}"
if [[ -n "$TARGET_DIR" && -d "$TARGET_DIR" ]]; then
    cd "$TARGET_DIR"
elif [[ -f "Caddyfile" && -f "compose.public.yaml" ]]; then
    : # Keep current directory
elif [[ -d "/opt/retailops" ]]; then
    cd /opt/retailops
fi

ACTION="${1:-status}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.public.yaml}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-retailops-web}"

reload_or_restart_caddy() {
    if command -v docker >/dev/null 2>&1; then
        if ! docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null; then
            docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" restart caddy
        fi
    fi
}

if [[ "$ACTION" == "enable" ]]; then
    if grep -q '@auth_maintenance' Caddyfile 2>/dev/null; then
        echo "AUTH_MAINTENANCE_ALREADY_ENABLED"
        exit 0
    fi
    echo "Enabling emergency authentication maintenance mode (fail-closed 503 for login routes)..."
    test -f Caddyfile.maintenance || { echo "ERROR: Caddyfile.maintenance not found!" >&2; exit 1; }
    if [[ -f Caddyfile && ! -f Caddyfile.normal.bak ]]; then
        cp -p Caddyfile Caddyfile.normal.bak
    fi
    cp -f Caddyfile.maintenance Caddyfile
    reload_or_restart_caddy
    if ! grep -q '@auth_maintenance' Caddyfile 2>/dev/null; then
        echo "ERROR: Failed to apply maintenance Caddyfile!" >&2
        exit 1
    fi
    echo "AUTH_MAINTENANCE_ENABLED"
elif [[ "$ACTION" == "disable" ]]; then
    if ! grep -q '@auth_maintenance' Caddyfile 2>/dev/null; then
        echo "AUTH_MAINTENANCE_ALREADY_DISABLED"
        exit 0
    fi
    echo "Disabling auth maintenance mode (restoring normal login flows)..."
    if [[ -f Caddyfile.normal.bak ]]; then
        cp -f Caddyfile.normal.bak Caddyfile
        rm -f Caddyfile.normal.bak
    elif [[ -f Caddyfile.normal ]]; then
        cp -f Caddyfile.normal Caddyfile
    else
        echo "ERROR: Cannot disable maintenance mode: Neither Caddyfile.normal.bak nor Caddyfile.normal found!" >&2
        exit 1
    fi
    reload_or_restart_caddy
    if grep -q '@auth_maintenance' Caddyfile 2>/dev/null; then
        echo "ERROR: Failed to restore normal Caddyfile!" >&2
        exit 1
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
