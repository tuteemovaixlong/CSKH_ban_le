# P5-E Candidate Evidence Snapshot — 2026-10-18 (Updated 2026-10-19 Round 3 Remediation)

## Scope and verdict

Evidence packet for PR #43 (`feat/phase5-e-ai-trust-account-governance`). It preserves the independent review snapshot on candidate `982801144702b703eb9af3d4d1435a3a75b1b1e4` and records the Round 3 bounded remediation on code candidate `97b11bbcaa67a7b2f4297e63437d5802ee789384` (tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`), closing the three remaining open findings (`AI1` canary/secret filtering in preserved reasoning, `DATA1` strict 3-order fixture & zero-import/item provenance backfill guard, and `AI5` PostgreSQL/pgvector provider & daily quota HTTP `429` error-contract/state-invariance parity).

Overall independent review verdict remains **CHANGES REQUIRED** pending Codex re-review of the Round 3 candidate; implementer status across all 14 P5-E acceptance criteria is **REMEDIATED / READY FOR CODEX RE-REVIEW**. This document records review and CI evidence only; it is not acceptance, merge, or deployment approval. P5-E remains exactly 14 acceptance criteria.

## Candidate mapping

| Item | Round 2 Reviewed Snapshot (`9828011`) | Round 3 Remediated Code Candidate (`97b11bb`) |
|---|---|---|
| PR | [#43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43), OPEN | [#43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43), OPEN |
| Candidate head | `982801144702b703eb9af3d4d1435a3a75b1b1e4` | `97b11bbcaa67a7b2f4297e63437d5802ee789384` (code/test candidate; followed by docs-only sync commit on PR #43) |
| Base | `44540eab516831d5c8232dd80392b8e20c6cd47e` | `44540eab516831d5c8232dd80392b8e20c6cd47e` |
| Tested merge ref | `50fa050b4c9fa7afea59c6201e4f29aca8d4274d` | `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1` |
| CI (`ci.yml`) | [39140778461](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39140778461), `SUCCESS` | [39203490030](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490030), `SUCCESS` (`offline` `117901231330`, `colab-python313` `117901231538`) |
| Ops Console (`ops-console.yml`) | [39140778477](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39140778477), `SUCCESS` | [39203490035](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490035), `SUCCESS` (`postgres` `117901231247`, `portable (ubuntu-24.04)` `117901231530`, `portable (windows-latest)` `117901231463`) |

## Round 3 bounded remediation summary (AI1, DATA1, AI5)

| Finding | Root Cause on `9828011` | Round 3 Fix on `97b11bb` | Verification Evidence (SQLite + PostgreSQL/pgvector) |
|---|---|---|---|
| **AI1 (`P5-E-AI1`)** — Canary/secret inside preserved `trace.reasoning` / `thought` fields | `sanitize_structured_payload` skipped keys in `preserve_keys` (`"reasoning"`, `"thought"`, `"_reasoning"`, `"thinking"`), allowing canary/secret probes placed inside `trace.reasoning` or `message.thinking` to survive in live responses, persisted `agent_turns`/`trace`, replay, and legacy read-time channels. | Added `sanitize_reasoning_text` in `retailops/guardrails/topic_filter.py` and wired it into `sanitize_structured_payload` for `effective_preserve_keys` (`"reasoning"`, `"thought"`, `"_reasoning"`, `"thinking"`). Ordinary visible Chain-of-Thought (`trace.reasoning`) is preserved unchanged (`return text` when no canary/secret is detected); sentences containing canary/secret probes (plain, reversed, Base64, hex, spaced, or system-prompt/env-secret markers) are scrubbed while keeping non-leaking CoT sentences intact. Also sanitized `exc_trace` on `AgentError` in `retailops/business/application.py` and `events()`/`manager_events()` payloads on read in `retailops/business/store.py`. | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_ai1_prompt_injection_persona_encoding_exfiltration_resistance` (hostile CoT canary in `single_agent` & `multi_agent`, replay, transcript, history + positive control preserving ordinary visible CoT) & `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries`. |
| **DATA1 (`P5-E-DATA1`)** — Mixed-provenance backfill guard for returning demo fixtures | `seed_demo_sample_orders` checked `imported_events` only on the middle `P-602` order and did not verify all 3 order attributes (`name`, `variant`, `amount`, `status`, `cancel_reason`, `product_id`) or check `order_items` / `sales_event_imported` across the customer and 3-order triplet. | Added `_DEMO_SAMPLE_FIXTURE_SPEC`, `_row_matches_demo_fixture_spec`, and `_has_import_or_item_provenance` in `retailops/business/store.py` (inherited by `PostgresBusinessStore`). Backfill and `is_demo_sample_order` now require: (1) exact 3-order triplet (`O-(seed_base+1..3)`) matching `_DEMO_SAMPLE_FIXTURE_SPEC` across `P-601`, `P-602`, `P-603`, AND (2) zero non-fixture `imported_events`, `order_items`, or `sales_event_imported` records on the customer or any of the 3 orders. Legacy 3-order triplets with mixed import provenance or modified attributes keep canonical `Quần tây ống đứng tôn dáng` (no `display_name`). | `tests/test_phase5_e_ai_trust_and_governance.py::Phase5EAITrustAndGovernanceTests.test_p5e_data1_demo_sample_order_label_and_ssot_consistency` (`legacy_mixed_cust` with `pos_sync` import on `P-601` + `legacy_mod_cust` with modified `P-601` amount) & `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (`pg_legacy_mixed` + `pg_legacy_mod`). |
| **AI5 (`P5-E-AI5`)** — PostgreSQL/pgvector provider & daily quota HTTP `429` parity | `test_phase5_e_postgres_governance_and_ai_boundaries` in `tests/test_postgres.py` covered `504` and `503` on `store_a` (`PostgresBusinessStore`), and quota `429` later on `PostgresSessions`, but lacked explicit provider `429` (`api_rate_limited`) and daily quota `429` (`api_daily_limit`) error-contract and business-state invariance assertions alongside `504`/`503` on `store_a`. | Added `_PgRateLimitGw` (`429 api_rate_limited`) and `_PgHealthyApiGw` (`200` on 2nd attempt, `429 api_daily_limit` on 3rd attempt with `api_daily_limit=2`) via `_pg_api` / `api_result` in `test_phase5_e_postgres_governance_and_ai_boundaries`, verifying status `429`, error codes (`api_rate_limited`, `api_daily_limit`), Vietnamese user-facing messages, and unchanged `orders`/`proposals` snapshots on PostgreSQL. | `tests/test_postgres.py::PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries` (executed in CI `offline` job `117901231330` against PostgreSQL 16 + `pgvector 0.8.6`). |

## CI and regression evidence (Round 3 candidate `97b11bbcaa67a7b2f4297e63437d5802ee789384`)

- **CI (`ci.yml`) run [39203490030](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490030) on tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`:**
  - `offline` job `117901231330`: `SUCCESS`. Raw log confirms `TEST_PGVECTOR_READY=0.8.6`, `test_phase5_e_postgres_governance_and_ai_boundaries (test_postgres.PostgresTests.test_phase5_e_postgres_governance_and_ai_boundaries) ... ok`, step 8 (`Unit, pgvector and HTTP contract tests`) `Ran 701 tests in 107.624s` -> `OK` (`0 skipped` — Python `unittest` omits `(skipped=N)` when zero tests are skipped), and step 13 packaged container rerun `Ran 701 tests in 115.721s` -> `OK` (`0 skipped`).
  - `colab-python313` job `117901231538`: `SUCCESS` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`, `COLAB_PY313_DEPENDENCIES_OK`).
- **Ops Console (`ops-console.yml`) run [39203490035](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490035) on tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`:**
  - `postgres` job `117901231247`: `SUCCESS` (`TEST_PGVECTOR_READY=0.8.6`, `Ran 19 tests in 1.056s` -> `OK`, `0 skipped`, `OPS_CONSOLE_TESTS_OK`, `ACCOUNT_USAGE_QUOTA_OK`).
  - `portable (ubuntu-24.04)` job `117901231530`: `SUCCESS` (`Ran 19 tests in 0.009s` -> `OK (skipped=2)` for the 2 PostgreSQL-specific tests in portable SQLite mode, `OPS_CONSOLE_TESTS_OK`, `ACCOUNT_USAGE_QUOTA_OK`, `OPS_CONSOLE_UI_CONTRACT_OK`).
  - `portable (windows-latest)` job `117901231463`: `SUCCESS` (`Ran 19 tests in 0.102s` -> `OK (skipped=2)` for the 2 PostgreSQL-specific tests in portable SQLite mode, `OPS_CONSOLE_TESTS_OK`, `ACCOUNT_USAGE_QUOTA_OK`, `OPS_CONSOLE_UI_CONTRACT_OK`).
- **Local targeted verification in clean worktree `C:/Users/HP/AppData/Local/Temp/retailops_p5e_wt`:**
  - `py -3.12 -m unittest -v tests/test_phase5_e_ai_trust_and_governance.py`: `Ran 14 tests in 10.285s` -> `OK` (`0 skipped`).
  - `node tests/test_public_session.js` (default + `RETAILOPS_TEST_PERSISTENT=1`): `PUBLIC_COOKIE_UI_FLOW_OK` & `PERSISTENT_ACCOUNT_UI_FLOW_OK` (`PASS`).
  - `py -3.12 scripts/build_agent_notebook.py --check` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`), `py -3.12 scripts/check_docs_contract.py` (`SUCCESS`), `py -3.12 scripts/check_deployment_contract.py` (`DEPLOYMENT_CONTRACT_OK`), `git diff --check` (`PASS`).

