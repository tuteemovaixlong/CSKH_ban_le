# Phase 5 Fix B — Evidence and status ledger

**Updated:** 2026-10-24 (+07)  
**Overall (2026-10-24): R5 INDEPENDENT STATIC REVIEW PASS / READY FOR PR/CI; POSTGRESQL CI PENDING; LIVE CLEANUP BLOCKED.** [independent review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md) found no additional blocker to PR/CI within Fix B scope. The reviewer made no edits, ran no tests and opened no DB. The primary agent reran local Fix A/B + guard `13/13`, docs `4/4`, deployment contract, notebook sync, YAML parsing and diff checks successfully. Earlier R5 targeted regression remains `102/102`; Ops Console `19 tests / 3 skipped`. These are not PostgreSQL CI evidence. Candidate remains uncommitted; no PR, CI, merge, deployment or live database operation has run.

## Status by gate

| ID | Status | Evidence / remaining work |
|---|---|---|
| FIXB-CODE-DRYRUN | REMEDIATED (local PASS; PG CI pending) | Default CLI dry-run sets `maintenance=False, read_only=True` with zero session/rate-limit cleanup, migration, or DDL. SQLite opens existing files in `?mode=ro`; PostgreSQL issues `SET TRANSACTION READ ONLY` first and maps `SQLSTATE 25006` to `ApiError(409, "read_only_store")`. Real PostgreSQL CI execution remains pending (`FIXB-PG-CI`). |
| FIXB-BACKEND | STATIC REVIEW PASS; PG CI pending | `scripts/purge_demo_order.py` (`_resolve_storage_target`) enforces explicit `RETAILOPS_STORAGE_BACKEND` (`sqlite`/`postgresql`), rejects unknown and whitespace-only selectors, requires a valid DSN when `postgresql` is selected, and never falls back to SQLite even if `--data-dir` or `RETAILOPS_DATA_DIR` is present (`tests/test_phase5_fix_a.py`). |
| FIXB-DSN | STATIC REVIEW PASS; PG CI pending | Shared `validate_dsn()` (`retailops/storage/postgres.py`) validates URI and libpq `key=value` structure plus required `dbname`/`user` before connecting; rejects simultaneous `RETAILOPS_DATABASE_URL` + `RETAILOPS_DATABASE_URL_FILE`, PostgreSQL DSN + `--data-dir`/`RETAILOPS_DATA_DIR`, and missing/empty/directory/unreadable DSN files; `transaction()` logs only `({exc.__class__.__name__})` with zero secret/DSN leakage (`tests/test_phase5_fix_a.py`). |
| FIXB-AUDIT | STATIC REVIEW PASS; PG CI pending | CLI now rejects `--execute` without explicit nonblank `--operator-id`; storage/persistent APIs no longer default to `cli-operator`; tests confirm missing and whitespace-only IDs abort before backend construction and a synthetic execute records an explicit operator (`tests/test_phase5_fix_a.py`). |
| FIXB-PG-CI | IMPLEMENTED; local PostgreSQL tests NOT RUN / CI pending | All destructive suites, including `opsconsole/tests/test_usage_postgres.py` and `opsconsole/tests/test_account_usage_postgres.py`, call the shared guard before connecting. Guard checks exact database, literal loopback, conninfo redirects and ambient libpq overrides. `tests/test_postgres_test_guard.py` now passes `5/5`; Ops Console runner: `19` tests, `3` skipped (`2` PostgreSQL unavailable locally, `1` symlink capability). CI opt-in is limited to the relevant test/preparation steps, including the packaged-container test. Exact-candidate PostgreSQL/pgvector CI with `0 skipped` is still required. |
| FIXB-ERRORS | REMEDIATED (local PASS; PG CI pending) | SQLite and PostgreSQL read-only write attempts raise `ApiError(409, "read_only_store")`; `IdentityStore.connection()` and `BusinessStore.connection()` wrap corrupt/unavailable `sqlite3.Error` into `ApiError(503, "database_unavailable")` while preserving `IntegrityError`/`ProgrammingError`; `_ensure_purge_tombstone_table()` defines `amount BIGINT NOT NULL` (`tests/test_phase5_fix_a.py`, `tests/test_postgres.py`). |
| FIXB-DOCS | STATIC REVIEW PASS | Retired Step 1–4 shell command blocks physically removed from [Fix A evidence](../phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md) with explicit `DO NOT RUN / SUPERSEDED` notice; stale 4-step Session Manager instructions removed from `CURRENT_PROJECT_STATUS.md` and Fix A criteria/README; all docs contract and relative link checks pass. |
| FIXB-SOURCE | PENDING | Candidate worktree `C:\Users\HP\.codex\worktrees\fixb-readonly-dry-run\CSKH_ban_le` is based on `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e`; changes remain uncommitted per handoff stop rule. No deployed image/source match verification. |
| FIXB-ENV | UNKNOWN / NOT RUN | No EC2/SSM status check was made. |
| FIXB-TARGET | NOT RUN | No production tenant mapping or order query. Historical tuple is not live evidence. |
| FIXB-CATALOG | NOT RUN | No cloud catalog read. |
| FIXB-BACKUP | NOT RUN | No production backup, secret access, archive check, or restore. |
| FIXB-REHEARSAL | PARTIAL (SQLite local; PG CI pending) | Local synthetic SQLite CLI dry-run + execute + uninitialized tombstone `BIGINT` verified; real PostgreSQL rehearsal awaits CI `offline` job. |
| FIXB-DRYRUN | NOT RUN | No live dry-run and no production DB connection. |
| FIXB-EXECUTE | NOT RUN | No production write or purge. |
| FIXB-POSTCHECK | NOT RUN | No runtime/browser/DB post-check. |
| FIXB-RETENTION | CODE CONTRACT ONLY | Purge implementation preserves old `business_events`, `imported_events`, and conversation turns/feedback while unlinking `conversations.order_id`; no live count evidence. |
| FIXB-DEPLOY-APPROVAL | NOT APPROVED / NOT RUN | No deploy workflow was dispatched. |

