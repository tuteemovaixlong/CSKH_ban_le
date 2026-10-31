# Phase 5 Fix B — Post-remediation self-review R3 (Argon)

**Date:** 2026-10-23  
**Status:** **REMEDIATED IN UNCOMMITTED CANDIDATE — PENDING POSTGRESQL/PGVECTOR CI & INDEPENDENT RE-REVIEW.** Live production cleanup remains **BLOCKED**.

## Scope and review basis

This post-remediation review record covers the uncommitted Fix B candidate layered directly on top of the existing Fix B worktree `isolated Fix B worktree (machine path omitted)` at baseline merge SHA `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e`. Historical reviews [R1](PHASE_5_FIX_B_REVIEW_2026-10-23.md) and [R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md) are preserved intact without rewriting their historical verdicts.

No AWS/SSM/EC2 access, production secret/database access, deployment, backup, CI workflow dispatch, commit, merge, live dry-run, or live purge was performed. Primary workspace `primary checkout (machine path omitted)` (`stash@{0}`) and all other worktrees were left untouched.

## Resolution of R2 findings (`FIXB-1` through `FIXB-4`)

### FIXB-1 (P1) — Backend/DSN fail-closed resolution and secret redaction: **REMEDIATED (local unit PASS; PG CI pending)**

- `scripts/purge_demo_order.py` (`_resolve_storage_target`, `build_parser`, `main`):
  - Enforces explicit `RETAILOPS_STORAGE_BACKEND` validation (`""`, `"sqlite"`, or `"postgresql"`); unknown values abort with `ApiError(503, "database_configuration_invalid", ...)`.
  - When `RETAILOPS_STORAGE_BACKEND=postgresql`, requires a valid DSN from either `RETAILOPS_DATABASE_URL` or `RETAILOPS_DATABASE_URL_FILE` and **never** falls back to SQLite even if `--data-dir` or `RETAILOPS_DATA_DIR` is present.
  - Rejects simultaneous `RETAILOPS_DATABASE_URL` and `RETAILOPS_DATABASE_URL_FILE`, PostgreSQL DSN/backend combined with `--data-dir` or `RETAILOPS_DATA_DIR`, `RETAILOPS_STORAGE_BACKEND=sqlite` combined with a PostgreSQL DSN, whitespace-only env values, missing/empty DSN files (`database_configuration_missing`), and directory/unreadable DSN files (`database_configuration_invalid`).
  - Calls shared `validate_dsn(dsn)` (`retailops/storage/postgres.py`) before constructing `PostgresSessions`.
- `retailops/storage/postgres.py` (`_parse_dsn_options`, `validate_dsn`, `transaction`):
  - Validates URI (`postgresql://`, `postgres://`) and libpq `key=value` conninfo structure plus required `dbname` and `user` fields in pure Python first (and via `psycopg.conninfo.conninfo_to_dict` whenever `psycopg` is installed), never interpolating input DSN text into exceptions.
  - Sanitizes `transaction()` `except pg.Error as exc:` to emit only `({exc.__class__.__name__})` rather than `{exc}`, preventing raw driver connection strings, passwords, or tokens from leaking to HTTP responses or CLI `stderr`.
- **Verification:** `tests/test_phase5_fix_a.py::Phase5FixATests.test_fixb_purge_cli_dsn_validation_backend_conflicts_and_secret_redaction` exercises 15 fail-closed configuration/conflict subcases, `PermissionError` secret-file failures, and simulated `psycopg.OperationalError` driver failures with a secret canary, confirming exit code `2`, zero secret leakage on `stdout`/`stderr`, and zero session construction on failure.

### FIXB-2 (P2) — Real PostgreSQL CLI integration coverage: **IMPLEMENTED IN SOURCE; SKIPPED LOCALLY (`NOT RUN` until CI)**

- `tests/test_postgres.py::PostgresTests.test_purge_demo_order_cli_postgres_dry_run_readonly_and_execute_contract`:
  - Invokes the real `scripts/purge_demo_order.py` subprocess against disposable `RETAILOPS_TEST_DATABASE_URL` via a mode-`0600` `RETAILOPS_DATABASE_URL_FILE` secret file (`RETAILOPS_STORAGE_BACKEND=postgresql`, `RETAILOPS_DATABASE_URL=""`).
  - Drops `order_purge_tombstones` beforehand and seeds expired sentinels in `retailops_identity.sessions` and `retailops_identity.identity_rate`.
  - Proves PostgreSQL server-enforced `SET TRANSACTION READ ONLY` rejects `DELETE`, `INSERT`, and `CREATE TABLE` (`SQLSTATE 25006` → `ApiError(409, "read_only_store")`), CLI dry-run leaves `order_purge_tombstones` uncreated and expired sentinels intact, malformed subprocess DSN redacts secrets, mid-transaction `execute=True` failure rolls back partial deletes on real PostgreSQL, CLI `--execute` creates `order_purge_tombstones` with `amount` `data_type == 'bigint'` while keeping expired sentinels untouched, and a second CLI `--execute` returns `status="already_purged"` (`idempotent_replay=true`).
