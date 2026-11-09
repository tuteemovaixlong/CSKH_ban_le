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

## 7. Controlled schema migrations (Business v8 and Business v9)

Application startup is read-only and fails closed whenever any tenant schema is below `BUSINESS_SCHEMA_CURRENT` (`../../retailops/storage/postgres.py`). Controlled migrations follow [§11.5](../phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md#115-migration-runbook-od-07) (`migrate-v5`..`migrate-v8`) and [W6.1b-1 section 6](../phase_role_aware_ops/W6_1B_1_EXECUTION_HANDOFF_2026-11-08.md) (`migrate-v9`), requiring separate owner approval before production execution:

- **Business v8 (W4):** install/verify `deploy/compose.clamav.yaml`, run read-only preflight, capture `pg_dump` backup, rehearse `python -m retailops database migrate-v8 --confirm-preflight --confirm-backup` on a scratch database copy, stop `web`, capture final pre-migration backup, run `database migrate-v8 --confirm-preflight --confirm-backup`, roll out image + Caddyfile, and run smoke verification.
- **Business v9 and integration intake rollout (W6.1b-1, [database guide](../../khoa_luan/07_co_so_du_lieu.md)):**
  1. **Backup and scratch rehearsal:** capture `pg_dump`, restore into a scratch DB copy following the [pgvector-compatible restore sequence](../POSTGRESQL.md#backup-restore-và-rollback), run `python -m retailops database migrate-v9 --confirm-preflight --confirm-backup`, and record `backfilled_orders` (re-running must report `upgraded: false`). Record the **storage location and scheduled deletion date of every backup** in the deploy log per [§20](../phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md#20-w61b-owner-decisions-2026-11-08); automated backup retention is not yet implemented, see [PERSISTENT_IDENTITY](../PERSISTENT_IDENTITY.md).
  2. **Provision host integration secrets:** create `/opt/retailops/integration-secrets/` with `postgres-secrets` permissions (`0700` owned by `root`; each secret `0444`, regular non-symlink file, ≥ 32 random bytes): `retailops_connector_marketplace_sim` and `retailops_event_digest_key` (`../../deploy/compose.postgres.yaml`). Never place secret bytes in the repository, env vars, logs, or chat; back up secret files separately from DB dumps.
  3. **Stop web, final backup, and migrate:** stop `web`, take the final pre-v9 `pg_dump` backup (`pg_restore --list` verified), and run `python -m retailops database migrate-v9 --confirm-preflight --confirm-backup`.
  4. **Roll out image and verify connectors:** note that `deploy/rollout-public-web.sh` only updates `compose.public.yaml` on the host, so before running rollout copy `compose.postgres.yaml` and `Caddyfile` from the new image onto `/opt/retailops/` and preserve the `import /etc/caddy/admin/*.caddy` line added by `deploy/admin-console.py` in the host `Caddyfile`. Then roll out the new image, register the production tenant connector via `python -m retailops connector add --tenant <tenant_id> --source-system marketplace_sim --kind marketplace --merchant-id <merchant_id> --secret-ref retailops_connector_marketplace_sim --status-mapping-file data/connectors/marketplace_sim.json`, and run `python -m retailops connector check --tenant <tenant_id>` — exit code must be `0` (stop and inspect startup logs otherwise).
  5. **Purge unreferenced legacy seed orders:** run `python -m retailops database purge-legacy-demo --tenant <tenant_id> --dry-run`; after owner review of the purge vs retained-by-action lists, run `purge-legacy-demo` without `--dry-run`.
  6. **Import canonical demo store events:** run `python -m retailops database import-events --tenant <tenant_id> --source-system marketplace_sim --file data/demo_events/store_events.jsonl --rebase-clock now` (`../../data/demo_events/store_events.jsonl`).
  7. **Post-deploy smoke and deploy record:** verify a demo customer asking `"đơn của tôi đang ở đâu"` receives a DB-backed `track_shipment` journey, confirm external requests to `/internal/*` receive `404` from Caddy (`../../deploy/Caddyfile`), and record the deploy log.
