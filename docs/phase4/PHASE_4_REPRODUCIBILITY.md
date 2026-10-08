# PHASE_4_REPRODUCIBILITY — Reproduction protocol

> Status: READY FOR HARNESS/PREFLIGHT — writer/validator/mock replay đã có ở HEAD `1f8c344`; acceptance provenance và live evidence vẫn chưa đóng.

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
| R01 | clean checkout emits canonical bundle/checksums | PARTIAL — mock replay PASS; clean-checkout/CI evidence pending |
| R02 | validator rejects missing/duplicate joins and recomputation mismatch | PARTIAL — H8/H9 PASS; orphan evidence refs F1 còn mở |
| R03 | manifest separates system/harness/overlay and unavailable provider fields | PARTIAL — placeholder harness SHA F2 còn mở |
| R04 | stratified smoke, quota/cap and fixture/identity sidecar | BACKLOG — chưa được authorize |

Until R01–R04 have evidence, no paid/cloud/full measurement is authorized and status remains READY FOR HARNESS/PREFLIGHT.