## 14-criterion disposition summary

| Criterion | Prior Review Verdict (`9828011`) | Round 3 Implementer Status (`97b11bb`) | Evidence Reference |
|---|---|---|---|
| **P5-E-AI1** | `CHANGES REQUIRED` (canary in preserved `trace.reasoning`) | **REMEDIATED / READY FOR CODEX RE-REVIEW** | `sanitize_reasoning_text` in `retailops/guardrails/topic_filter.py`; `test_p5e_ai1_prompt_injection_persona_encoding_exfiltration_resistance` & `test_phase5_e_postgres_governance_and_ai_boundaries` |
| **P5-E-AI2** | `SUPPORTED` | **SUPPORTED (UNCHANGED)** | `test_p5e_ai2_no_unauthorized_mutation_under_conflicting_read_only_instructions_and_positive_control` & `test_phase5_e_postgres_governance_and_ai_boundaries` |
| **P5-E-AI3** | `SUPPORTED` | **SUPPORTED (UNCHANGED)** | `test_p5e_ai3_entity_and_owner_boundary_and_unicode_confusables` & `test_phase5_e_postgres_governance_and_ai_boundaries` |
| **P5-E-AI4** | `SUPPORTED` | **SUPPORTED (UNCHANGED)** | `test_p5e_ai4_factuality_grounding_and_list_orders_truncation_contract` & `test_phase5_e_postgres_governance_and_ai_boundaries` |
| **P5-E-AI5** | `PARTIAL` (missing PG provider/quota `429` parity) | **REMEDIATED / READY FOR CODEX RE-REVIEW** | `test_p5e_ai5_timeout_429_quota_503_truthfulness_and_no_false_completion` & `test_phase5_e_postgres_governance_and_ai_boundaries` (`_PgRateLimitGw` + `_PgHealthyApiGw` `429` assertions) |
| **P5-E-AI6** | `PASS (bounded)` | **PASS (bounded, UNCHANGED)** | `test_p5e_ai6_bounded_reproducible_adversarial_manifest` (`EXPECTED_MANIFEST_SHA256 = "b21dca25eb286080487c5df24949df13e7576db5e340dfdbfda15b5b83e7a2af"`) |
| **P5-E-ADM1..ADM6** | `SUPPORTED` | **SUPPORTED (UNCHANGED)** | `test_p5e_adm1..adm6*`, `test_p5e_r2_sqlite_legacy_schema_role_migration_and_rollback`, `tests/test_public_session.js`, `test_phase5_e_postgres_governance_and_ai_boundaries` |
| **P5-E-DATA1** | `CHANGES REQUIRED` (mixed-provenance backfill guard) | **REMEDIATED / READY FOR CODEX RE-REVIEW** | `_DEMO_SAMPLE_FIXTURE_SPEC` + `_has_import_or_item_provenance` in `retailops/business/store.py`; `test_p5e_data1_demo_sample_order_label_and_ssot_consistency` & `test_phase5_e_postgres_governance_and_ai_boundaries` |
| **P5-E-DATA2** | `SUPPORTED` | **SUPPORTED (UNCHANGED)** | `test_p5e_data2_incomplete_catalog_p604_and_variant_seed_fallback_safety` & `test_p604_catalog_seed_preserves_unknowns_and_is_idempotent_postgres` |

## Limitations

This snapshot does not establish live provider quality, current EC2 state, production database contents, merge/deploy readiness, G4 AI-lane acceptance, G5/G6/G7 readiness, or performance. No live OAuth, AWS/SSM/EC2 commands, production DB/config changes, or paid model calls were executed.

Read with: [review](REVIEW_ARGON_P5_E_2026-10-18.md) · [handoff and Argon trigger](PHASE_5_E_EXECUTION_HANDOFF.md) · [acceptance criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md) · [P5-E plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md) · [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) · [current status](../CURRENT_PROJECT_STATUS.md)
