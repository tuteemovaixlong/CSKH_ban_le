# Evaluation Protocol

> Nguồn: [EVAL.digest](../_digest/code/EVAL.digest), [DATA.digest](../_digest/code/DATA.digest), [CONTRACTS.digest](../_digest/code/CONTRACTS.digest). Snapshot local `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`, ngày 2026-10-08; merged SHA sau G2 [UNVERIFIED]. Tài liệu này không cấp quyền merge/paid/cloud/live và không tuyên bố G2 đã xong: [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1) + [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104).

## 1. Identity phải ghi trước mỗi run

| Identity | Nội dung nguồn yêu cầu | Digest + source |
|---|---|---|
| system_commit_sha |Runtime revision được đo; khác revision harness | [EVAL §2](../_digest/code/EVAL.digest#2-bundle-identity-và-joins) + [constants.py:34](../../evals/harness/constants.py#L34), [handoff:23](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L23) |
| evaluation_harness_sha |Immutable harness revision; sau merge dùng merged revision | [CONTRACTS §3](../_digest/code/CONTRACTS.digest#3-r12--schemajoinsprovenance) + [schema.py:119](../../evals/harness/schema.py#L119), [handoff:24](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L24) |
| evaluation_overlay_sha256 |Evaluation instrumentation riêng hoặc none | [EVAL §2](../_digest/code/EVAL.digest#2-bundle-identity-và-joins) + [constants.py:34](../../evals/harness/constants.py#L34), [handoff:25](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L25) |
| Inputs/config |Dataset/fixture/KB/qrels/config/prompt/protocol/grader versions/hashes | [EVAL §2/3](../_digest/code/EVAL.digest#3-scenario-sidecar-và-qrels), [DATA §2/3](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [schema.py:93](../../evals/harness/schema.py#L93), [handoff:26](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L26) |
| Lane/provider/model |lane_id/provider_id/endpoint/model/revision/sampling thực; null+reason khi unavailable | [CONTRACTS §3](../_digest/code/CONTRACTS.digest#3-r12--schemajoinsprovenance) + [schema.py:188](../../evals/harness/schema.py#L188), [handoff:28](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L28) |

## 2. G2 đến G7 — checklist protocol đã có

| Gate | Điều kiện / công việc theo nguồn | Evidence để ghi | Digest + code/doc gốc |
|---|---|---|---|
| G2 MERGED_VERIFIED |Owner merge rồi clean merged checkout; CI/contracts/frozen hashes/mock replay đúng harnessSHA |Merged revision, CI URLs, commands/exits, frozen hashes, raw bundle/checksums | [CONTRACTS §2/5](../_digest/code/CONTRACTS.digest#2-r11--gatereadiness) + [gates.py:28](../../evals/harness/gates.py#L28), [acceptance:91](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L91) |
| G3 SMOKE_AUTHORIZED |Owner approval smoke riêng; lane/quota/price/cap/stop rule đủ |Approval ID, price source, cap/quota/selector | [EVAL §11/13](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [gates.py:29](../../evals/harness/gates.py#L29), [cost:48](../phase4/PHASE_4_COST_BUDGET.md#L48) |
| G4 LIVE_SMOKE |Stratified dev IDs per lane; endpoint/DB/KB thật; cache/retry assertions |Live identity, fixture, KB/qrels hashes, trace/raw valid | [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [gates.py:30](../../evals/harness/gates.py#L30), [handoff:39](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L39) |
| G5 LANE_MEASUREMENT_READY |Chỉ G5 cho khai báo READY FOR MEASUREMENT; lane evidence phải đủ |Validated smoke manifest, identity/completeness/budget checks | [CONTRACTS §2](../_digest/code/CONTRACTS.digest#2-r11--gatereadiness) + [gates.py:71](../../evals/harness/gates.py#L71), [handoff:45](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L45) |
| G6 FULL_MEASUREMENT_AUTHORIZED |Full-run approval/cap riêng; G5 không tự cấp full run |Approval ID/full cap/preregistered workload | [EVAL §11/13](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [gates.py:32](../../evals/harness/gates.py#L32), [handoff:41](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L41) |
| G7 MEASURED |Chạy và báo raw/aggregate/metrics/statistics/cost/limitations theo protocol |Run identity, raw bundle, first/eventual metrics, CI, decision | [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [gates.py:33](../../evals/harness/gates.py#L33), [handoff:81](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L81) |

State machine không cho skip/backwards/same gate. Object chỉ trả measurement-ready tạiG5; G6 là authorization execution riêng, không là gate tuyên bố lane readiness. Nguồn: [CONTRACTS §2](../_digest/code/CONTRACTS.digest#2-r11--gatereadiness) + [gates.py:106](../../evals/harness/gates.py#L106), [gates.py:129](../../evals/harness/gates.py#L129).

## 3. Workload, số lần chạy và denominator

| Arm | Quy định trong nguồn | Digest + code/data/doc gốc |
|---|---|---|
| Quality A0 |250cases từ master/benchmark mirror; dev150/held_out100; cache đọc/ghiOFF; tenant/conversation mới | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation), [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [telemetry.py:110](../../evals/harness/telemetry.py#L110), [plan:33](../phase4/PLAN_PHASE_4_EVALUATION.md#L33) |
| Held-out final |100held_out chạy một lần final mỗi cell; không tune held_out | [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [master:1](../../evals/scenarios/master_250_v1.jsonl#L1), [statistics:49](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L49) |
| Load |Client concurrency1/2/4/8/16; mỗi level>=3repetitions độc lập; cap/duration pin trước run | [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [infra:43](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md#L43), [statistics:51](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L51) |
| Cold/warm/ablation |Run IDs riêng; warmup/population/reset ghi manifest; không vào A0primary | [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [plan:34](../phase4/PLAN_PHASE_4_EVALUATION.md#L34), [validator.py:182](../../evals/harness/validator.py#L182) |
| Retry |Transport/runtime theo retry_policy; mọi attempt append; firstprimary/eventualsecondary; wrong-answer diagnostic riêng | [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [validator.py:159](../../evals/harness/validator.py#L159), [validator.py:214](../../evals/harness/validator.py#L214), [plan:35](../phase4/PLAN_PHASE_4_EVALUATION.md#L35) |

Không cộng hai mirror250files thành500samples hoặc coi retries độc lập. Primary/secondary code definitions xem [METRICS_DICTIONARY](../02_DATA_CONTRACTS/METRICS_DICTIONARY.md): [DATA §6](../_digest/code/DATA.digest#6-exact-overlap--local-computation), [EVAL §7/12](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:150](../../evals/harness/validator.py#L150), [statistics:7](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L7).

## 4. Lệnh offline từ CLI hiện hữu

Ví dụ gọi từ project root, với RUN_DIR là thư mục riêng được chọn cho run (không chạy các lệnh này trong lượt tổ chức docs): [EVAL §1](../_digest/code/EVAL.digest#1-module-và-giao-diện) + [cli.py:119](../../evals/harness/cli.py#L119).

```powershell
python -B -m evals.harness.cli mock-run --run-id g2-offline --outdir <RUN_DIR> --benchmark evals/scenarios/benchmark_250.jsonl
python -B -m evals.harness.cli validate --run-dir <RUN_DIR>
python -B -m evals.harness.cli recompute --run-dir <RUN_DIR>
```

`recompute` validate rồi in aggregate; không ghi đè file. Mock-run là giả lập, không tự tiến gate hoặc cấp readiness: [EVAL §1/10](../_digest/code/EVAL.digest#1-module-và-giao-diện) + [cli.py:65](../../evals/harness/cli.py#L65), [runner.py:163](../../evals/harness/runner.py#L163), [gates.py:71](../../evals/harness/gates.py#L71).

## 5. Cost, stop và báo cáo

Cost model đã chốt gồm EC2+GPU+API+storage+egress+observability+annotation+contingency; estimate/actual riêng; thiếu giá là UNKNOWN. Dừng trước batch kế tiếp nếu projected spend>80%cap, price/quota unknown, credential exposure, retry không thêm evidence, config identity đổi hoặc hết quota. Không dừng vì có run đẹp. Nguồn: [EVAL §13](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [cost:7](../phase4/PHASE_4_COST_BUDGET.md#L7), [cost:60](../phase4/PHASE_4_COST_BUDGET.md#L60), [statistics:52](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L52).

Raw bundle gồm7canonicalfiles; aggregate recompute từ raw; report cần numerator/denominator/missing/blocked/CI/first-eventual/taxonomy/cost/decision. Điền [EXPERIMENT_LOG](EXPERIMENT_LOG.md), link raw/checksums, không bịa score từ mock. Nguồn: [EVAL §2/8/12](../_digest/code/EVAL.digest#2-bundle-identity-và-joins) + [constants.py:19](../../evals/harness/constants.py#L19), [validator.py:741](../../evals/harness/validator.py#L741), [statistics:56](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L56).

## 6. Unknown / Unverified

- [UNVERIFIED] Merged SHA/G2/sign-off: source PENDING. [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1) + [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104).
- [UNVERIFIED] Live runner command, exact dev smoke selector, endpoint/DB/KB evidence: chưa được xác minh; không sinh lệnh gọi model từ CLI mock. [EVAL §14](../_digest/code/EVAL.digest#14-unknown--unverified) + [cli.py:119](../../evals/harness/cli.py#L119), [repro:64](../phase4/PHASE_4_REPRODUCIBILITY.md#L64).
- [UNVERIFIED] Price/cap/approval thực: source đểPENDING/null. [EVAL §13/14](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [cost:34](../phase4/PHASE_4_COST_BUDGET.md#L34).

Đọc tiếp: [AI evaluation/safety](../01_AI_SYSTEM/AI_EVALUATION_AND_SAFETY.md), [frozen benchmarks](../02_DATA_CONTRACTS/FROZEN_BENCHMARKS.md), [runbook](../04_OPERATIONS/RUNBOOK.md).
