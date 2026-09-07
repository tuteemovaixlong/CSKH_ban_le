#!/usr/bin/env python3
"""Static deployment contract checks used by CI and release workflows."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def require(path, *needles):
    source = text(path)
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise SystemExit(f"{path} is missing deployment contract markers: {missing}")
    return source


def main():
    require(
        "Dockerfile",
        "deploy/rollout-public-web.sh",
        "deploy/cutover-postgres.sh",
    )
    publish = require(
        "deploy/publish_and_activate.py",
        "rollout-public-web.sh",
        "docker cp",
        "Public web rollout checked for the activated image",
        "ssm_run",
    )
    ast.parse(publish, filename="deploy/publish_and_activate.py")
    require(
        "deploy/rollout-public-web.sh",
        "deployed.env",
        "previous.env",
        "--force-recreate",
        "verify_live",
        "sha256sum",
        "PUBLIC_WEB_ROLLBACK_OK",
        "PUBLIC_WEB_ROLLOUT_OK",
    )
    require(
        "deploy/cutover-postgres.sh",
        "postgres:16.15-bookworm",
        "docker pull",
        "POSTGRES_IMAGE_READY",
        "Public HTTPS did not become ready after PostgreSQL cutover.",
    )
    print("DEPLOYMENT_CONTRACT_OK")


if __name__ == "__main__":
    main()
