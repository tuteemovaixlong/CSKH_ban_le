#!/usr/bin/env python3
"""Static deployment contract checks used by CI and release workflows."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]
PGVECTOR = "pgvector/pgvector:0.8.6-pg16-bookworm@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b"


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def require(path, *needles):
    source = text(path)
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise SystemExit(f"{path} is missing deployment contract markers: {missing}")
    return source


def check_integration_secrets_contract():
    """Enforce W6.1b-D5 Compose secret mounts, env-only paths, and .dockerignore exclusion."""
    pg_compose = text("deploy/compose.postgres.yaml")
    pub_compose = text("deploy/compose.public.yaml")
    api_compose = text("deploy/compose.api.yaml")
    dockerfile = text("Dockerfile")
    dockerignore = text(".dockerignore")

    # 1. Both integration secrets declared as file: under ./integration-secrets/
    for secret_name in ("retailops_connector_marketplace_sim", "retailops_event_digest_key"):
        pattern = re.compile(
            rf"(?m)^  {re.escape(secret_name)}:\s*\n    file:\s*\./integration-secrets/{re.escape(secret_name)}\s*$"
        )
        if not pattern.search(pg_compose):
            raise SystemExit(
                f"deploy/compose.postgres.yaml must declare file secret '{secret_name}' under ./integration-secrets/"
            )

    # 2. web service receives both secrets via secrets:
    web_section = pg_compose.split("  postgres:", 1)[0]
    for secret_name in ("retailops_connector_marketplace_sim", "retailops_event_digest_key"):
        if not re.search(rf"(?m)^\s*-\s*{re.escape(secret_name)}\s*$", web_section):
            raise SystemExit(
                f"deploy/compose.postgres.yaml web service must mount '{secret_name}' via secrets:"
            )

    # 3. Never bind-mount any directory onto /run/secrets across any compose file
    for cname, content in (
        ("deploy/compose.postgres.yaml", pg_compose),
        ("deploy/compose.public.yaml", pub_compose),
        ("deploy/compose.api.yaml", api_compose),
    ):
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and ":/run/secrets" in stripped:
                raise SystemExit(
                    f"{cname} must never bind-mount a directory onto /run/secrets: {stripped}"
                )

    # 4. Connector and digest env vars must only point to paths under /run/secrets (never inline secret values)
    for cname, content in (
        ("deploy/compose.postgres.yaml", pg_compose),
        ("deploy/compose.public.yaml", pub_compose),
        ("deploy/compose.api.yaml", api_compose),
    ):
        for line in content.splitlines():
            m = re.match(r"^\s*(RETAILOPS_(?:CONNECTOR|EVENT_DIGEST)[A-Z0-9_]*)\s*:\s*(.+?)\s*$", line)
            if m:
                key, val = m.group(1), m.group(2).strip().strip("\"'")
                if not val.startswith("/run/secrets"):
                    raise SystemExit(
                        f"{cname} env var {key} must be a path under /run/secrets, got {val!r}"
                    )
    require(
        "deploy/compose.postgres.yaml",
        "RETAILOPS_CONNECTOR_SECRETS_DIR: /run/secrets",
        "RETAILOPS_EVENT_DIGEST_KEY_FILE: /run/secrets/retailops_event_digest_key",
    )

    # 5. Dockerfile copies data/connectors, never copies integration-secrets; .dockerignore forbids integration-secrets/
    require("Dockerfile", "data/connectors")
    if "integration-secrets" in dockerfile:
        raise SystemExit("Dockerfile must never reference or COPY integration-secrets")
    require(".dockerignore", "!data/connectors/")
    for line in dockerignore.splitlines():
        stripped = line.strip()
        if stripped.startswith("!") and "integration-secrets" in stripped:
            raise SystemExit(f".dockerignore must never allow integration-secrets/: {stripped}")


def main():
    require("Dockerfile", "deploy/rollout-public-web.sh", "deploy/cutover-postgres.sh",
            "deploy/enable-pgvector.sh", "data/knowledge", "notebooks")
    require(".dockerignore", "!notebooks/", "!notebooks/**")
    check_integration_secrets_contract()
    publish = require("deploy/publish_and_activate.py", "rollout-public-web.sh", "docker cp",
                      "Public web rollout checked for the activated image", "ssm_run",
                      "EC2 DEPLOY PREFLIGHT", "EC2_ROOT_DISK_LOW",
                      "docker image prune -af", "docker builder prune -af",
                      "EC2 DISK AFTER RELEASE CLEANUP", "failed_before_shell")
    ast.parse(publish, filename="deploy/publish_and_activate.py")
    require("deploy/compose.postgres.yaml", PGVECTOR)
    require("deploy/init-postgres.sh", "CREATE EXTENSION vector WITH SCHEMA retailops_extensions",
            "GRANT USAGE ON SCHEMA retailops_extensions TO retailops")
    require("deploy/rollout-public-web.sh", "deployed.env", "previous_image", "deployed.rollback.",
            "--force-recreate", "--no-deps", "compose.clamav.yaml", "verify_live", "sha256sum",
            "PUBLIC_WEB_ROLLBACK_OK", "PUBLIC_WEB_ROLLOUT_OK")
    require("deploy/admin-console.py", "compose.clamav.yaml")
    require("deploy/live-e2e.py", "compose.clamav.yaml")
    require("deploy/cutover-postgres.sh", PGVECTOR, "docker pull", "POSTGRES_IMAGE_READY",
            "database migrate", "Public HTTPS did not become ready after PostgreSQL cutover.")
    require("deploy/enable-pgvector.sh", PGVECTOR, "pg_dump", "CREATE EXTENSION IF NOT EXISTS vector",
            "database migrate", "PGVECTOR_PUBLIC_HEALTH_OK", "PGVECTOR_ENABLE_COMPLETE")
    require("deploy/start-public-web.sh", "RETAILOPS_DEMO_TENANT_ID", "GOOGLE_AUTH_TENANT_ID",
            "required <= set(values) <= (required | optional)",
            "Conflicting tenant selectors in public.env.")
    print("DEPLOYMENT_CONTRACT_OK")


if __name__ == "__main__":
    main()
