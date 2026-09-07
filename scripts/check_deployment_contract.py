#!/usr/bin/env python3
"""Static deployment contract checks used by CI and release workflows."""
from pathlib import Path
import ast

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


def main():
    require("Dockerfile", "deploy/rollout-public-web.sh", "deploy/cutover-postgres.sh",
            "deploy/enable-pgvector.sh", "data/knowledge")
    publish = require("deploy/publish_and_activate.py", "rollout-public-web.sh", "docker cp",
                      "Public web rollout checked for the activated image", "ssm_run")
    ast.parse(publish, filename="deploy/publish_and_activate.py")
    require("deploy/compose.postgres.yaml", PGVECTOR)
    require("deploy/init-postgres.sh", "CREATE EXTENSION vector WITH SCHEMA retailops_extensions",
            "GRANT USAGE ON SCHEMA retailops_extensions TO retailops")
    require("deploy/rollout-public-web.sh", "deployed.env", "previous_image", "deployed.rollback.",
            "--force-recreate", "verify_live", "sha256sum", "PUBLIC_WEB_ROLLBACK_OK", "PUBLIC_WEB_ROLLOUT_OK")
    require("deploy/cutover-postgres.sh", PGVECTOR, "docker pull", "POSTGRES_IMAGE_READY",
            "database migrate", "Public HTTPS did not become ready after PostgreSQL cutover.")
    require("deploy/enable-pgvector.sh", PGVECTOR, "pg_dump", "CREATE EXTENSION IF NOT EXISTS vector",
            "database migrate", "PGVECTOR_PUBLIC_HEALTH_OK", "PGVECTOR_ENABLE_COMPLETE")
    print("DEPLOYMENT_CONTRACT_OK")


if __name__ == "__main__":
    main()
