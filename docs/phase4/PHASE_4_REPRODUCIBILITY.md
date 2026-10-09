# PHASE_4_REPRODUCIBILITY — Reproduction protocol

> **Merge policy owner chốt 2026-10-08:** [Acceptance v1](PHASE_4_ACCEPTANCE_CRITERIA.md): đúng8check; N1 manifest mutation/N3 denominator/N4 safety types DONE trong scope v1. [Evidence HEAD 8a666fc](PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md): K1–K8/C1–C6 PASS, independent sign-off PENDING. Checklist kỹ thuật đạt theo packet; chờ nguồn độc lập xác minh và ký 8/8 → owner review → merge → G2. N1 replay/counts/tool-name semantics, L2/L4/L5 và việc ngoài checklist → [Phase5 backlog](PHASE_5_BACKLOG.md), không block merge. Findings/progress lịch sử bên dưới không mở thêm merge gate.

> **Trạng thái (2026-10-08):** READY FOR HARNESS/PREFLIGHT. HEAD `8a666fc` đạt K1–K8/C1–C6: CI5 success, mock250 PASS, patch whitespace clean; local full-suite rerun has timing variance. K7/C6 PASS trên patch merge; 5 EOF blank lines đã được loại bỏ; independent sign-off PENDING. N1 replay/counts/tool-name semantics vào Phase5, không block merge; chưa merge/G2/live.

## 1. Identity manifest

Every run records run_id, system_commit_sha, evaluation_harness_sha, evaluation_overlay_sha256, protocol/config/prompt/grader versions, both frozen benchmark hashes, fixture/identity/KB/qrels hashes, provider lane/adapter/endpoint/model identity, actual sampling, Python/OS/dependency/CUDA/vLLM versions, hardware, cache/retry/load modes, UTC timestamps and non-secret operator handle.

A provider field that is not exposed is null with unavailable_reason. A provider/endpoint/model mismatch blocks the lane. Do not fabricate proprietary revision or seed.

## 2. Clean-room preparation

1. Checkout system_commit_sha in a clean tree.
2. Verify both frozen benchmark files and their separate hashes.
3. Install declared dependencies and record versions.
4. Prepare synthetic isolated PostgreSQL/tenant/fixture where the scope requires RAG/business data.
5. Start the selected lane and capture health/identity output.
6. Assert answer-cache OFF for A0 and record ToolCache mode.
7. Run the stratified dev smoke only after G3 smoke approval; do not call this a measurement-ready gate before actual evidence.

## 3. Execution

For each immutable case_id:

1. Resolve sidecar identity/fixture/focus/prior turns.
2. Send the registered request envelope.
3. Append one attempts.jsonl record for every transport/runtime attempt.
4. Write grading/retrieval/error records linked by canonical keys.
5. Retry only retryable transport/runtime failures under retry_policy_id; retain first and eventual outcomes.
6. Do not rerun an incorrect answer into the primary sample. Diagnostic reruns use a separate run_id and label.

Quality and load/cache runs have different run_id. Warm-up, retries and ablations never enter the primary A0 quality denominator.

## 4. Canonical artifact layout

~~~text
artifacts/phase4/<run_id>/
  manifest.json
  attempts.jsonl
  grading.jsonl
  retrieval.jsonl
  errors.jsonl
  aggregate.json
  checksums.sha256
~~~

Aggregate must be recomputable from raw. Failed, skipped, blocked and retried cases remain in the bundle. No credentials, cookies or unredacted PII.

## 5. Local contract commands

The exact live command is stored in manifest. Local, no-network checks use:

~~~bash
python -B scripts/check_docs_contract.py
python -B scripts/check_eval_dataset.py evals/scenarios/benchmark_250.jsonl
python -B scripts/check_eval_dataset.py evals/scenarios/master_250_v1.jsonl
python -B scripts/check_deployment_contract.py
python -B scripts/check_live_e2e_contract.py
python -B scripts/build_agent_notebook.py --check
~~~

A live/model runner command is not implied by this document; it must record endpoint, lane, approval and cap.

## 6. Reproduction levels

| Level | Meaning | Evidence |
|---|---|---|
| L0 | dataset/schema/local contract | system SHA + frozen hashes |
| L1 | offline harness/metrics | L0 + raw bundle + grader/metric versions |
| L2 | model quality | L1 + model/DB/KB/fixture/config identity |
| L3 | latency/load | L2 + hardware/network/concurrency/timing |
| L4 | production/pilot | separate live-data/SLO/rollback evidence |

## 7. Implementation backlog

| ID | Acceptance | Status |
|---|---|---|
| R01 | clean checkout emits canonical bundle/checksums | PASS BRANCH OFFLINE/CI — 8a666fc mock SHA đúng/full local575 PASS/49 skipped; K7/C6 PASS, sign-off/G2 merged replay chưa có |
| R02 | validator rejects missing/duplicate joins and recomputation mismatch | ACCEPTABLE v1 — joins/rates/N2 DONE; N3 counts backlog, không block merge |
| R03 | manifest separates system/harness/overlay and unavailable provider fields | PASS COHERENCE/QRELS/MOCK DENY — N1 actual-source replay deferred P5-01 |
| R04 | stratified smoke, quota/cap and fixture/identity sidecar | BACKLOG LIVE — sidecar offline có; smoke/quota/cap chưa authorize; G4 proof không được suy từ schema PASS |

Until R01–R04 have evidence, no paid/cloud/full measurement is authorized and status remains READY FOR HARNESS/PREFLIGHT.
