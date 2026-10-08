# PHASE_4_EVIDENCE_CHECKLIST — Evidence và gate

> Trạng thái (2026-10-08): READY FOR HARNESS/PREFLIGHT. HEAD `48b84cd` có offline/CI/Docker evidence, B1–B6 cũ DONE; N1–N5 còn mở theo [review](REVIEW_GEMINI_PHASE4_2026-10-07.md); chưa merge hoặc READY FOR MEASUREMENT.

## 1. Evidence levels

- L0: dataset/schema/local contract.
- L1: offline harness/grader/writer replay.
- L2: live model quality trên lane có identity/DB/KB.
- L3: latency/load trên hardware/network đã pin.
- L4: production/pilot evidence; ngoài phạm vi Phase 4.

## 2. Canonical artifacts

| ID | Artifact | Acceptance |
|---|---|---|
| E01 | manifest.json | run_id, system/harness/overlay tuple, protocol/config/dataset/fixture/KB/qrels hashes |
| E02 | attempts.jsonl | mỗi attempt append-only; first/retry keys và nullable telemetry đúng schema |
| E03 | grading.jsonl | first-attempt và eventual link, rubric/grader/adjudication, safety severity |
| E04 | retrieval.jsonl | candidate/served evidence, qrels version hoặc explicit no-evidence |
| E05 | errors.jsonl | taxonomy, stage, retryable, status, redacted message |
| E06 | aggregate.json | recompute từ raw, numerator/denominator/CI và derived_from |
| E07 | checksums.sha256 | checksum mọi artifact và input |

Canonical name là retrieval.jsonl; retrieval_traces.jsonl chỉ là historical alias.

## 3. Gate 4A — required

4A không phụ thuộc OCR, multimodal, positive mutation, multi-turn ablation hoặc embedding/reranker upgrade. Required:

- frozen dataset/hash/count và sidecar identity/fixture;
- offline grader adversarial tests;
- canonical writer/validator và schema round-trip;
- qrels/answerability/claim labels tối thiểu cho scope A0;
- cache/retry assertions, first/eventual split;
- provider/config/lane preflight;
- telemetry measured hoặc null + reason;
- CI và clean-checkout replay.

## 4. Gate 4B — conditional

4B chỉ mở sau A0 evidence và bottleneck decision:

- cache/history arms;
- retrieval/embedding/reranker;
- OCR/vision, positive mutation, live-data supplementary;
- provider comparison hoặc topology variants.

Arm chưa chạy là DESIGNED/BLOCKED; không đưa điểm giả vào scorecard.

## 5. Backlog acceptance

| ID | Acceptance check | Dependency | Status |
|---|---|---|---|
| F01 | grader routing/tool/owner/outcome/claim/safety | schema, taxonomy, fixture | PARTIAL OFFLINE — safety ordering DONE; N4 malformed trace và L1 null text còn mở; live rubric chưa nghiệm thu |
| F02 | identity/fixture sidecar setup idempotent | frozen JSONL, DB | OFFLINE IMPLEMENTED — sidecar 250 có; N1 hash binding/live fixture còn mở |
| F09 | qrels, claim labels, answerability, adjudication | corpus/annotation | PARTIAL — qrels/labels offline có; N1 fail-closed source và annotation/adjudication live còn mở |
| M01 | metric numerator/denominator, CI, first/eventual | metrics/statistics | PARTIAL — recompute checks có; N3 quality denominator và statistical CI live chưa đạt |
| M02 | cache/retry/no-evidence/blocked handling | schema, runner | PARTIAL — cache/retry append có; N2 duplicate schedule/N3 blocked handling còn mở |
| M03 | telemetry completeness and unavailable identity | infra/harness | PASS OFFLINE MOCK — model telemetry có; N4 tool/safety typing và live identity còn mở |
| M05 | canonical writer/validator/checksum | results schema | PARTIAL — writer/checksum/refs có; N1/N2/N3 và L2 còn mở |
| M06 | importer preserves split/category/actual mode from raw | raw schema/taxonomy | BACKLOG — importer/scorecard theo split/category/actual mode chưa nghiệm thu |

## 6. Readiness rules

G0 SPEC_ACCEPTED: contract and scope agree.
G1 HARNESS_ACCEPTED: offline adversarial fixtures and raw recomputation pass.
G2 MERGED_VERIFIED: merge/CI + clean checkout replay pass.
G3 SMOKE_AUTHORIZED: explicit owner approval, quota/price cap and stop rule.
G4 LIVE_SMOKE: live stratified smoke with actual provider/DB/KB, cache/retry/identity and artifact validation; this is not measurement readiness.
G5 LANE_MEASUREMENT_READY: the only gate that may write READY FOR MEASUREMENT after G4 evidence, completeness, budget and identity checks pass.
G6 FULL_RUN_AUTHORIZED: separate full-run approval and preregistered workload.
G7 MEASURED: full run and analysis artifacts complete.

Only G5 may grant READY FOR MEASUREMENT in a lane manifest. Preflight/null-harness/mock bundles cannot grant it (N5 implementation còn mở). Missing artifact, missing identity, mock/CPU-only output or HTTP-200-only evidence cannot close G5.