- **Verification boundary:** Local Python 3.10 environment does not have `psycopg` or a local disposable PostgreSQL service (`Ran 40 tests ... OK (skipped=40)`). Therefore `FIXB-PG-CI` remains **`NOT RUN / PENDING CI`** until GitHub Actions `ci.yml` (`offline` job with `pgvector/pgvector:0.8.6-pg16-bookworm`) executes with `0 skipped` on the committed candidate PR.

### FIXB-3 (P2) — Remove stale Fix A runbook blocks and reconcile linked docs: **REMEDIATED**

- `docs/phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md`: physically removed the retired Step 1 and Step 2 shell command blocks, preserved an explicit `DO NOT RUN / SUPERSEDED` notice explaining why Steps 1–4 were withdrawn, reconciled `FIXA-DATA5` status (`BLOCKED under Fix B`), verified source field contracts (`status="dry_run_verified"` / `"purged"` / `"already_purged"`, `ApiError(409, "order_purged_tombstone")`, `operator_id`, `pre_counts_json`, `post_counts_json`, `amount BIGINT NOT NULL`), and pointed operators exclusively to [Phase 5 Fix B](README.md).
- `docs/CURRENT_PROJECT_STATUS.md`, `docs/phase5_fix_A/PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md`, `docs/phase5_fix_A/README.md`, `docs/03_EVALUATION/ACCEPTANCE_MATRIX.md`, `docs/PLAN_ROADMAP_INDEX.md`, `docs/phase5/README.md`, and `docs/README.md`: removed remaining instructions to run the retired 4-step Session Manager procedure in Fix A evidence and aligned status/gate pointers with this post-remediation state.

### FIXB-4 (P3) — Backend error parity and tombstone `BIGINT`: **REMEDIATED (local unit PASS; PG CI pending)**

- `retailops/storage/pg_repositories.py` (`PostgresBusinessStore.connection`, `PostgresIdentityStore.connection`) and `retailops/storage/postgres.py` (`transaction` `SQLSTATE 25006`): aligned PostgreSQL read-only write rejections to `ApiError(409, 'read_only_store', ...)` matching SQLite (`BusinessStore.connection`, `IdentityStore.connection`), and preserved normal `check_schema(dsn, ...)` call compatibility (`tests/test_pr_a_correctness.py::test_n08_c1_postgresql_schema_guard_and_upgrade`).
- `retailops/identity/store.py` (`IdentityStore.connection`) and `retailops/business/store.py` (`BusinessStore.connection`): wrapped `sqlite3.Error` (corrupt/non-SQLite files, locked/unavailable DBs) into `ApiError(503, 'database_unavailable', ...)` (and `409 read_only_store` when SQLite `?mode=ro` blocks a write on a read-only store) while preserving `sqlite3.IntegrityError` and `sqlite3.ProgrammingError` passthrough and closing `db` safely in `finally`.
- `retailops/business/store.py` (`BusinessStore._ensure_purge_tombstone_table`): updated `amount` from `INTEGER NOT NULL` to `BIGINT NOT NULL` to match canonical `P5C_BUSINESS_DDL` (`retailops/storage/pg_schema.py`).
- **Verification:** `tests/test_phase5_fix_a.py::Phase5FixATests.test_fixb_backend_readonly_error_parity_corrupt_sqlite_and_uninitialized_tombstone_bigint` verifies SQLite/PostgreSQL `409 read_only_store` parity, corrupt `identity.sqlite3` and `corrupt_shop.sqlite3` `503 database_unavailable` translation (including via CLI), and uninitialized `order_purge_tombstones` staying absent on dry-run then being created with `BIGINT NOT NULL` on `--execute`.

## Remaining blockers before production readiness

1. **PostgreSQL/pgvector CI (`FIXB-PG-CI`):** `NOT RUN` on this uncommitted candidate (`40 skipped` locally due to absent `psycopg`/PostgreSQL service). Must run in GitHub Actions `ci.yml` (`offline` job) with `0 skipped` after branch/PR creation is authorized.
2. **Independent re-review:** A fresh independent review on the updated candidate diff + green PostgreSQL CI run is required before merge.
3. **Operational gates (`FIXB-SOURCE`, `FIXB-ENV`, `FIXB-TARGET`, `FIXB-CATALOG`, `FIXB-BACKUP`, `FIXB-REHEARSAL`, `FIXB-DRYRUN`, `FIXB-EXECUTE`, `FIXB-POSTCHECK`, `FIXB-DEPLOY-APPROVAL`):** All remain **NOT RUN / BLOCKED** pending code/CI sign-off and separate owner operational approvals.

Related: [packet index](README.md) · [historical review R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md) · [historical review R1](PHASE_5_FIX_B_REVIEW_2026-10-23.md) · [criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) · [evidence](PHASE_5_FIX_B_EVIDENCE.md) · [execution handoff](PHASE_5_FIX_B_EXECUTION_HANDOFF.md).
