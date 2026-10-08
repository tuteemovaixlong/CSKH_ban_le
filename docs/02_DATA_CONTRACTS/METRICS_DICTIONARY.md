# Metrics Dictionary

> Nguồn: [EVAL.digest](../_digest/code/EVAL.digest), [CONTRACTS.digest](../_digest/code/CONTRACTS.digest). Snapshot local `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`, ngày 2026-10-08; merged SHA sau G2 [UNVERIFIED] theo [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104). Công thức §1–3 mô tả code hiện tại; §4 ghi protocol dự kiến riêng.

## 1. Đơn vị và ký hiệu code

| Ký hiệu / field | Định nghĩa đang thực thi | Digest + code gốc |
|---|---|---|
| N / n_total / logical_cases |Số case_id duy nhất trong attempts; không lấy trực tiếp scheduled count từ manifest | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:150](../../evals/harness/validator.py#L150) |
| n_attempt |len(attempts), gồm retry | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:152](../../evals/harness/validator.py#L152) |
| Effective grading |Adjudicated ưu tiên unadjudicated trên cùng attempt; reject duplicate cùng loại | [EVAL §2](../_digest/code/EVAL.digest#2-bundle-identity-và-joins) + [validator.py:101](../../evals/harness/validator.py#L101) |
| n_graded |Số case_id duy nhất có effective grading; blocked label cũng được thêm vào tập này | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:167](../../evals/harness/validator.py#L167) |
| n_blocked |Số case_id có effective decision=blocked_environment | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:173](../../evals/harness/validator.py#L173) |
| Q / n_graded_first |First attempt retry_index0, grading first_attempt=True, decision thuộc pass/partial/fail/abstain_correct/abstain_incorrect/rejected | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [constants.py:85](../../evals/harness/constants.py#L85), [validator.py:186](../../evals/harness/validator.py#L186) |
| P / first_passes |Unique first-attempt case IDs có decision pass hoặc abstain_correct trong Q | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:192](../../evals/harness/validator.py#L192) |
| E / eventual_passes |Case có latest attempt (max retry_index) với effective decision pass hoặc abstain_correct | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:214](../../evals/harness/validator.py#L214) |
| C / eventual_completed |Case có latest attempt outcome=completed | [EVAL §7](../_digest/code/EVAL.digest#7-aggregate-unit) + [validator.py:218](../../evals/harness/validator.py#L218) |

## 2. Aggregate formulas hiện tại

| Metric | Công thức thực thi | Empty denominator / precision | Digest + code gốc |
|---|---|---|---|
| quality_conditional |P/Q; giữ numerator=P, denominator=Q, rate |Q=0→0.0; round4| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:195](../../evals/harness/validator.py#L195) |
| first_attempt_success_rate |P/N |N=0→0.0; round4| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:244](../../evals/harness/validator.py#L244) |
| eventual_success_rate |E/N |N=0→0.0; round4| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:245](../../evals/harness/validator.py#L245) |
| e2e_success |C/N; giữ numerator=C, denominator=N, rate |N=0→0.0; round4| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:228](../../evals/harness/validator.py#L228) |
| retry_recovery_rate |size((all_case_ids−first_pass_case_ids)∩eventual_pass_case_ids)/size(all_case_ids−first_pass_case_ids) |No failed-first set→null; round4| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:236](../../evals/harness/validator.py#L236) |
| completeness |n_graded/N |N=0→0.0; round4| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:207](../../evals/harness/validator.py#L207) |
| n_missing_grading |max(0,N−n_graded−n_blocked) |Count | [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:206](../../evals/harness/validator.py#L206) |
| first_attempt_outcomes |Counter(outcome) của attempts retry_index0 |Histogram| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:159](../../evals/harness/validator.py#L159) |
| eventual_outcomes |Counter(outcome) của latest attempt per case |Histogram| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:209](../../evals/harness/validator.py#L209) |
| severity_counts / taxonomy_failure_counts |Đếm effective grading records; taxonomy gồm primary và mọi secondary |Histogram theo grading records| [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas) + [validator.py:247](../../evals/harness/validator.py#L247) |

`e2e_success` hiện kiểm outcome=`completed`, không kiểm tất cả điều kiện “response hợp lệ trong deadline” mà protocol mô tả cho e2e_reliability. Tài liệu ghi rõ tên và cách đếm; không đổi code hoặc tạo acceptance mới. Completeness/count semantics đã được defer theo owner: [EVAL §8](../_digest/code/EVAL.digest#8-current-aggregate-formulas), [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1) + [validator.py:228](../../evals/harness/validator.py#L228), [metrics source:27](../phase4/PHASE_4_METRICS_DEFINITION.md#L27), [acceptance:28](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L28).

## 3. Hàm retrieval hiện tại

Với R là relevant_ids, L là ordered retrieved IDs, và k mặc định5: [EVAL §9](../_digest/code/EVAL.digest#9-retrieval-functions) + [qrels.py:30](../../evals/harness/qrels.py#L30), [qrels.py:60](../../evals/harness/qrels.py#L60).

| Metric | Công thức / boundary code | Digest + code gốc |
|---|---|---|
| Recall@k |size(R∩set(L[:k]))/size(R); emptyR→0.0; round4 | [EVAL §9](../_digest/code/EVAL.digest#9-retrieval-functions) + [qrels.py:60](../../evals/harness/qrels.py#L60) |
| Precision@k |size(R∩set(L[:k]))/k; k<=0→0.0; round4 | [EVAL §9](../_digest/code/EVAL.digest#9-retrieval-functions) + [qrels.py:68](../../evals/harness/qrels.py#L68) |
| compute_mrr |1/rank_first_relevant cho một list; nohit/emptyR→0.0; round4 | [EVAL §9](../_digest/code/EVAL.digest#9-retrieval-functions) + [qrels.py:50](../../evals/harness/qrels.py#L50) |
| nDCG@k |DCG=sum((2^rel−1)/log2(rank+1)); IDCG với rel sorted giảm dần[:k]; DCG/IDCG; empty/IDCG<=0→0.0; round4 | [EVAL §9](../_digest/code/EVAL.digest#9-retrieval-functions) + [qrels.py:30](../../evals/harness/qrels.py#L30) |

Protocol yêu cầu no-evidence N/A/metric riêng và chỉ query có qrels áp dụng; hàm trả0.0 cho empty relevance không tự chứng minh caller đã dùng đúng denominator protocol. Candidate recall/served coverage phải tách: [EVAL §9/12](../_digest/code/EVAL.digest#9-retrieval-functions) + [qrels.py:32](../../evals/harness/qrels.py#L32), [statistics:23](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L23).

## 4. Telemetry và công thức protocol dự kiến

| Metric | Trích xuất và cấp thực thi | Digest + nguồn gốc |
|---|---|---|
| model_calls / provider_inference_ms |Measured hoặc null;0/0.0chỉ khi observerTrue+zero_reason hợp lệ; positivecalls cần positivetime | [CONTRACTS §1](../_digest/code/CONTRACTS.digest#1-r10--measured-zero) + [schema.py:282](../../evals/harness/schema.py#L282) |
| latency_ms |Collector elapsed monotonic time round2; mock value là overhead collector, không là live E2E/model latency | [EVAL §10](../_digest/code/EVAL.digest#10-telemetry-và-mock) + [telemetry.py:86](../../evals/harness/telemetry.py#L86), [runner.py:282](../../evals/harness/runner.py#L282) |
| queue_wait_ms / ttfb_ms |Collector khởi tạo null; schema trace không tạo measurement nếu chưa có observer | [EVAL §10](../_digest/code/EVAL.digest#10-telemetry-và-mock) + [telemetry.py:42](../../evals/harness/telemetry.py#L42) |
| p50/p95/p99 / throughput |Protocol: nearest-rank raw; completedlogicalcases/wallseconds; [UNVERIFIED] live aggregate implementation/result trong scanned harness | [EVAL §12/14](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [validator.py:254](../../evals/harness/validator.py#L254), [metrics source:61](../phase4/PHASE_4_METRICS_DEFINITION.md#L61) |
| Tokens / cost_per_success |Protocol: usage thực; total_cost/successfulcases; [UNVERIFIED] live ledger/result chưa có; thiếu không đổi thành0 | [EVAL §13/14](../_digest/code/EVAL.digest#13-planned-cost-and-stopping) + [runner.py:175](../../evals/harness/runner.py#L175), [metrics source:72](../phase4/PHASE_4_METRICS_DEFINITION.md#L72) |

## 5. Unknown / Unverified

- [UNVERIFIED] Model score/confidence interval/latency/cost thật; mock không là measurement. [EVAL §14](../_digest/code/EVAL.digest#14-unknown--unverified) + [runner.py:1](../../evals/harness/runner.py#L1), [statistics:56](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L56).
- [UNVERIFIED] Live caller áp dụng qrels no-evidence N/A và thống kê candidate/served đầy đủ. [EVAL §9](../_digest/code/EVAL.digest#9-retrieval-functions) + [qrels.py:30](../../evals/harness/qrels.py#L30), [statistics:23](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L23).

Đọc tiếp: [AI evaluation/safety](../01_AI_SYSTEM/AI_EVALUATION_AND_SAFETY.md), [data contract](DATA_CONTRACT.md), [protocol](../03_EVALUATION/EVALUATION_PROTOCOL.md).
