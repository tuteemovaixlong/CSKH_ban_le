# Experiment Log

> Đây là template tracking, chưa nhập run đo model. Nguồn field: [EVAL.digest](../_digest/code/EVAL.digest), [CONTRACTS.digest](../_digest/code/CONTRACTS.digest) + [schema.py:93](../../evals/harness/schema.py#L93), [cost:50](../phase4/PHASE_4_COST_BUDGET.md#L50). Snapshot local `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`, ngày 2026-10-08; merged SHA sau G2 [UNVERIFIED] theo [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104).

## 1. Trạng thái nguồn và quy tắc ghi

Acceptance nguồn ghi K1–K8PASS nhưng independent/owner/merge/G2PENDING. Mock result kiểm plumbing, không điền như model-quality run. Không tạo dòng thực nghiệm từ một planned protocol hoặc suy score từ CI: [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1), [EVAL §10/14](../_digest/code/EVAL.digest#10-telemetry-và-mock) + [acceptance:98](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L98), [runner.py:282](../../evals/harness/runner.py#L282).

## 2. Bảng tracking — để trống cho evidence thật

| run_id | date_utc | system_SHA | harness_SHA | overlay_hash | lane / provider / model | gate / run_kind | dataset / config hashes | cost_estimate_USD | cost_actual_USD | result / denominator | raw / checksums / approval links |
|---|---|---|---|---|---|---|---|---|---|---|---|

Đây là schema ghi chép đề xuất theo yêu cầu tổ chức docs; không phải thêm contract vào acceptance. Các cột identity, gate và run_kind nối manifest/runtime/harness; cost estimate/actual được tách theo source cost model: [EVAL §2/11/13](../_digest/code/EVAL.digest#2-bundle-identity-và-joins), [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1) + [schema.py:93](../../evals/harness/schema.py#L93), [gates.py:26](../../evals/harness/gates.py#L26), [cost:9](../phase4/PHASE_4_COST_BUDGET.md#L9), [acceptance:72](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L72).

## 3. Evidence cần liên kết khi điền một dòng

| Cụm thông tin | Field / nguồn để sao chép | Digest + source |
|---|---|---|
| Identity/time |run_id/systemSHA/harnessSHA/overlaySHA/lane/provider/created/completed từ manifest; model metadata/capture nếu có | [EVAL §2](../_digest/code/EVAL.digest#2-bundle-identity-và-joins) + [schema.py:93](../../evals/harness/schema.py#L93), [handoff:21](../phase4/PHASE_4_EXECUTION_HANDOFF.md#L21) |
| Inputs |Dataset/fixture/qrels/config/prompt/KBhashes và cache/retry/load profile | [EVAL §3/12](../_digest/code/EVAL.digest#3-scenario-sidecar-và-qrels) + [schema.py:93](../../evals/harness/schema.py#L93), [repro:9](../phase4/PHASE_4_REPRODUCIBILITY.md#L9) |
| Result |Numerator/denominator, first/eventual/quality/E2E, blocked/missing, severity và raw aggregate/checksums | [EVAL §7/8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:254](../../evals/harness/validator.py#L254), [writer.py:93](../../evals/harness/writer.py#L93) |
| Cost |Quantity/unit/price_source/actual amount/evidence_ref; null hoặc UNKNOWN khi thiếu | [EVAL §13](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [cost:50](../phase4/PHASE_4_COST_BUDGET.md#L50) |
| Authorization |Gate và approval/cap smoke/full riêng; merge/CI không tự approve chi phí | [CONTRACTS §2](../_digest/code/CONTRACTS.digest#2-r11--gatereadiness), [EVAL §13](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [gates.py:29](../../evals/harness/gates.py#L29), [cost:48](../phase4/PHASE_4_COST_BUDGET.md#L48) |

## 4. Unknown / Unverified

- [UNVERIFIED] Chưa nhập model measurement/cost/live latency vào template này; runner scanned là offline mock. [EVAL §14](../_digest/code/EVAL.digest#14-unknown--unverified) + [runner.py:1](../../evals/harness/runner.py#L1).
- [UNVERIFIED] Merged/G2/approved live identity và cap còn pending theo source. [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1), [EVAL §13](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104), [cost:34](../phase4/PHASE_4_COST_BUDGET.md#L34).

Đọc tiếp: [EVALUATION_PROTOCOL](EVALUATION_PROTOCOL.md), [METRICS_DICTIONARY](../02_DATA_CONTRACTS/METRICS_DICTIONARY.md), [AI_REPRODUCIBILITY](../01_AI_SYSTEM/AI_REPRODUCIBILITY.md).