## R5 independent review and local rerun — 2026-10-24

- [independent review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md): static code/test/workflow and docs review PASS; READY FOR PR/CI. No remaining PR/CI-blocking finding in Fix B scope. The reviewer ran no tests and accessed no database.
- Primary-agent rerun: `python -B -m unittest tests.test_phase5_fix_a tests.test_postgres_test_guard -v` → `13 tests`, `0 skipped`, PASS.
- Docs contract `4/4`, deployment contract, notebook sync, both workflow YAML parses and `git diff --check` PASS. No production or PostgreSQL CI action.

## Local test and contract evidence (non-production; verified 2026-10-23 with `PYTHONDONTWRITEBYTECODE=1` and `python -B`)

- `python -B -m unittest tests.test_phase5_fix_a -v`: **`Ran 8 tests` → `OK` (`0 skipped`)**, covering Fix A UI/data contracts plus Fix B DSN/backend fail-closed & secret-canary redaction, explicit operator attribution for execute, SQLite/PostgreSQL `409 read_only_store` parity, corrupt `identity.sqlite3`/`corrupt_shop.sqlite3` `503 database_unavailable`, and uninitialized `order_purge_tombstones` `BIGINT` creation on `--execute`.
- `python -B -m unittest tests.test_phase5_fix_a tests.test_schema_migration tests.test_phase5_google_identity tests.test_phase5_e_ai_trust_and_governance tests.test_pr_a_correctness -v`: **`Ran 102 tests` → `OK` (`0 skipped`)**, confirming zero regression across schema migration (`IntegrityError` passthrough), Google identity, P5-E governance, and PR A `check_schema` / `503 database_unavailable` contracts.
- `python -B -m unittest discover -s tests -p "test_postgres_test_guard.py" -v`: **`Ran 5 tests` → `OK` (`0 skipped`)** for opt-in, exact DB name, loopback, conninfo redirects, and ambient libpq overrides without echoing values.
- `python -B scripts/check_ops_console.py`: **`Ran 19 tests` → `OK (skipped=3)`**; both PostgreSQL integration tests were skipped because no local disposable PostgreSQL/DSN is configured; one symlink test was skipped because the OS disallows symlinks. The new PostgreSQL suite guards therefore still require CI execution.
- `python -B -m unittest discover -s tests -p "test_postgres.py" -v`: **`Ran 40 tests` → `OK (skipped=40)`**; `test_phase5_sales_postgres.py`: **`Ran 13 tests` → `OK (skipped=13)`**. Local Python 3.10 lacks `psycopg`/disposable PostgreSQL, so these are not PostgreSQL PASS; CI `offline` job (`0 skipped`) is mandatory.
- In-memory `compile()` check across all modified Python files, including the shared PostgreSQL test guard and its callers: **PASS** (`0` `.pyc` / `__pycache__` written). A direct `py_compile` attempt was denied while trying to create `scripts/__pycache__`; no cache was written, and the in-memory compile check passed instead.
- Documentation & repository contract checks:
  - `python -B scripts/check_docs_contract.py` → `SUCCESS` (`4/4` gates including Markdown relative-link resolution across `docs/**/*.md` and `README.md`).
  - `python -B scripts/check_deployment_contract.py` → `DEPLOYMENT_CONTRACT_OK`.
  - `python -B scripts/check_eval_dataset.py` → `EVAL_DATASET_OK`.
  - `python -B scripts/build_agent_notebook.py --check` → `AGENT_NOTEBOOK_SOURCE_SYNC_OK` (`notebooks/colab_agent.ipynb` synced with updated `retailops/` and `tests/` bundle).
  - `git diff --check` → clean (`0` whitespace/conflict errors).

## Review history and disposition

- [Review R1](PHASE_5_FIX_B_REVIEW_2026-10-23.md): initial dry-run/backend blocker identification on merged `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e`.
- [Review R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md): focused review of initial Fix B candidate returning **FAIL — CHANGES REQUIRED** (`FIXB-1`..`FIXB-4`).
- [Post-remediation review R3](PHASE_5_FIX_B_REVIEW_R3_2026-10-23.md): Argon remediation of `FIXB-1`..`FIXB-4` in uncommitted candidate; historical self-review, not an independent sign-off for R5. R4/R5 static re-review is complete in [independent review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md); GitHub Actions PostgreSQL/pgvector CI (`0 skipped`) remains pending.

- [independent review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md): independent read-only review PASS, READY FOR PR/CI; records R4 P1/P2/P3 resolutions and the pending PostgreSQL/live gates.

## Target and retention contract (not live verified)

Historical target tuple: `O-819126`, customer `CG-d9b82ffe`, product `P-602`, `delivered`, `520000` VND, old order snapshot `Quần tây ống đứng tôn dáng`. The current catalog item is expected to remain `Quần tây đen hàn quốc`. Tenant ID must be resolved from official identity mapping; do not infer it.

Expected retention: remove only the target order and scoped dependent operational rows; retain old business/security audit and imported-event history; keep conversation/turns/feedback but unlink the order; create a purge notice and tenant-local tombstone. These are requirements, **not live outcomes**.

Related: [independent review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md) · [historical self-review R3](PHASE_5_FIX_B_REVIEW_R3_2026-10-23.md) · [historical review R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md) · [criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) · [handoff](PHASE_5_FIX_B_EXECUTION_HANDOFF.md).
