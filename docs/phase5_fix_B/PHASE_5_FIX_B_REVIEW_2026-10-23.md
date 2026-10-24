# Phase 5 Fix B — Focused review: dry-run safety and backend selection

**Date:** 2026-10-23  
**Status:** Two source-level blockers identified and locally remediated; full independent review and PostgreSQL CI are still pending. **Production dry-run/cleanup is not ready.**

> **Historical R1 record:** superseded for current status by [focused review R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md), which records the subsequent **FAIL — CHANGES REQUIRED** verdict and four open findings. Do not use this R1 “review pending” status as the current decision.

## Scope and baseline

Review is limited to the purge CLI safety boundary for the one-time demo order `O-819126`, based on merged Fix A SHA `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e`. Code changes are isolated in managed worktree `fixb-readonly-dry-run`; the dirty primary workspace was not edited. No AWS/SSM/EC2, production DB, credentials, deployment, backup or purge was used.

## Initial findings

1. **P2 — CLI dry-run was not read-only end-to-end.** Although the purge method avoided target-row writes, CLI startup constructed session/store objects that performed session/rate-limit cleanup and schema migration/DDL before the purge query. This invalidated the advertised read-only dry-run.
2. **P2 — Missing PostgreSQL configuration could fall back to SQLite.** With neither DSN variable resolved, the CLI selected the local persistent directory (or defaulted under the source tree), so an apparently successful dry-run might inspect the wrong backend. A declared but missing DSN file also did not fail closed.
3. **P2 — Historical Fix A evidence showed an incompatible CLI command/output contract.** The documented command used flags absent from the merged parser (`--postgres-dsn`, `--expected-*`, `--operator`, `--dry-run`) and expected obsolete JSON fields. Those commands must not be run.

The independent source review found no separate blocker in the exact-tuple guard, tenant-scoped purge transaction, retention handling, tombstone/replay protection, or idempotency. That review was static and did not connect to a database.

## Local remediation

- Added explicit no-maintenance and read-only modes to the SQLite/PostgreSQL session/store construction path. Dry-run now avoids startup cleanup/migrations/DDL; PostgreSQL transactions use `SET TRANSACTION READ ONLY`; SQLite opens existing DB files with `mode=ro`.
- Changed backend selection to fail closed when no DSN is configured. A declared missing or empty DSN file aborts without selecting SQLite. SQLite is available only with explicit `--data-dir` / `RETAILOPS_DATA_DIR`.
- Added CLI regressions for missing backend/secret-file failure and for dry-run not invoking migrations/DDL or deleting expired session/rate-limit sentinel rows.
- Retracted the stale Step 3/4 shell commands in [Fix A evidence](../phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md).

## Verification and remaining gaps

- `python -m unittest tests.test_phase5_fix_a`: **5 tests PASS**. The Fix A functional/execute coverage used local temporary SQLite; one new PostgreSQL transaction-contract test uses a mock driver and confirms `SET TRANSACTION READ ONLY` is the first command. This did not touch production or any PostgreSQL server.
- Python 3.10 runtime has `langgraph` but not `psycopg`; real PostgreSQL integration tests for this patch were **not run locally**. In-memory Python `compile()` syntax checks across 9 changed Python files and `git diff --check` pass; CI PostgreSQL/pgvector is still required.
- Runtime/package review: source image build includes `scripts/` and the PostgreSQL driver; actual deployed image digest, Compose secret readability and DB backend remain unverified.
- No production command was run; live tenant, target tuple, backup/restore, rehearsal, dry-run and final execute approval are outstanding.

## Verdict

The changes are a narrow candidate worth independent Argon review, not a production go-ahead. Keep Fix B blocked until Argon reviews the exact diff, PostgreSQL CI passes, docs/CLI contract are consistent, and all operational criteria in [acceptance criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) are evidenced.

Related: [Fix B evidence](PHASE_5_FIX_B_EVIDENCE.md) · [handoff and Argon prompt](PHASE_5_FIX_B_EXECUTION_HANDOFF.md) · [Fix A packet](../phase5_fix_A/README.md).
