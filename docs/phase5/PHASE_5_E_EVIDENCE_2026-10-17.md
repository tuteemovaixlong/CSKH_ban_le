# Phase 5-E Evidence Packet — AI Trust & Safety, Account/Quota Governance, and Catalog Hygiene

> **Date:** 2026-10-19 (Round 3 Bounded Remediation `AI1`/`DATA1`/`AI5` on PR #43; see active snapshot [PHASE_5_E_EVIDENCE_2026-10-18.md](PHASE_5_E_EVIDENCE_2026-10-18.md))
> **Baseline (PR #42 merged):** `44540eab516831d5c8232dd80392b8e20c6cd47e`
> **Prior Reviewed Candidates:**
> - Round 1: `7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb`
> - Round 2 Input Candidate: `baa70b15731fd82b909c36e0b89cb7d9b41ca342`
> - Round 2 Reviewed Candidate: `982801144702b703eb9af3d4d1435a3a75b1b1e4` (tested merge `50fa050b4c9fa7afea59c6201e4f29aca8d4274d`, CI `39140778461`, Ops Console `39140778477`; [Independent Review](REVIEW_ARGON_P5_E_2026-10-18.md) — `CHANGES REQUIRED` on `AI1`, `DATA1`, `AI5` only)
> **Round 3 Code Candidate:** `97b11bbcaa67a7b2f4297e63437d5802ee789384` (tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`, [CI 39203490030](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490030) `SUCCESS` [`offline` `117901231330`: `701` tests, `0 skipped`; `colab-python313` `117901231538`], [Ops Console 39203490035](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490035) `SUCCESS` [`postgres` `117901231247`: `19` tests, `0 skipped`; portable `117901231530`/`117901231463`: `19` tests, `skipped=2`])
> **Workstream Branch & PR:** `feat/phase5-e-ai-trust-account-governance` ([PR #43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43))
> **Authoritative Specs:** [PHASE_5_E_EVIDENCE_2026-10-18.md](PHASE_5_E_EVIDENCE_2026-10-18.md) | [PHASE_5_E_ACCEPTANCE_CRITERIA.md](PHASE_5_E_ACCEPTANCE_CRITERIA.md) | [PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md) | [PHASE_5_E_EXECUTION_HANDOFF.md](PHASE_5_E_EXECUTION_HANDOFF.md) | [ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md](ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md) | [REVIEW_ARGON_P5_E_2026-10-18.md](REVIEW_ARGON_P5_E_2026-10-18.md)
> **Scope & Gate Notice:** This packet records the implementer self-report and offline deterministic code, SQLite, UI, and CI PostgreSQL 16 + pgvector evidence for the 14 Phase 5-E criteria (`P5-E-AI1..AI6`, `P5-E-ADM1..ADM6`, `P5-E-DATA1..DATA2`) and the Round 2 + Round 3 bounded remediations. Independent Codex review is required before PR #43 is marked `PASS`. Passing P5-E does **not** automatically close `G4` or authorize `G5`/`G6`/`G7` live/paid performance benchmarking.

---

## 1. Round 2 Bounded Remediation Summary (`R1`..`R6` from `baa70b15731fd82b909c36e0b89cb7d9b41ca342`)

| Item | Reviewer Finding on `baa70b1` ([REVIEW_ARGON_P5_E_2026-10-18.md](REVIEW_ARGON_P5_E_2026-10-18.md)) | Remediation Implemented | Verification Evidence |
|---|---|---|---|
| **R1 (`P5-E-AI1`)** | `Application.chat()` only sanitized `answer["message"]` and final-message strings, leaving structured channels (`answer["messages"]` `tool_calls`/`tool` content, `answer["trace"]` events/steps/tool payloads, `bound.human_support`, `conversation_feedback.comment`) and legacy/pre-existing rows in `replay()`, `conversation_transcript()`, `history()`, `feedbacks()`, `escalations()` unsanitized. | Added `sanitize_structured_payload` in `retailops/guardrails/topic_filter.py` (preserving raw CoT `reasoning`/`thought`/`_reasoning` and user messages). Applied write-time sanitization across `answer["messages"]`, `answer["trace"]`, `bound.human_support`, `BoundTools("request_human_support")`, and `record_feedback()`, plus read-time sanitization in `replay()`, `history()`, `feedbacks()`, `escalations()`, `list_conversations()`, and `conversation_transcript()` on both `BusinessStore` (`retailops/business/store.py`) and `PostgresBusinessStore` (`retailops/storage/pg_repositories.py`). | `test_p5e_ai1_prompt_injection_persona_encoding_exfiltration_resistance` (SQLite, `multi_agent` + `single_agent`, structured channels + pre-existing poisoned turn/feedback rows) & `test_phase5_e_postgres_governance_and_ai_boundaries` (`tests/test_postgres.py`). |
| **R2 (`P5-E-ADM1` / `ADM4`)** | **CLOSED** in `REVIEW_ARGON_P5_E_2026-10-18.md`. | Preserved `upgrade_sqlite_memberships_role_constraint(path, *, fail_hook=None)` in `retailops/identity/store.py` and added post-`DROP TABLE memberships` rollback assertion in `test_p5e_r2_sqlite_legacy_schema_role_migration_and_rollback`. | `test_p5e_r2_sqlite_legacy_schema_role_migration_and_rollback` (`tests/test_phase5_e_ai_trust_and_governance.py`). |
| **R3 (`P5-E-DATA1`)** | `seed_demo_sample_orders` used `% 200000` (allowing `O-900000..O-900001` outside `_DEMO_SAMPLE_P602_ORDER_RE = r"^O-[78]\d{5}$"`), and returning demo customers with pre-existing 3-order sample triplets lacked idempotent provenance backfill. | Changed modulo to `seed_base = 700000 + (abs(hash(customer_id)) % 199990)` (`O-700001..O-899992`) and added idempotent `demo_sample_fixture_seeded` backfill when a returning customer has the exact 3 consecutive `P-601`/`P-602`/`P-603` demo sample orders in both `BusinessStore` and `PostgresBusinessStore`. | `test_p5e_data1_demo_sample_order_label_and_ssot_consistency` (including high-hash `% 200000 >= 199999` customer + returning customer backfill + negative `O-123456`/`O-754321`) & `test_phase5_e_postgres_governance_and_ai_boundaries`. |
| **R4 (`P5-E-ADM2..ADM4`)** | (1) `admin_list_accounts` applied `LIMIT` before filtering by `q` in SQLite; (2) changing `#admin-tenant-id-input` in `web/app.js` kept stale `#admin-selected-membership-id`; (3) `quota.next_reset_utc` was not rendered in `web/app.js`; (4) no way to clear/remove an active quota override (`daily_limit = null`). | (1) Filtered by `q` before slicing `[:limit]` in `IdentityStore.admin_list_accounts`; (2) added `clearAdminSelectedAccount()` on `#admin-tenant-id-input` change, client/server `tenant_id` scope verification (`409 tenant_scope_mismatch` + denied audit log), and confirmation checkbox reset; (3) rendered `quota.next_reset_utc` in `loadAdminAccounts` and `inspectAdminAccount`; (4) supported `daily_limit=None` (`null`) in `admin_set_quota_override`, `POST /api/admin/accounts/{id}/quota`, and UI (`#btn-admin-clear-quota` / `submitAdminClearQuotaOverride`). | `test_p5e_adm1_and_adm2_authz_boundary_and_scoped_account_view`, `test_p5e_adm3_account_suspend_reactivate_and_session_revocation`, `test_p5e_adm4_quota_inspection_and_bounded_override_with_expiry_and_persistence`, `tests/test_public_session.js`, and `tests/test_postgres.py`. |
| **R5 (`P5-E-AI2` / `AI4` / `AI5` & Tests)** | (1) `request_human_support` could still write `conversation_feedback` during read-only lookup (`AI2`); (2) `AI4` grounding was not enforced in runtime against hostile model outputs fabricating `P-604` price/stock/warranty, omitting `list_orders` truncation, or claiming false order cancellation; (3) raw `TimeoutError` in `agent.py`/`read_worker.py`/`dispute_agent.py` raised `502`/`500` instead of `504 agent_timeout` (`AI5`). | (1) Blocked `request_human_support` side effects when `read_only_lookup` is True across `BoundTools`, `supervisor.py`, `graph.py`, and `Application.chat`; (2) added `enforce_final_answer_grounding` in `retailops/guardrails/topic_filter.py` and wired it into `Application.chat`; (3) mapped `TimeoutError` to `AgentError('agent_timeout')` (`504`) in `agent.py`, `read_worker.py`, and `dispute_agent.py`; (4) expanded SQLite, PostgreSQL, and Node UI tests with hostile model mocks. | `tests/test_phase5_e_ai_trust_and_governance.py` (14 tests, 0 skips), `tests/test_postgres.py` (`test_phase5_e_postgres_governance_and_ai_boundaries`), and `tests/test_public_session.js`. |
| **R6 (Evidence & Docs)** | Sync updated handoff/review/plan docs from primary workspace, update ADR & Evidence packet with exact SHAs, commands, counts, skips, and preserve `REVIEW_ARGON_P5_E_2026-10-18.md` verdict as `CHANGES REQUIRED` until Codex re-reviews. | Synced `PHASE_5_E_EXECUTION_HANDOFF.md`, `REVIEW_ARGON_P5_E_2026-10-18.md`, and `PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md`; updated `ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md` and `PHASE_5_E_EVIDENCE_2026-10-17.md`; rebuilt `notebooks/colab_agent.ipynb`. | `py -3.12 scripts/build_agent_notebook.py --check` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`) & `py -3.12 scripts/check_docs_contract.py` (`SUCCESS`). |

---

## 2. Criteria-to-Evidence Matrix (14 / 14 Criteria)

| Criterion | Implementation Files | SQLite / UI / Offline Deterministic Tests | PostgreSQL 16 + pgvector Integration Tests (`tests/test_postgres.py`) | Implementer Status (Pending Codex Re-Review) |
|---|---|---|---|---|
| **P5-E-AI1** — Prompt injection, persona override, encoding & secret/canary resistance across chat, structured channels (`messages`/`trace`/`human_support`/`feedback`), replay & legacy read-time channels | `retailops/guardrails/topic_filter.py`, `retailops_tools.py`, `retailops/business/application.py`, `retailops/business/store.py`, `retailops/storage/pg_repositories.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai1_prompt_injection_persona_encoding_exfiltration_resistance` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI2** — Read-only vs mutation intent boundary (blocking both `prepare_cancellation` and `request_human_support`) & explicit confirmation gate | `retailops/guardrails/topic_filter.py`, `retailops_tools.py`, `retailops/workflow/supervisor.py`, `retailops/workflow/graph.py`, `retailops/workflow/subagents/dispute_agent.py`, `retailops/business/application.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai2_no_unauthorized_mutation_under_conflicting_read_only_instructions_and_positive_control` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI3** — Entity, owner, tenant & Unicode confusable / SQL-like ID boundary | `retailops/business/store.py`, `retailops/storage/pg_repositories.py`, `retailops_tools.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai3_entity_and_owner_boundary_and_unicode_confusables` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI4** — Runtime factuality grounding (`enforce_final_answer_grounding`), unknown handling (`P-604`), no false-success cancellation claim, `order_not_found` guard, and `list_orders` truncation disclosure | `retailops/guardrails/topic_filter.py`, `retailops/business/application.py`, `retailops_tools.py`, `retailops/business/store.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai4_factuality_grounding_and_list_orders_truncation_contract` | `tests/test_postgres.py::PostgresTests.test_p604_catalog_seed_preserves_unknowns_and_is_idempotent_postgres` & `test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI5** — Timeout (`504` including raw `TimeoutError` in single/multi-agent), provider `429`, daily quota (`429`), and `503` truthfulness without false completion | `retailops/workflow/agent.py`, `retailops/workflow/subagents/read_worker.py`, `retailops/workflow/subagents/dispute_agent.py`, `retailops/business/application.py`, `retailops/account_usage.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai5_timeout_429_quota_503_truthfulness_and_no_false_completion` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI6** — Bounded, deterministic, zero-paid-call adversarial manifest (`EXPECTED_MANIFEST_SHA256` literal pinned + tamper-negative test) | `tests/test_phase5_e_ai_trust_and_governance.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai6_bounded_reproducible_adversarial_manifest` (`EXPECTED_MANIFEST_SHA256 = "b21dca25eb286080487c5df24949df13e7576db5e340dfdbfda15b5b83e7a2af"`) | Pure deterministic offline manifest test (runs in CI `offline` job with `skipped=0`) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM1** — Admin RBAC, tenant authorization boundary & SQLite/PG role schema (`customer`/`viewer`/`staff` denied; `manager` own-tenant; `platform_admin` explicit tenant) | `retailops/business/permissions.py`, `retailops/identity/contracts.py`, `retailops/identity/persistent.py`, `retailops/identity/store.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm1_and_adm2_authz_boundary_and_scoped_account_view`, `test_p5e_r2_sqlite_legacy_schema_role_migration_and_rollback`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM2** — Scoped account list/detail view & UI (`q` filtered before `limit`) without credential/token/cookie leakage | `retailops/identity/store.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `retailops/http/public.py`, `web/index.html`, `web/app.js` | `test_p5e_adm1_and_adm2_authz_boundary_and_scoped_account_view` (including >50 accounts `q=z999&limit=5`), `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM3** — Account suspend, reactivate, session revocation, self-lockout prevention, and tenant scope mismatch protection (`409 tenant_scope_mismatch` + UI selection reset on tenant change) | `retailops/identity/store.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm3_account_suspend_reactivate_and_session_revocation`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM4** — Per-membership quota inspection (`next_reset_utc` in API & UI), bounded override (`1..10000`), clear override (`daily_limit=None`), concurrent reservation, UTC reset, `effective_at`/`expires_at`, and restart persistence | `retailops/account_usage.py`, `retailops/identity/store.py`, `retailops/storage/pg_schema.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm4_quota_inspection_and_bounded_override_with_expiry_and_persistence`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM5** — Append-only `admin_audit_log` & transactional rollback if audit fails | `retailops/identity/store.py`, `retailops/storage/pg_schema.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm5_append_only_admin_audit_log_and_transactional_rollback`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM6** — Control-plane isolation, CSRF origin check on admin mutations, and Ops Console v1 read-only preservation | `retailops/http/public.py`, `retailops/http/routes.py`, `opsconsole/server.py` | `test_p5e_adm6_control_plane_isolation_and_csrf_protection`, `scripts/check_ops_console.py` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-DATA1** — Server-side provenance-scoped demo sample order label (`display_name: "Bộ xếp hình gỗ cho bé"`, `O-700001..O-899992`, idempotent returning-customer backfill) without mutating SSOT `P-602` or affecting non-demo `O-\d{6}` orders | `retailops/business/store.py`, `retailops/identity/persistent.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/app.js` | `test_p5e_data1_demo_sample_order_label_and_ssot_consistency`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-DATA2** — Incomplete catalog (`P-604`) natural-language alias lookup & null/zero variant stock seed fallback safety | `data/products.json`, `retailops/business/store.py`, `retailops/storage/pg_repositories.py`, `retailops_conversation.py` | `test_p5e_data2_incomplete_catalog_p604_and_variant_seed_fallback_safety` | `tests/test_postgres.py::PostgresTests.test_p604_catalog_seed_preserves_unknowns_and_is_idempotent_postgres` & `test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |

---

## 3. Explicit Policy Decisions & Scope Limitations

1. **Raw Chain-of-Thought (`trace["reasoning"]`) Preserved:** Per owner decision recorded in [PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md) and [PHASE_5_E_ACCEPTANCE_CRITERIA.md](PHASE_5_E_ACCEPTANCE_CRITERIA.md), raw `trace["reasoning"]` rendering in the UI is intentionally preserved. `P5-E-AI1` sanitizes user-visible assistant final output and structured persistence/read channels (`messages`, `trace` non-reasoning fields, `human_support`, `feedbacks`, `escalations`, `replay`, `conversation_transcript`) while preserving `trace["reasoning"]`.
2. **Provenance-Scoped Demo Sample Orders (`P5-E-DATA1`):** `seed_demo_sample_orders(customer_id)` generates sample IDs strictly in `O-700001..O-899992` (`700000 + (abs(hash(customer_id)) % 199990)`), records `demo_sample_fixture_seeded` in `imported_events` and `business_events`, and idempotently backfills provenance if a returning demo customer already has the exact 3 consecutive `P-601`/`P-602`/`P-603` sample orders. Non-demo `O-\d{6}` orders (`O-123456`, `O-754321`) never receive `display_name`.
3. **No Live / Paid / EC2 Execution:** All verification in this packet is offline/deterministic (local SQLite + Node UI + GitHub Actions CI with disposable PostgreSQL 16 + pgvector). No live OAuth, EC2/SSM commands, production DB edits, or paid LLM calls were executed.

---

## 4. Verification Commands & Local / CI Execution Summary

### Local Verification Commands Executed (All Exit Code `0`)
```bash
py -3.12 scripts/build_agent_notebook.py --check
py -3.12 scripts/check_docs_contract.py
py -3.12 scripts/check_deployment_contract.py
node --check web/app.js
node --check opsconsole/static/app.js
node tests/test_chat_focus.js
node tests/test_model_status.js
node tests/test_knowledge_sources.js
node tests/test_shipment_ui.js
node tests/test_provider_selector.js
node tests/test_public_session.js
RETAILOPS_UI_TEST_MODE=persistent node tests/test_public_session.js
node opsconsole/tests/test_ui.js
py -3.12 scripts/check_account_usage_quota.py
py -3.12 scripts/check_ops_console.py
py -3.12 -m unittest tests/test_phase5_e_ai_trust_and_governance.py tests/test_audit_remediation.py tests/test_persistent_identity.py tests/test_phase5_google_identity.py -v
```

### Local Execution Results
- **`tests/test_phase5_e_ai_trust_and_governance.py`:** `Ran 14 tests in 8.288s — OK` (`skipped=0`).
- **Combined targeted Python regressions (`test_phase5_e_ai_trust_and_governance.py`, `test_audit_remediation.py`, `test_persistent_identity.py`, `test_phase5_google_identity.py`):** `Ran 55 tests — OK` (`skipped=0`).
- **`py -3.12 scripts/check_ops_console.py` (local portable without `RETAILOPS_TEST_DATABASE_URL`):** `Ran 19 tests — OK (skipped=2)` (`test_membership_quota_route_trace_and_replay` and `test_export_is_read_only_and_excludes_content` require `RETAILOPS_TEST_DATABASE_URL` and run with `skipped=0` in CI `postgres` / `offline` jobs).
- **`py -3.12 scripts/check_account_usage_quota.py`:** `ACCOUNT_USAGE_QUOTA_OK` (exit `0`).
- **Contracts & UI Suites:** `AGENT_NOTEBOOK_SOURCE_SYNC_OK`, `check_docs_contract.py` (`SUCCESS`), `DEPLOYMENT_CONTRACT_OK`, `node --check web/app.js`, `node --check opsconsole/static/app.js`, and all 7 Node UI test runs exited with `0`.

---

## 5. Files Changed in PR #43 (Relative to Baseline `44540eab516831d5c8232dd80392b8e20c6cd47e`)

- `data/products.json`
- `docs/00_OVERVIEW/CODEBASE_MAP.md`
- `docs/03_EVALUATION/ACCEPTANCE_MATRIX.md`
- `docs/CURRENT_PROJECT_STATUS.md`
- `docs/PLAN_ROADMAP_INDEX.md`
- `docs/phase5/ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md`
- `docs/phase5/PHASE_5_E_ACCEPTANCE_CRITERIA.md`
- `docs/phase5/PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md`
- `docs/phase5/PHASE_5_E_EVIDENCE_2026-10-17.md`
- `docs/phase5/PHASE_5_E_EXECUTION_HANDOFF.md`
- `docs/phase5/PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md`
- `docs/phase5/README.md`
- `docs/phase5/REVIEW_ARGON_P5_E_2026-10-18.md`
- `notebooks/colab_agent.ipynb`
- `retailops/account_usage.py`
- `retailops/business/application.py`
- `retailops/business/permissions.py`
- `retailops/business/store.py`
- `retailops/guardrails/topic_filter.py`
- `retailops/http/public.py`
- `retailops/http/routes.py`
- `retailops/identity/contracts.py`
- `retailops/identity/persistent.py`
- `retailops/identity/store.py`
- `retailops/storage/pg_repositories.py`
- `retailops/storage/pg_schema.py`
- `retailops/workflow/agent.py`
- `retailops/workflow/graph.py`
- `retailops/workflow/subagents/dispute_agent.py`
- `retailops/workflow/subagents/read_worker.py`
- `retailops/workflow/supervisor.py`
- `retailops_conversation.py`
- `retailops_tools.py`
- `tests/test_phase5_e_ai_trust_and_governance.py`
- `tests/test_postgres.py`
- `tests/test_public_session.js`
- `web/app.js`
- `web/index.html`
