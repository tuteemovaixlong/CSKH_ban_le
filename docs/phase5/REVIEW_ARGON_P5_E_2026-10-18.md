# Independent Codex Review — P5-E candidate 9828011 (2026-10-18, Updated 2026-10-19 Round 3 Remediation Note)

**Verdict: CHANGES REQUIRED (pending Codex re-review of Round 3 candidate `97b11bbcaa67a7b2f4297e63437d5802ee789384`).** Candidate đã qua CI, nhưng chưa đủ điều kiện merge, nghiệm thu P5-E hoặc chuyển sang performance cho tới khi Codex hoàn tất re-review độc lập. Phạm vi giữ nguyên 14 acceptance criteria hiện có; không mở bug hunt khác.

## Review lineage

This current review supersedes the earlier assessment of candidate `baa70b1`. Candidate `982801144702b703eb9af3d4d1435a3a75b1b1e4` closed the earlier bounded `AI2`, `AI4`, `ADM2–ADM4` and generated-ID findings; only `AI1` (canary in preserved `trace.reasoning`), `AI5` (PostgreSQL `429` parity) and `DATA1` (mixed provenance backfill guard) remained open on `9828011`. Round 3 code candidate `97b11bbcaa67a7b2f4297e63437d5802ee789384` (tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`) remediates those three bounded findings and is **READY FOR CODEX RE-REVIEW**.

## Candidate và bằng chứng đã đối chiếu

- PR #43: [candidate](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43), base `44540eab516831d5c8232dd80392b8e20c6cd47e`.
- **Round 2 reviewed candidate:** head `982801144702b703eb9af3d4d1435a3a75b1b1e4`, tested merge ref `50fa050b4c9fa7afea59c6201e4f29aca8d4274d`, [CI run 39140778461](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39140778461) (`offline` `117714580485`, `colab-python313` `117714580703` `SUCCESS`), [Ops Console run 39140778477](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39140778477) (`postgres` `117714580123`, portable `117714580288`/`117714580245` `SUCCESS`).
- **Round 3 remediated code candidate (implementer self-report, ready for Codex re-review):** head `97b11bbcaa67a7b2f4297e63437d5802ee789384`, tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`:
  - [CI run 39203490030](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490030): `offline` job `117901231330` (`SUCCESS`, `TEST_PGVECTOR_READY=0.8.6`, step 8 `Ran 701 tests in 107.624s — OK` [`0 skipped`] and step 13 packaged rerun `Ran 701 tests in 115.721s — OK` [`0 skipped`], including `test_phase5_e_postgres_governance_and_ai_boundaries ... ok`) and `colab-python313` job `117901231538` (`SUCCESS`).
  - [Ops Console run 39203490035](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490035): `postgres` job `117901231247` (`SUCCESS`, `Ran 19 tests in 1.056s — OK` [`0 skipped`]) and portable Ubuntu/Windows jobs `117901231530` / `117901231463` (`SUCCESS`, `Ran 19 tests — OK (skipped=2)`).
  - Local targeted P5-E suite on clean worktree: `14/14 PASS` (`0 skipped`); `node tests/test_public_session.js` (default + persistent) `PASS`.
- The actual PostgreSQL test method is `test_phase5_e_postgres_governance_and_ai_boundaries` in `tests/test_postgres.py`.

## Review findings (`9828011`) and Round 3 remediation status (`97b11bb`)

| Area | Review Verdict on `9828011` | Round 3 Implementer Status (`97b11bb`) | Evidence and remaining work |
|---|---|---|---|
| AI1 — prompt/secret boundary | CHANGES REQUIRED | **REMEDIATED / READY FOR CODEX RE-REVIEW** | Added `sanitize_reasoning_text` in `retailops/guardrails/topic_filter.py` for preserved `reasoning`/`thought`/`_reasoning`/`thinking` fields, scrubbing canary/secret probes while preserving ordinary visible CoT unchanged. Added SQLite (`single_agent` + `multi_agent`) and PostgreSQL regressions. |
| AI2 — read-only intent | SUPPORTED | **SUPPORTED** | Reviewed path prevents read-only turns from performing cancellation or opening human-support side effects; targeted regression coverage exists. |
| AI3 — identity and tenant authorization | SUPPORTED | **SUPPORTED** | Owned/foreign/malformed identifier boundaries are covered by service tests and PostgreSQL CI; no cross-owner exposure was found in this bounded review. |
| AI4 — answer grounding | SUPPORTED | **SUPPORTED** | Missing/unknown product/order facts and unsupported success claims have targeted regressions; no remaining bounded finding was found. |
| AI5 — timeout/provider/quota failure | PARTIAL | **REMEDIATED / READY FOR CODEX RE-REVIEW** | Added explicit PostgreSQL provider `429` (`api_rate_limited`) and daily quota `429` (`api_daily_limit`) error-contract and business-state (`orders`/`proposals`) invariance assertions in `test_phase5_e_postgres_governance_and_ai_boundaries` (`tests/test_postgres.py`). |
| AI6 — bounded deterministic evaluation | PASS (bounded) | **PASS (bounded)** | The offline suite and pinned adversarial fixtures run without a paid/live model call. This does not establish live-model quality. |
| ADM1–ADM6 — account and quota operations | SUPPORTED | **SUPPORTED** | The bounded review found the R4 account search, tenant scope, stale selection, reset/clear override, audit and CSRF findings addressed. Regression checks passed; CI supplies PostgreSQL parity evidence. |
| DATA1 — demo display label provenance | CHANGES REQUIRED | **REMEDIATED / READY FOR CODEX RE-REVIEW** | Tightened `seed_demo_sample_orders` and `is_demo_sample_order` in `retailops/business/store.py` with `_DEMO_SAMPLE_FIXTURE_SPEC` and `_has_import_or_item_provenance` across all 3 orders (`P-601`, `P-602`, `P-603`) and customer. Added mixed-provenance and modified-attribute regressions in SQLite and PostgreSQL. |
| DATA2 — unknown/null inventory truth | SUPPORTED | **SUPPORTED** | Candidate regressions preserve unknown/null/zero facts and prevent unsupported stock/product claims. |

## Bounded next step

Round 3 remediation for `AI1`, `DATA1`, and `AI5` is complete on PR #43 (`97b11bbcaa67a7b2f4297e63437d5802ee789384`, tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`, CI `39203490030`, Ops Console `39203490035`, followed by the docs synchronization commit on PR #43) and is ready for independent Codex re-review. Keep the 14 criteria unchanged.

Owner decisions remain in force: raw ordinary CoT may remain visible; do not convert that decision into a gate. No merge, deployment, AWS/SSM/EC2, OAuth live, production DB/config changes, benchmark, or paid test is authorized by this review.

## Linked packet

[Execution handoff and Argon trigger](PHASE_5_E_EXECUTION_HANDOFF.md) · [evidence snapshot](PHASE_5_E_EVIDENCE_2026-10-18.md) · [acceptance criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md) · [P5-E plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md) · [manual-test input](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md) · [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) · [current project status](../CURRENT_PROJECT_STATUS.md) · [roadmap](../PLAN_ROADMAP_INDEX.md) · [codebase map](../00_OVERVIEW/CODEBASE_MAP.md)
