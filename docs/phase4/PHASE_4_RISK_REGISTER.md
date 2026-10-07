# Phase 4 — Risk Register

Status: READY FOR HARNESS/PREFLIGHT — controls are specified; no risk is closed without evidence (2026-10-06).

## 1. Rules

A risk is closed only by the artifact named in its mitigation. Blocked means the affected lane/metric cannot be interpreted. Every fallback creates a new run/config identity. Frozen benchmark and labels remain unchanged.

## 2. Register

| ID | Trigger / impact | Required mitigation and evidence | Stop / fallback | Status |
|---|---|---|---|---|
| R-01 | Frozen hash mismatch invalidates comparability | Verify both frozen hashes before/after; manifest | Stop run | Open |
| R-02 | Model/tokenizer/quantization drift | Pin digest/startup/checksum | Split results; no pooling | Open |
| R-03 | GPU unavailable/OOM/driver mismatch | nvidia-smi, VRAM, startup and stratified dev smoke; record hardware | Lane BLOCKED; approved fallback gets new identity | Open |
| R-04 | Provider/model fallback or topology mismatch | Assert lane/adapter/endpoint/returned model/tool IDs | Mark runtime error; no silent fallback | Open |
| R-05 | API/provider quota or outage | Separate app quota, provider quota and GPU capacity; ledger/status/retry-after | Pause lane; retain records | Open |
| R-06 | Answer/tool/DB cache contamination | A0 answer-cache OFF assertion; fresh tenant; cache mode in manifest | Invalidate contaminated run | Open |
| R-07 | Template leakage across split | scenario_family overlap/exposure report | Limit claim; no held-out tuning | Open |
| R-08 | Non-deterministic provider | Register supported seed/settings; record unavailable seed honestly | Report variance; no seed cherry-pick | Open |
| R-09 | Fixture/identity/DB drift | Immutable sidecar, owner assertions, PG/KB snapshot | Block affected category/lane | Open |
| R-10 | Timeout/retry hides first failure | Append every attempt, retry policy and cumulative wait | Classify transport failure | Open |
| R-11 | Citation presence without support | Claim-level grader/qrels/adjudication | Separate citation and support metrics | Open |
| R-12 | Grader disagreement | Blind double grade, anchors, adjudication/agreement | Mark unresolved/inconclusive | Open |
| R-13 | Missing/corrupt raw artifacts | Schema/count/checksum/aggregate validator before publication | No aggregate score | Open |
| R-14 | Cost/credential leak | Hard cap, approval, secret redaction and cost ledger | Stop lane; incident record | Open |
| R-15 | Shared EC2 lifecycle interference | Ownership/runbook and separate evaluation resource | Do not stop shared web host | Open |
| R-16 | Metric changes after results | Version metric/grader and pre-register gates | Recompute or mark incomparable | Open |
| R-17 | Load affects public service | Isolated synthetic stack and cap | Stop load | Open |
| R-18 | OCR/embedding/reranker enters baseline | New arm/config/dataset and gate | Defer to 4B | Open |
| R-19 | Grader/importer turns missing evidence into pass | Adversarial tests; actual_mode from raw | Block measurement | Open |
| R-20 | Missing qrels/labels/sidecar | Versioned qrels/fixture/identity hashes | Metric blocked | Open |
| R-21 | Unmeasured telemetry encoded as zero | null + unavailable_reason; validator rejects fabricated zero | Block artifact | Open |
| R-22 | App quota stops scheduled workload | Projected ledger and scheduled-vs-graded denominator | Stop lane; report blocked | Open |
| R-23 | Raw schema/join mismatch | Per-record schema, key uniqueness, retry sequence, recomputation tests | G1 blocked | Open |
| R-24 | Harness changes A0 business behavior | Allow only eval-only files/overlay; system variant if runtime changes | Reject build for baseline | Open |

## 3. Analyzable release

A run is analyzable only when R-01, R-02, R-04, R-06, R-09, R-13, R-16, R-20, R-21, R-23 and R-24 have evidence for that lane. Open residual threats must be listed in the report; no paid/full run is authorized by this file.
