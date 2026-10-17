# Phase 5-E Evidence Packet — AI Trust & Safety, Account/Quota Governance, and Catalog Hygiene

> **Date:** 2026-10-17
> **Baseline (PR #42 merged):** `44540eab516831d5c8232dd80392b8e20c6cd47e`
> **Workstream Branch:** `feat/phase5-e-ai-trust-account-governance`
> **Authoritative Specs:** [PHASE_5_E_ACCEPTANCE_CRITERIA.md](PHASE_5_E_ACCEPTANCE_CRITERIA.md) | [PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md) | [PHASE_5_E_EXECUTION_HANDOFF.md](PHASE_5_E_EXECUTION_HANDOFF.md) | [ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md](ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md)
> **Scope & Gate Notice:** This packet records offline deterministic code, SQLite, and CI PostgreSQL 16 + pgvector evidence for the 14 Phase 5-E criteria (`P5-E-AI1..AI6`, `P5-E-ADM1..ADM6`, `P5-E-DATA1..DATA2`). Passing P5-E does **not** automatically close `G4` or authorize `G5`/`G6`/`G7` live/paid performance benchmarking.

---

## 1. Criteria-to-Evidence Matrix (14 / 14 Criteria)

| Criterion | Implementation Files | SQLite & Contract Tests | PostgreSQL 16 + pgvector Tests | Status |
|---|---|---|---|---|
| **P5-E-AI1** — Prompt injection, persona override, encoding & secret/canary resistance | `retailops/guardrails/topic_filter.py`, `retailops/business/application.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai1_prompt_injection_persona_encoding_exfiltration_resistance` | Covered in CI `offline` job alongside full suite (`skipped=0`) | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-AI2** — Read-only vs mutation intent boundary & confirmation gate | `retailops/guardrails/topic_filter.py`, `retailops/workflow/supervisor.py`, `retailops/workflow/subagents/dispute_agent.py`, `retailops/business/application.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai2_no_unauthorized_mutation_under_conflicting_read_only_instructions_and_positive_control` | Covered in CI `offline` job alongside `test_postgres.py` (`skipped=0`) | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-AI3** — Entity, owner, tenant & Unicode confusable / SQL-like ID boundary | `retailops/business/store.py`, `retailops_tools.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai3_entity_and_owner_boundary_and_unicode_confusables` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-AI4** — Factuality grounding, unknown handling (`P-604`), and `list_orders` truncation disclosure | `retailops_tools.py`, `retailops/business/store.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai4_factuality_grounding_and_list_orders_truncation_contract` | `tests/test_postgres.py::PostgresTests.test_p604_catalog_seed_preserves_unknowns_and_is_idempotent_postgres` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-AI5** — Timeout (`504`), provider `429`, daily quota (`429`), and `503` truthfulness without false completion | `retailops/business/application.py`, `retailops/account_usage.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai5_timeout_429_quota_503_truthfulness_and_no_false_completion` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-AI6** — Bounded, deterministic, zero-paid-call adversarial manifest (`SHA-256` pinned) | `tests/test_phase5_e_ai_trust_and_governance.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai6_bounded_reproducible_adversarial_manifest` | Executed in CI `offline` job (`skipped=0`) | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-ADM1** — Admin RBAC & tenant authorization boundary (`customer`/`viewer`/`staff` denied; `manager` own-tenant; `platform_admin` explicit tenant) | `retailops/business/permissions.py`, `retailops/identity/contracts.py`, `retailops/identity/persistent.py`, `retailops/identity/store.py`, `retailops/http/routes.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_adm1_and_adm2_authz_boundary_and_scoped_account_view` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-ADM2** — Scoped account list/detail view without credential/token/cookie leakage | `retailops/identity/store.py`, `retailops/http/routes.py`, `retailops/http/public.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_adm1_and_adm2_authz_boundary_and_scoped_account_view` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-ADM3** — Account suspend, reactivate, session revocation, and self-lockout prevention | `retailops/identity/store.py`, `retailops/http/routes.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_adm3_account_suspend_reactivate_and_session_revocation` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-ADM4** — Per-membership quota inspection & bounded override (`1..10000`, expiry fallback, restart persistence) | `retailops/account_usage.py`, `retailops/identity/store.py`, `retailops/storage/pg_schema.py`, `retailops/http/routes.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_adm4_quota_inspection_and_bounded_override_with_expiry_and_persistence` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-ADM5** — Append-only `admin_audit_log` & transactional rollback if audit fails | `retailops/identity/store.py`, `retailops/storage/pg_schema.py`, `retailops/http/routes.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_adm5_append_only_admin_audit_log_and_transactional_rollback` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-ADM6** — Control-plane isolation, CSRF origin check on admin mutations, and Ops Console v1 read-only preservation | `retailops/http/public.py`, `retailops/http/routes.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_adm6_control_plane_isolation_and_csrf_protection` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-DATA1** — Synthetic demo sample order display label (`display_name: "Bộ xếp hình gỗ cho bé"`) without mutating SSOT `P-602` fields | `retailops/http/routes.py`, `web/app.js` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_data1_demo_sample_order_label_and_ssot_consistency` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |
| **P5-E-DATA2** — Incomplete catalog (`P-604`) natural-language alias lookup & null/zero variant stock seed fallback safety | `data/products.json`, `retailops/business/store.py`, `retailops_conversation.py` | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_data2_incomplete_catalog_p604_and_variant_seed_fallback_safety` | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` | **REMEDIATED / RE-REVIEW (CI PASS)** |

---

## 2. Explicit Owner Decision Preserved (CoT Display)

Per owner instruction recorded in [PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md) and [PHASE_5_E_ACCEPTANCE_CRITERIA.md](PHASE_5_E_ACCEPTANCE_CRITERIA.md):
- Raw `trace["reasoning"]` (Chain-of-Thought) rendering in the UI is **intentionally preserved** for demo/research visibility.
- `P5-E-AI1` enforces canary/secret/system-prompt non-exfiltration on user-visible assistant replies (`reply`, `trace.final_reply`, `trace.assistant_message`) without hiding CoT reasoning panels.

---

## 3. Verification Commands & Local / CI Execution Summary

### Local Verification Commands
```bash
python scripts/build_agent_notebook.py --check
python scripts/check_docs_contract.py
python scripts/check_deployment_contract.py
node --check web/app.js
node --check web/ops_console.js
node tests/test_chat_focus.js
node tests/test_model_status.js
node tests/test_knowledge_sources.js
node tests/test_shipment_ui.js
node tests/test_provider_selector.js
node tests/test_public_session.js
python -m unittest tests/test_phase5_e_ai_trust_and_governance.py tests/test_audit_remediation.py -v
```

### Local & GitHub Actions CI Summary
- **Local P5-E SQLite suite (`tests/test_phase5_e_ai_trust_and_governance.py`):** 13 ran, 13 passed, 0 skipped.
- **Local Node UI & contract checks:** `AGENT_NOTEBOOK_SOURCE_SYNC_OK`, `DEPLOYMENT_CONTRACT_OK`, `check_docs_contract.py` PASS, all Node UI tests PASS.
- **GitHub Actions CI (`ci.yml`):** Executed on the exact candidate SHA with real PostgreSQL 16 + pgvector (`RETAILOPS_TEST_DATABASE_URL` configured, `skipped=0` across the entire discovered test suite).
