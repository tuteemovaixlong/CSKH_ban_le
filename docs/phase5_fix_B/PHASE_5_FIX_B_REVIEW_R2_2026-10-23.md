# Phase 5 Fix B — focused independent review R2

**Date:** 2026-10-23  
**Verdict:** **FAIL — CHANGES REQUIRED.** The live cleanup remains **BLOCKED**.

## Scope and review basis

This review covers the Fix B candidate for one-time removal of demo order `O-819126`, based on merged Fix A SHA `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e`. The candidate is still uncommitted in the managed worktree `fixb-readonly-dry-run`. Findings below are transcribed and normalized from the review report supplied for this review round. This documentation update did not change or retest the candidate code.

No AWS/SSM/EC2, production database or secret, deployment, backup, live dry-run, or purge was used. The earlier review remains at [R1](PHASE_5_FIX_B_REVIEW_2026-10-23.md); this R2 record supersedes its “independent review pending” status.

## Findings

### FIXB-1 — P1: backend/DSN resolution is not fully fail-closed and may expose connection secrets

**Affected areas:** `scripts/purge_demo_order.py` DSN resolution and `main`; `retailops/storage/postgres.py` DSN validation and exception handling.

- The CLI does not call the shared `validate_dsn()` before constructing the PostgreSQL session store. A malformed DSN or secret-file content can reach `psycopg.connect`; raw driver exception text may include connection parameters and is currently surfaced in CLI error output.
- A DSN missing required fields can be left to libpq defaults instead of being rejected by the application contract.
- `RETAILOPS_STORAGE_BACKEND=postgresql` with no DSN can fall back to SQLite when `RETAILOPS_DATA_DIR` is set; an unknown backend should also fail, not select a default.
- Simultaneous DSN sources (`RETAILOPS_DATABASE_URL` and `RETAILOPS_DATABASE_URL_FILE`) or PostgreSQL DSN plus SQLite `--data-dir` are not rejected as configuration conflicts.

**Required resolution:** validate and normalize configuration before any connection; enforce explicit backend selection; reject missing, unreadable, malformed, incomplete, or conflicting configuration without fallback; sanitize connection errors so no raw DSN, password, token, or driver detail is emitted.

**Gate impact:** blocks code acceptance, synthetic PostgreSQL CI acceptance, and any live dry-run.

### FIXB-2 — P2: no real PostgreSQL integration coverage for the Fix B CLI path

The current targeted tests use temporary SQLite or a mocked PostgreSQL driver. They do not exercise the CLI against a real PostgreSQL service using `RETAILOPS_DATABASE_URL_FILE`, nor prove server-enforced read-only behavior and maintenance-free execution end to end.

**Required resolution:** add disposable PostgreSQL integration tests and run them in the existing PostgreSQL/pgvector CI job. Cover CLI dry-run and explicit `--execute` with `maintenance=False`; verify the dry-run's `SET TRANSACTION READ ONLY` is enforced by PostgreSQL, sentinel session/rate-limit rows remain unchanged, and execution behavior is transactional. Do not substitute a mock for this integration evidence.

**Gate impact:** blocks synthetic PostgreSQL CI acceptance and the live dry-run gate.

### FIXB-3 — P2: Fix A evidence and project indexes still contain unsafe/stale runbook instructions

At review time, `docs/phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md` presented old Step 1/Step 2 commands as operational instructions. The review report identifies incorrect paths/files and environment variables, unsafe inference of `tenant_id` from a schema name, and database password variables that do not match the deployed secret-file contract. The evidence also recorded obsolete purge response/audit field names. Project indexes referred to the retired “4-step Session Manager procedure,” contradicting the retraction notice.

**Required resolution:** remove the obsolete command blocks and any remaining instruction to run the retired four-step procedure; explicitly mark it `DO NOT RUN / SUPERSEDED`; correct the described API/audit/tombstone fields against source; link operators only to the current Fix B acceptance gates, which contain no production-ready command until the code/CI/live approvals exist.

**Gate impact:** blocks documentation acceptance and live dry-run. It does not by itself break the existing docs contract checker.

**Documentation follow-up (2026-10-23):** a doc-only update has since added a prominent `DO NOT RUN / SUPERSEDED` notice to Fix A evidence, corrected the described tombstone/audit/import fields, and updated the active project indexes to point to Fix B. The legacy command blocks remain physically present for now; FIXB-3 remains open until they are removed or moved to an explicitly historical archive and the final link/contract checks pass. This follow-up did not modify code or claim that the candidate passed review.

### FIXB-4 — P3: backend error parity and tombstone amount type are inconsistent

- A write attempt through a PostgreSQL store opened read-only raises `ValueError`, unlike SQLite's `ApiError(409, "read_only_store")`; the CLI can misreport it as a configuration failure.
- `IdentityStore.connection()` may allow SQLite errors to escape as a raw traceback instead of the sanitized `database_unavailable` API error.
- `_ensure_purge_tombstone_table()` defines `amount` as `INTEGER`, while canonical PostgreSQL DDL uses `BIGINT`.

**Required resolution:** align read-only error semantics across backends, translate SQLite connection failures into the established safe error contract, and use the canonical `BIGINT` type. Add focused tests, including the previously uninitialized tombstone-table path.

**Gate impact:** must be fixed before final code acceptance and synthetic PostgreSQL rehearsal; it is not an approval to defer the type mismatch merely because the current demo amount fits in 32 bits.

## Evidence and skips

The supplied report states that `python -B -m unittest -v tests.test_phase5_fix_a` passed **5/5**, docs contract passed **4/4**, and `git diff --check` passed. It also reports static confirmation of maintenance-free/read-only construction and a mocked transaction test. These are recorded as reported evidence, not newly rerun in this documentation-only update.

Real PostgreSQL/pgvector integration for this candidate was **not run**; the report says local `psycopg`/PostgreSQL service was unavailable and identifies the missing CLI integration coverage above. AWS/SSM/EC2, image identity, production secret/DB, tenant mapping, backup/restore, live dry-run, and execute were **NOT RUN**.

## Decision and next gate

**Do not merge, deploy, start EC2 for this operation, or run a live dry-run/purge.** First address FIXB-1 through FIXB-4 in the isolated candidate, update the affected documents, run targeted local tests and docs checks, then run PostgreSQL/pgvector CI on the exact candidate and obtain a fresh independent review. Only a later, separately approved operational window may begin the production gates in [acceptance criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md).

Related: [packet index](README.md) · [criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) · [evidence](PHASE_5_FIX_B_EVIDENCE.md) · [execution handoff](PHASE_5_FIX_B_EXECUTION_HANDOFF.md) · [Fix A evidence](../phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md).
