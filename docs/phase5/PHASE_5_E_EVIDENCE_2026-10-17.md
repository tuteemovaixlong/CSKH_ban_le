# Phase 5-E Evidence Packet — AI Trust & Safety, Account/Quota Governance, and Catalog Hygiene

> **Date:** 2026-10-18 (R1–R6 Consolidated Remediation on PR #43)
> **Baseline (PR #42 merged):** `44540eab516831d5c8232dd80392b8e20c6cd47e`
> **Prior Reviewed Candidate (Round 1):** `7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb` ([Independent Review](REVIEW_ARGON_P5_E_2026-10-18.md) — `CHANGES REQUIRED` R1–R6)
> **Workstream Branch & PR:** `feat/phase5-e-ai-trust-account-governance` ([PR #43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43))
> **Authoritative Specs:** [PHASE_5_E_ACCEPTANCE_CRITERIA.md](PHASE_5_E_ACCEPTANCE_CRITERIA.md) | [PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md) | [PHASE_5_E_EXECUTION_HANDOFF.md](PHASE_5_E_EXECUTION_HANDOFF.md) | [ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md](ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md) | [REVIEW_ARGON_P5_E_2026-10-18.md](REVIEW_ARGON_P5_E_2026-10-18.md)
> **Scope & Gate Notice:** This packet records offline deterministic code, SQLite, UI, and CI PostgreSQL 16 + pgvector evidence for the 14 Phase 5-E criteria (`P5-E-AI1..AI6`, `P5-E-ADM1..ADM6`, `P5-E-DATA1..DATA2`) and the consolidated R1–R6 remediation. Passing P5-E does **not** automatically close `G4` or authorize `G5`/`G6`/`G7` live/paid performance benchmarking.

---

## 1. Consolidated R1–R6 Remediation Summary

| Item | Finding on `7b94f9c` | Remediation Implemented | Verification Evidence |
|---|---|---|---|
| **R1 (`P5-E-AI1`)** | `Application.chat()` sanitized `answer["message"]` but persisted unsanitized `answer["messages"]` into `agent_turns.messages`, leaking canary tokens via `/api/conversations/{id}/messages` and `store.history()`. | Synchronized sanitized assistant final message into `answer["messages"]` and final-output trace fields (`final_reply`, `assistant_message`, `final_message`, `steps[action=='final_answer'].summary`) **before** `self.store.finish_turn(...)`. Preserved raw CoT (`trace["reasoning"]`) unchanged. Added hex canary decode check in `sanitize_output_against_canary_leak`. | `test_p5e_ai1_prompt_injection_persona_encoding_exfiltration_resistance` (SQLite, both `multi_agent` and `single_agent`) + `test_phase5_e_postgres_governance_and_ai_boundaries` (PostgreSQL). |
| **R2 (`P5-E-ADM1` / `ADM4`)** | SQLite legacy 4-role `memberships` migration ran `PRAGMA foreign_keys=OFF` inside an active transaction (no-op in SQLite) and swallowed errors with `except Exception: pass`. | Implemented `upgrade_sqlite_memberships_role_constraint(path, *, fail_hook=None)` in `retailops/identity/store.py` using `isolation_level=None`, `PRAGMA foreign_keys=OFF` verified before `BEGIN IMMEDIATE`, `PRAGMA foreign_key_check` before `COMMIT`, and clean rollback with zero swallowed errors. Removed `try/except pass` around `memberships_role_check` in `PostgresIdentityStore.__init__`. | `test_p5e_r2_sqlite_legacy_schema_role_migration_and_rollback` (disposable baseline `44540ea` SQLite DB with memberships, credentials, sessions, forced failure rollback + successful upgrade to `platform_admin`). |
| **R3 (`P5-E-DATA1`)** | `_format_order_for_api` attached `display_name: "Bộ xếp hình gỗ cho bé"` to any `P-602` delivered `O-\d{6}` order (`Đen / L`, `520000`), including manual/imported non-demo orders. | Added `BusinessStore.seed_demo_sample_orders(customer_id)` (recording `demo_sample_fixture_seeded` in `business_events`, filtered from customer/manager event lists) and `BusinessStore.is_demo_sample_order(customer_id, order_id)`. `_format_order_for_api` only attaches `display_name` when `store.is_demo_sample_order(...)` is true. | `test_p5e_data1_demo_sample_order_label_and_ssot_consistency` (SQLite positive + negative `O-123456`/`O-754321` on `non_demo_customer`), `test_phase5_e_postgres_governance_and_ai_boundaries` (PostgreSQL positive + negative), and `tests/test_public_session.js` (UI positive + negative). |
| **R4 (`P5-E-ADM1..ADM6`)** | Account & quota governance had backend routes (`/api/admin/accounts*`, `/api/admin/audit-log`) but no operator UI in `web/index.html` + `web/app.js`. | Added `#tab-btn-accounts` and `#tab-content-accounts` in `web/index.html` + controller logic in `web/app.js` (scoped list/search, detail + quota/reset inspection, suspend/reactivate/revoke-sessions, bounded quota override `1..10000` with mandatory reason and confirmation, audit log table, and explicit `tenant_id` selector for `platform_admin`; hidden/blocked for `customer`/`viewer`/`staff`). Ops Console v1 (`opsconsole/`) remains read-only. | `tests/test_public_session.js` (default + `RETAILOPS_UI_TEST_MODE=persistent`) + `test_p5e_adm1..adm6` (SQLite & PostgreSQL). |
| **R5 (Required Tests)** | Missing pinned literal `EXPECTED_MANIFEST_SHA256` + tamper-negative test (`AI6`); missing PG-backed assertions for `AI1`/`AI2`/`AI5`/`ADM4` concurrency/`ADM6`/`DATA1` negative; missing E2E final-response assertions for `AI4`. | Pinned `EXPECTED_MANIFEST_SHA256 = "b21dca25eb286080487c5df24949df13e7576db5e340dfdbfda15b5b83e7a2af"` + tamper-negative assertion in `test_p5e_ai6`; added E2E final-response assertions in `test_p5e_ai4`; added `AccountQuotaStore` concurrency/UTC-reset/effective/expiry tests on SQLite (`test_p5e_adm4`) and PostgreSQL (`test_postgres.py`); expanded `test_phase5_e_postgres_governance_and_ai_boundaries` with PG-backed `AI1`, `AI2`, `AI4`, `AI5`, `ADM4`, `ADM6`, and `DATA1` negative assertions. | `tests/test_phase5_e_ai_trust_and_governance.py` (14 tests, 0 skips) + `tests/test_postgres.py` (PostgreSQL 16 + pgvector in CI, 0 skips). |
| **R6 (Evidence & Docs)** | Evidence listed nonexistent `node --check web/ops_console.js`, lacked exact per-criterion backend/test mapping, and needed selective sync of updated P5-E docs from primary workspace. | Selectively synced updated P5-E/status/navigation docs from primary workspace, preserved `REVIEW_ARGON_P5_E_2026-10-18.md` as historical review of `7b94f9c`, removed `node --check web/ops_console.js`, and updated ADR + Evidence packet with exact commands, counts, skips, and backend coverage. | `python scripts/check_docs_contract.py` (`PASS`). |

---

## 2. Criteria-to-Evidence Matrix (14 / 14 Criteria)

| Criterion | Implementation Files | SQLite / UI / Offline Deterministic Tests | PostgreSQL 16 + pgvector Integration Tests (`tests/test_postgres.py`) | Implementing Verdict (for Re-Review) |
|---|---|---|---|---|
| **P5-E-AI1** — Prompt injection, persona override, encoding & secret/canary resistance across chat, trace, replay & transcript | `retailops/guardrails/topic_filter.py`, `retailops/business/application.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai1_prompt_injection_persona_encoding_exfiltration_resistance` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (PG chat response, trace, replay & `/api/conversations/{id}/messages` transcript sanitization + CoT preservation) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI2** — Read-only vs mutation intent boundary & confirmation gate | `retailops/guardrails/topic_filter.py`, `retailops/workflow/supervisor.py`, `retailops/workflow/subagents/dispute_agent.py`, `retailops/business/application.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai2_no_unauthorized_mutation_under_conflicting_read_only_instructions_and_positive_control` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (PG hostile `prepare_cancellation` blocked on read-only lookup; order `O-101` unchanged) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI3** — Entity, owner, tenant & Unicode confusable / SQL-like ID boundary | `retailops/business/store.py`, `retailops_tools.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai3_entity_and_owner_boundary_and_unicode_confusables` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI4** — Factuality grounding, unknown handling (`P-604`), no false-success mutation, and `list_orders` truncation disclosure | `retailops_tools.py`, `retailops/business/store.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai4_factuality_grounding_and_list_orders_truncation_contract` (tool + E2E final assistant response assertions) | `tests/test_postgres.py::PostgresTests.test_p604_catalog_seed_preserves_unknowns_and_is_idempotent_postgres` & `test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI5** — Timeout (`504`), provider `429`, daily quota (`429`), and `503` truthfulness without false completion | `retailops/business/application.py`, `retailops/account_usage.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai5_timeout_429_quota_503_truthfulness_and_no_false_completion` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (PG `504 agent_timeout`, `429 api_daily_limit`, `503 agent_response_failed`, zero order mutation) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-AI6** — Bounded, deterministic, zero-paid-call adversarial manifest (`EXPECTED_MANIFEST_SHA256` literal pinned + tamper-negative test) | `tests/test_phase5_e_ai_trust_and_governance.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai6_bounded_reproducible_adversarial_manifest` (`EXPECTED_MANIFEST_SHA256 = "b21dca25eb286080487c5df24949df13e7576db5e340dfdbfda15b5b83e7a2af"`) | Pure deterministic offline manifest test (backend-independent; runs in CI `offline` job with `skipped=0`) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM1** — Admin RBAC, tenant authorization boundary & SQLite/PG role schema (`customer`/`viewer`/`staff` denied; `manager` own-tenant; `platform_admin` explicit tenant) | `retailops/business/permissions.py`, `retailops/identity/contracts.py`, `retailops/identity/persistent.py`, `retailops/identity/store.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm1_and_adm2_authz_boundary_and_scoped_account_view`, `test_p5e_r2_sqlite_legacy_schema_role_migration_and_rollback`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM2** — Scoped account list/detail view & UI without credential/token/cookie leakage | `retailops/identity/store.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `retailops/http/public.py`, `web/index.html`, `web/app.js` | `test_p5e_adm1_and_adm2_authz_boundary_and_scoped_account_view`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM3** — Account suspend, reactivate, session revocation, and self-lockout prevention (API + UI) | `retailops/identity/store.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm3_account_suspend_reactivate_and_session_revocation`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM4** — Per-membership quota inspection & bounded override (`1..10000`, concurrent reservation, UTC reset, `effective_at`/`expires_at`, restart persistence, UI) | `retailops/account_usage.py`, `retailops/identity/store.py`, `retailops/storage/pg_schema.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm4_quota_inspection_and_bounded_override_with_expiry_and_persistence`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (PG restart persistence, 6-thread concurrent reservation, UTC day reset, future `effective_at` & expired `expires_at`) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM5** — Append-only `admin_audit_log` & transactional rollback if audit fails | `retailops/identity/store.py`, `retailops/storage/pg_schema.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/index.html`, `web/app.js` | `test_p5e_adm5_append_only_admin_audit_log_and_transactional_rollback`, `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-ADM6** — Control-plane isolation, CSRF origin check on admin mutations, and Ops Console v1 read-only preservation | `retailops/http/public.py`, `retailops/http/routes.py`, `opsconsole/server.py` | `test_p5e_adm6_control_plane_isolation_and_csrf_protection`, `scripts/check_ops_console.py` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (PG `403 invalid_origin` CSRF rejection on admin POST) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-DATA1** — Server-side provenance-scoped demo sample order label (`display_name: "Bộ xếp hình gỗ cho bé"`) without mutating SSOT `P-602` or affecting non-demo `O-\d{6}` orders | `retailops/business/store.py`, `retailops/identity/persistent.py`, `retailops/storage/pg_repositories.py`, `retailops/http/routes.py`, `web/app.js` | `test_p5e_data1_demo_sample_order_label_and_ssot_consistency` (positive demo + negative `O-123456`/`O-754321` on `non_demo_customer`), `tests/test_public_session.js` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (PG positive demo + negative `O-123456`/`O-754321` across `/api/orders`, `/api/orders/{id}`, `/api/conversations/{id}/focus`) | **REMEDIATED / READY FOR RE-REVIEW** |
| **P5-E-DATA2** — Incomplete catalog (`P-604`) natural-language alias lookup & null/zero variant stock seed fallback safety | `data/products.json`, `retailops/business/store.py`, `retailops_conversation.py` | `test_p5e_data2_incomplete_catalog_p604_and_variant_seed_fallback_safety` | `tests/test_postgres.py::PostgresTests.test_p604_catalog_seed_preserves_unknowns_and_is_idempotent_postgres` & `test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / READY FOR RE-REVIEW** |

---

## 3. Explicit Policy Decisions & Scope Limitations

1. **Raw Chain-of-Thought (`trace["reasoning"]`) Preserved:** Per owner decision recorded in [PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md) and [PHASE_5_E_ACCEPTANCE_CRITERIA.md](PHASE_5_E_ACCEPTANCE_CRITERIA.md), raw `trace["reasoning"]` rendering in the UI is intentionally preserved. `P5-E-AI1` sanitizes user-visible assistant final output across chat response, persisted `agent_turns.messages`, final-output trace fields (`final_reply`, `assistant_message`, `final_message`, `steps[action=='final_answer'].summary`), replay, and transcript endpoints without stripping `trace["reasoning"]`.
2. **Legacy Pre-Existing Demo Orders Without Provenance Event (`P5-E-DATA1`):** `BusinessStore.seed_demo_sample_orders(customer_id)` records a server-side `demo_sample_fixture_seeded` provenance event in `business_events` whenever synthetic Google demo sample orders are seeded. Any pre-existing database row created prior to this provenance marker (or created manually/imported without `seed_demo_sample_orders`) intentionally retains canonical `name: "Quần tây ống đứng tôn dáng"` without `display_name` so non-demo orders are never mislabeled. No live/EC2 database records were modified.
3. **No Live / Paid / EC2 Execution:** All verification in this packet is offline/deterministic (local SQLite + Node UI + GitHub Actions CI with disposable PostgreSQL 16 + pgvector). No live OAuth, EC2/SSM commands, production DB edits, or paid LLM calls were executed.

---

## 4. Verification Commands & Local / CI Execution Summary

### Local Verification Commands Executed (All Exit Code `0`)
```bash
python scripts/build_agent_notebook.py --check
python scripts/check_docs_contract.py
python scripts/check_deployment_contract.py
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
python scripts/check_account_usage_quota.py
python scripts/check_ops_console.py
python -m unittest tests/test_phase5_e_ai_trust_and_governance.py tests/test_audit_remediation.py tests/test_persistent_identity.py tests/test_phase5_google_identity.py -v
```

### Local Execution Results
- **`tests/test_phase5_e_ai_trust_and_governance.py`:** `Ran 14 tests in 7.399s — OK` (`skipped=0`).
- **Combined targeted Python regressions (`test_phase5_e_ai_trust_and_governance.py`, `test_audit_remediation.py`, `test_persistent_identity.py`, `test_phase5_google_identity.py`):** `Ran 55 tests — OK` (`skipped=0`).
- **`python scripts/check_ops_console.py` (local portable without `RETAILOPS_TEST_DATABASE_URL`):** `Ran 19 tests in 0.234s — OK (skipped=2)` (`test_membership_quota_route_trace_and_replay` and `test_export_is_read_only_and_excludes_content` require `RETAILOPS_TEST_DATABASE_URL` and run with `skipped=0` in CI `postgres` / `offline` jobs).
- **`python scripts/check_account_usage_quota.py`:** `ACCOUNT_USAGE_QUOTA_OK` (exit `0`).
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
- `retailops/workflow/subagents/dispute_agent.py`
- `retailops/workflow/supervisor.py`
- `retailops_conversation.py`
- `retailops_tools.py`
- `tests/test_phase5_e_ai_trust_and_governance.py`
- `tests/test_postgres.py`
- `tests/test_public_session.js`
- `web/app.js`
- `web/index.html`
