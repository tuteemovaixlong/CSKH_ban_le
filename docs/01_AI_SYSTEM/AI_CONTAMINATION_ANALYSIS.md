# AI Contamination Analysis

> Nguồn: [DATA.digest](../_digest/code/DATA.digest), [EVAL.digest](../_digest/code/EVAL.digest), [RAG.digest](../_digest/code/RAG.digest). Snapshot local `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`, ngày 2026-10-08; merged SHA sau G2 [UNVERIFIED] theo [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104).

## 1. Câu hỏi và giới hạn của phép kiểm tra

Đã tính giao tập chính xác giữa ba scenario files theo `id`, chuỗi `user_text` đã decode và toàn bộ JSON row (serialize sort_keys=True). Đây là kiểm tra trùng dữ liệu đánh giá local; không phải kiểm tra toàn bộ training corpus của model. Phương pháp và nguồn: [DATA §6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [baseline_v1.jsonl:1](../../evals/scenarios/baseline_v1.jsonl#L1), [benchmark_250.jsonl:1](../../evals/scenarios/benchmark_250.jsonl#L1), [master_250_v1.jsonl:1](../../evals/scenarios/master_250_v1.jsonl#L1). Không thực hiện fuzzy/embedding/template comparison trong phép tính này.

## 2. Exact overlap giữa các scenario files

| Hai tập | ID trùng | user_text trùng | Whole row trùng | Digest + dữ liệu gốc |
|---|---:|---:|---:|---|
| baseline30 ↔ benchmark250 |0|0|0| [DATA §6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [baseline:1](../../evals/scenarios/baseline_v1.jsonl#L1), [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1) |
| baseline30 ↔ master250 |0|0|0| [DATA §6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [baseline:1](../../evals/scenarios/baseline_v1.jsonl#L1), [master:1](../../evals/scenarios/master_250_v1.jsonl#L1) |
| benchmark250 ↔ master250 |250|250|250| [DATA §6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [master:1](../../evals/scenarios/master_250_v1.jsonl#L1) |

Master và benchmark được kế hoạch nguồn gọi là mirror; chúng có cùng frozen LF SHA-256. Không xem chúng là hai bộ test độc lập: [DATA §2/6](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [constants.py:30](../../evals/harness/constants.py#L30), [plan:11](../phase4/PLAN_PHASE_4_EVALUATION.md#L11).

## 3. Exact overlap dev và held_out

| File | dev / held_out | ID giao nhau | user_text giao nhau | Digest + dữ liệu gốc |
|---|---|---:|---:|---|
| baseline_v1 |18/12|0|0| [DATA §2/6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [baseline:1](../../evals/scenarios/baseline_v1.jsonl#L1) |
| benchmark_250 |150/100|0|0| [DATA §2/6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1) |
| master_250_v1 |150/100|0|0| [DATA §2/6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [master:1](../../evals/scenarios/master_250_v1.jsonl#L1) |

Protocol giữ dev cho harness/smoke và held_out chạy một lần final mỗi cell; retry câu sai không thay primary sample. Đây là quy định sử dụng dữ liệu, không chứng minh operator chưa từng xem held_out: [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [statistics:49](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L49), [validator.py:182](../../evals/harness/validator.py#L182).

## 4. Knowledge và label exposure

Local inventory có9knowledge Markdown, qrels250queries và sidecar250entries. Qrels/sidecar được mock runner đọc để tạo evidence/chấm và mô phỏng candidate retrieval; kết quả mô phỏng không dùng làm bằng chứng model chưa nhìn thấy nhãn. Nguồn: [DATA §3/5](../_digest/code/DATA.digest#3-sidecarqrels-inventory--local-computation), [EVAL §10](../_digest/code/EVAL.digest#10-telemetry-và-mock) + [qrels.py:90](../../evals/harness/qrels.py#L90), [runner.py:331](../../evals/harness/runner.py#L331), [sidecar.py:44](../../evals/harness/sidecar.py#L44). Chi tiết cơ chế corpus/runtime xem [RAG.digest](../_digest/code/RAG.digest) và [AI_RAG_PIPELINE](AI_RAG_PIPELINE.md).

## 5. Unknown / Unverified

| Câu hỏi chưa được xác minh | Vì sao chưa kết luận | Digest + nguồn giới hạn |
|---|---|---|
| [UNVERIFIED] Benchmark từng nằm trong pretraining/fine-tuning của model? |Không có training corpus/checkpoint provenance trong inventory | [DATA §7](../_digest/code/DATA.digest#7-unknown--unverified) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [seed:1](../../data/deepseek_seed_data.json#L1) |
| [UNVERIFIED] Paraphrase/template trùng giữa dev và held_out? |Exact-string intersection không kiểm semantic overlap | [DATA §6/7](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [master:1](../../evals/scenarios/master_250_v1.jsonl#L1) |
| [UNVERIFIED] Operator đã tune prompt/model trên held_out? |Protocol quy định usage; không có exposure log được xác minh ở phép kiểm này | [EVAL §12](../_digest/code/EVAL.digest#12-planned-protocol-and-statistics) + [statistics:49](../phase4/PHASE_4_STATISTICAL_ANALYSIS.md#L49) |
| [UNVERIFIED] Nhãn/expected_outcome lọt vào request model live? |Mock đọc nhãn để giả lập; chưa có live request trace để kiểm đường model thật | [EVAL §10/14](../_digest/code/EVAL.digest#10-telemetry-và-mock) + [runner.py:204](../../evals/harness/runner.py#L204), [runner.py:331](../../evals/harness/runner.py#L331) |
| [UNVERIFIED] KB-vs-training leakage và deployed corpus? |Seed/knowledge local không xác định training set hay vector index live | [DATA §7](../_digest/code/DATA.digest#7-unknown--unverified), [RAG](../_digest/code/RAG.digest) + [faq.md:9](../../data/knowledge/faq.md#L9), [infra:64](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md#L64) |

Kết quả được phép báo cáo là **các số exact overlap ở §2–3**. Không dùng chúng để tuyên bố “train/test không contamination”. Không mở audit mới hoặc thay acceptance vì các trường chưa xác minh ở trên; phạm vi cố định lấy từ [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1) + [acceptance:72](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L72).

Đọc tiếp: [DATA_CONTRACT](../02_DATA_CONTRACTS/DATA_CONTRACT.md), [FROZEN_BENCHMARKS](../02_DATA_CONTRACTS/FROZEN_BENCHMARKS.md), [AI_REPRODUCIBILITY](AI_REPRODUCIBILITY.md).
