# Phase 4 — Timeline and Milestones

Status (2026-10-08): READY FOR HARNESS/PREFLIGHT — M1–M3 đã có implementation/local/CI evidence tại `48b84cd`, nhưng N1–N5 acceptance còn mở. Chưa merge hoặc thực hiện live/paid/deploy trong lượt review.

## 1. Gantt

~~~mermaid
gantt
    title Phase 4 Scientific Evaluation (proposed)
    dateFormat  YYYY-MM-DD
    axisFormat  %d/%m
    section Contract and harness
    Freeze scope and metric/grader versions :m0, 2026-10-06, 1d
    Build grader fixture qrels telemetry   :m1, after m0, 4d
    Validate dataset and raw schemas       :m2, after m1, 2d
    Offline acceptance and clean replay    :m3, after m2, 2d
    section Authorization and measurement
    Smoke approval and lane preflight      :m4, after m3, 1d
    Live stratified smoke per lane         :m5, after m4, 2d
    Full quality run after approval        :m6, after m5, 2d
    Load matrix 1/2/4/8/16               :m7, after m6, 2d
    section Analysis and decision
    Statistical analysis and validity      :m8, after m7, 3d
    Evidence bundle and thesis tables      :m9, after m8, 2d
    Phase 4 decision gate                  :m11, after m9, 1d
~~~

## 2. Milestones and exit criteria

| Milestone | Deliverable | Exit criterion |
|---|---|---|
| M0 Scope freeze | metric, taxonomy, identities, scope | no unversioned model/protocol choice |
| M1 Harness build | grader, fixture/identity, qrels, telemetry | adversarial dry-run catches intended failures |
| M2 Schema ready | raw schemas/writer/validator | join keys, nullability, checksums, recomputation pass offline |
| M3 Offline accepted | canonical bundle from mock | CI/local clean replay passes; no network/paid cost |
| M4 Smoke authorized | approval ID, quota/price/cap | owner explicitly authorizes selected lane(s) |
| M5 Live smoke | stratified dev smoke artifacts | actual endpoint/DB/KB identity, no fallback/mismatch |
| M6 Full quality | 250-case lane artifacts | first/eventual/retry and blocked records complete |
| M7 Load complete | 1/2/4/8/16 raw load samples | latency/throughput/429/fairness artifacts complete |
| M8 Analysis | CI/statistics/threats | all tables recompute from raw |
| M9 Evidence complete | checklist, cost ledger, checksums | reviewer can reproduce applicable L0–L3 claims |
| M11 Decision | handoff/report | explicit proceed, retrieval A/B, remediation or defer |

M5 corresponds to G4 live smoke and is not measurement readiness. Only the subsequent G5 lane gate may mark `READY FOR MEASUREMENT` in its manifest. M11 is a report decision, not a permission to bypass earlier gates.

## 3. Dependencies

- M0–M4 are offline and precede any paid/GPU-heavy run.
- M4 approval is separate from merge/CI.
- M5 is lane-specific; one blocked lane does not invalidate another but prevents paired comparison.
- M6 quality A0 uses answer-cache OFF. Cold/warm and cache ablations are separate runs.
- M7 load is separate from quality aggregate.
- Phase 4B embedding, reranker, OCR, summarization and live-data experiments open only after A0 decision and a named bottleneck.

## 4. Fallback and schedule changes

If GPU/API is unavailable, complete M0–M4 and report lane BLOCKED with fallback identity. Do not stop shared public EC2 without an ownership/runbook decision. Never compress by dropping raw evidence, changing frozen data or pooling lanes.

See PHASE_4_INFRASTRUCTURE_SPEC.md, PHASE_4_REPRODUCIBILITY.md and PHASE_4_EVIDENCE_CHECKLIST.md.

## 5. Tiến độ thực tế và bước tiếp theo (2026-10-08)

M0 spec/frozen baseline giữ nguyên. M1 harness implementation đã có; M2/M3 có local 563 tests/49 skipped, contracts/mock và CI/Docker xanh nhưng chưa accepted hoàn toàn vì N1–N5. Thực thi sửa theo [plan](PLAN_REVIEW_HANDOFF_GEMINI_2026-10-07.md), review lại HEAD mới, owner review/merge rồi G2 clean replay. M4/G3 authorization và mọi live milestone sau vẫn chưa mở; Gantt là kế hoạch, không phải bằng chứng hoàn thành.
