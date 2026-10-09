# Operations runbook (source-backed)

> Read-only operating reference. It records repository commands and guards; it does not execute deployment, AWS, live-E2E or paid inference.
>
> Cache: [`../_digest/code/INFRA.digest`](../_digest/code/INFRA.digest). Gates: [`../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md`](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md) and [`../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md`](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md).

## 1. Before deployment

1. Confirm Docker/Compose, AWS CLI v2, Python 3.11+, SSM and outbound SSM/ECR access; keep ECR private with immutable tags/digests (`../../deploy/SETUP.md:6-15`).
2. Bootstrap runner, compose, artifact directory and environment through the existing admin channel; CD does not synchronize host scripts or migrations (`../../deploy/SETUP.md:16-35`).
3. Configure `demo`, OIDC trust and repository variables; set `RETAILOPS_DEPLOY_ENABLED=true` only after bootstrap (`../../deploy/SETUP.md:37-114`).
4. Treat CI as packaging/source verification: setup explicitly says it does not prove an online model or acceptable quality (`../../deploy/SETUP.md:116-127`).

## 2. CI and packaging

Offline CI runs documentation/dataset/live-E2E/notebook contracts, unit/pgvector/HTTP tests, deployment checks, image/package checks and HTTPS checks (`../../.github/workflows/ci.yml:70-96;175-194`). Deployment repeats source/tests/image checks before AWS credentials and activation (`../../.github/workflows/deploy-ec2.yml:52-71`). Portable Windows/Ubuntu and PostgreSQL checks are in the ops-console workflow (`../../.github/workflows/ops-console.yml:13-70`).

## 3. Release activation

The release script validates inputs, performs disk preflight, publishes and obtains a digest, then calls the EC2 runner with that digest (`../../deploy/publish_and_activate.py:112-155`). The runner verifies repository/digest syntax, locks deployment, pulls/tests the image, atomically updates `deployed.env` and preserves `previous.env` (`../../deploy/deploy-runner.sh:5-36`).

## 4. Public web and database overlays

The public stack puts `web` behind Caddy on 80/443 and waits for health; the API binds to host loopback (`../../deploy/compose.public.yaml:1-40`; `../../deploy/compose.api.yaml:1-30`). PostgreSQL is an overlay with file-backed secrets and no host port mapping (`../../deploy/compose.postgres.yaml:1-26`). Caddy serves only the configured DNS name with HSTS/header and timeout settings (`../../deploy/Caddyfile:1-24`).

## 5. Rollback and live boundary

`previous.env` is the prior image pointer; rollback uses a known digest and does not roll back a DB schema (`../../deploy/SETUP.md:129-139`). Live E2E is separately dispatched with `smoke` or `full` mode through SSM (`../../.github/workflows/live-e2e.yml:1-44`). Phase 4 keeps G5 as the only measurement-ready gate (`../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:87-91`).

## 6. Stop conditions

Stop and inspect when EC2 preflight reports less than 1 GiB free, the runner rejects image/repository/digest, SSM fails, or trusted HTTPS is not confirmed. These conditions are encoded in `publish_and_activate.py` (`../../deploy/publish_and_activate.py:127-143`), `deploy-runner.sh` (`../../deploy/deploy-runner.sh:9-20`) and public rollout (`../../deploy/rollout-public-web.sh:116-130`).
