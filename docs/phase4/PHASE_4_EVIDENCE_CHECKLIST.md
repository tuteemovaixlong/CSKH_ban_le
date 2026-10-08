# PHASE_4_EVIDENCE_CHECKLIST — Evidence và gate

> **Merge policy owner chốt 2026-10-08:** [Acceptance v1](PHASE_4_ACCEPTANCE_CRITERIA.md): đúng8check; N1 manifest mutation/N3 denominator/N4 safety types DONE trong scope v1. [Evidence HEAD a19ed2a](PHASE_4_ACCEPTANCE_EVIDENCE_a19ed2a.md): K1–K6 PASS, K7/C6 FAIL, independent sign-off PENDING. Chỉ sửa nguyên nhân K7 rồi verify đúng8check trên frozen SHA mới; independent source mới sign-off8/8 → owner review → merge → G2. N1 replay/counts/tool-name semantics, L2/L4/L5 và việc ngoài checklist → [Phase5 backlog](PHASE_5_BACKLOG.md), không block merge. Findings/progress lịch sử bên dưới không mở thêm merge gate.

> **Trạng thái (2026-10-08):** READY FOR HARNESS/PREFLIGHT. HEAD `a19ed2a` đạt K1–K6: full local575 tests PASS/49 skipped, CI5 success, mock250 PASS. K7/C6 FAIL trên patch merge do5 blank lines EOF; independent sign-off PENDING. N1 replay/counts/tool-name semantics vào Phase5, không block merge; chưa merge/G2/live.

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
| F01 | grader routing/tool/owner/outcome/claim/safety | schema, taxonomy, fixture | DONE OFFLINE K3 TYPES — N4 type gate PASS tại a19ed2a; semantic evidence backlog |
| F02 | identity/fixture sidecar setup idempotent | frozen JSONL, DB | OFFLINE IMPLEMENTED — source replay hardening deferred P5-01; live fixture sau |
| F09 | qrels, claim labels, answerability, adjudication | corpus/annotation | PASS SOURCE PIN — L2 CLI/live annotation backlog, không block merge |
| M01 | metric numerator/denominator, CI, first/eventual | metrics/statistics | PASS PRIMARY DENOMINATOR — completeness/counts backlog P5-02; live statistics sau |
| M02 | cache/retry/no-evidence/blocked handling | schema, runner | PASS OFFLINE — cache/retry/N2/blocked denominator; completeness backlog |
| M03 | telemetry completeness and unavailable identity | infra/harness | PASS MODEL TELEMETRY/K3 TYPES — live sau |
| M05 | canonical writer/validator/checksum | results schema | ACCEPTABLE v1 — source replay/count semantics deferred; K7/C6 FAIL và independent sign-off PENDING |
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

Only G5 may grant READY FOR MEASUREMENT in a lane manifest. Preflight/null-harness/mock bundles cannot grant it (N5 deny đã kiểm chứng offline; live G4/completeness acceptance vẫn chưa mở). Missing artifact, missing identity, mock/CPU-only output or HTTP-200-only evidence cannot close G5.
