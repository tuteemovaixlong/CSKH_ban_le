# Data Contract

> Nguồn: [DATA.digest](../_digest/code/DATA.digest), [EVAL.digest](../_digest/code/EVAL.digest), [CONTRACTS.digest](../_digest/code/CONTRACTS.digest). Snapshot local `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`, ngày 2026-10-08. Merged SHA sau G2 [UNVERIFIED] theo [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104).

## 1. Ba lớp dữ liệu hiện có

| Lớp | File / số lượng tính local | Nguồn và mục đích trực tiếp |
|---|---|---|
| Scenario contracts | baseline30; benchmark250; master250; mỗi row có9fields | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [baseline:1](../../evals/scenarios/baseline_v1.jsonl#L1), [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [master:1](../../evals/scenarios/master_250_v1.jsonl#L1) |
| Annotation/fixture | qrels250queryrows; sidecar250caseentries | [DATA §3](../_digest/code/DATA.digest#3-sidecarqrels-inventory--local-computation) + [qrels:3](../../evals/qrels/policy_qrels_v1.json#L3), [sidecar:2](../../evals/fixtures/sidecar_250.json#L2), [qrels.py:90](../../evals/harness/qrels.py#L90) |
| Business seeds/knowledge | products19; mock shipments8; deepseek seed8products/6customers/8orders/8shipments/8inventory;9Markdownknowledge | [DATA §4/5](../_digest/code/DATA.digest#4-business-json-inventory--local-computation) + [products:3](../../data/products.json#L3), [shipments:2](../../data/mock_shipments.json#L2), [seed:2](../../data/deepseek_seed_data.json#L2), [faq:9](../../data/knowledge/faq.md#L9) |

Demo FAQ gọi đơn/sản phẩm/chính sách là dữ liệu tổng hợp phục vụ kiểm thử; đây không phải chứng nhận một deployment đang dùng cùng dữ liệu: [DATA §5/7](../_digest/code/DATA.digest#5-knowledge-inventory--local-computation-lf-hashes) + [faq.md:9](../../data/knowledge/faq.md#L9), [infra:64](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md#L64).

## 2. Contract của một scenario row

| Field | Giá trị / vai trò thấy trong nguồn | Digest + nguồn gốc |
|---|---|---|
| id |Case identifier; bundle attempts dùng case_id trong scenario membership | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation), [EVAL §3](../_digest/code/EVAL.digest#3-scenario-sidecar-và-qrels) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [validator.py:469](../../evals/harness/validator.py#L469) |
| split |dev/held_out;250files có150/100; baseline18/12 | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [baseline:1](../../evals/scenarios/baseline_v1.jsonl#L1) |
| category |order_lookup/product/policy/mixed/general/safety | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [baseline:1](../../evals/scenarios/baseline_v1.jsonl#L1) |
| user_text |Input text trong JSONL; mock đọc case row | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation), [EVAL §3](../_digest/code/EVAL.digest#3-scenario-sidecar-và-qrels) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [sidecar.py:48](../../evals/harness/sidecar.py#L48) |
| expected_mode |general/retail; grader so actual_mode khi cả hai tồn tại | [EVAL §4](../_digest/code/EVAL.digest#4-grader-check-order) + [grader.py:148](../../evals/harness/grader.py#L148) |
| expected_tools / forbidden_tools |Danh sách tool bắt buộc/cấm dùng để chấm | [EVAL §4](../_digest/code/EVAL.digest#4-grader-check-order) + [grader.py:78](../../evals/harness/grader.py#L78), [grader.py:155](../../evals/harness/grader.py#L155) |
| expected_outcome / safety |Nhãn outcome/safety trong scenario; grader dùng expected_outcome để nhận dạng handoff | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation), [EVAL §4](../_digest/code/EVAL.digest#4-grader-check-order) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [grader.py:169](../../evals/harness/grader.py#L169) |

## 3. Frozen inputs và cách hash

| Input | Hash được contract dùng | Digest + nguồn gốc |
|---|---|---|
| benchmark_250 |LF SHA-256 `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411` | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [constants.py:30](../../evals/harness/constants.py#L30), [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1) |
| master_250_v1 |Cùng LF hash; ghi riêng file/hash dù là mirror | [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [master:1](../../evals/scenarios/master_250_v1.jsonl#L1), [infra:13](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md#L13) |
| policy_qrels_v1 |Text/LF `769a45d682648290a3356dad32aacae3c62f6942b62844dd4cc50f2d83c15161` | [DATA §3](../_digest/code/DATA.digest#3-sidecarqrels-inventory--local-computation) + [constants.py:31](../../evals/harness/constants.py#L31), [qrels.py:90](../../evals/harness/qrels.py#L90) |
| Sidecar |Canonical serialized hash `69e9835d3f4c63a2466d6ab08749737dcf59de65f2c22713372bd66b19bb3f2d`; không phải raw fixture hash | [DATA §1/3](../_digest/code/DATA.digest#3-sidecarqrels-inventory--local-computation) + [constants.py:32](../../evals/harness/constants.py#L32), [sidecar.py:102](../../evals/harness/sidecar.py#L102) |

Raw checkout hash và LF hash khác nhau khi có CRLF; không trim hoặc tự thêm newline lúc tính LF. Runner kiểm actual LF source trước emit; manifest schema kiểm declared hash; replay rehash hardening được defer theo acceptance. Nguồn: [DATA §1](../_digest/code/DATA.digest#1-phương-pháp-tính-local), [CONTRACTS §3](../_digest/code/CONTRACTS.digest#3-r12--schemajoinsprovenance) + [runner.py:137](../../evals/harness/runner.py#L137), [schema.py:158](../../evals/harness/schema.py#L158), [acceptance:24](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L24). Bảng raw/LF riêng: [FROZEN_BENCHMARKS](FROZEN_BENCHMARKS.md).

## 4. Provenance của raw result

Mỗi JSONL result phải có common envelope gồm run/case/logical_request, system/harness/overlaySHA, protocol/config/fixturehash và timestamp. Grading/retrieval/error phải join attempt cùng provenance; evidence refs cùng run/case/logical request. Nguồn: [CONTRACTS §3](../_digest/code/CONTRACTS.digest#3-r12--schemajoinsprovenance) + [constants.py:34](../../evals/harness/constants.py#L34), [schema.py:46](../../evals/harness/schema.py#L46), [validator.py:46](../../evals/harness/validator.py#L46), [validator.py:689](../../evals/harness/validator.py#L689).

## 5. Unknown / Unverified

- [UNVERIFIED] Creator và creation time của benchmarks/qrels/fixtures: source metadata không cung cấp; không suy từ ngày commit hay tên seed file. [DATA §7](../_digest/code/DATA.digest#7-unknown--unverified) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [qrels:1](../../evals/qrels/policy_qrels_v1.json#L1), [sidecar:1](../../evals/fixtures/sidecar_250.json#L1).
- [UNVERIFIED] Actual deployed DB/index/corpus snapshot và train-set provenance. [DATA §7](../_digest/code/DATA.digest#7-unknown--unverified) + [seed:1](../../data/deepseek_seed_data.json#L1), [infra:64](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md#L64).

Đọc tiếp: [metric dictionary](METRICS_DICTIONARY.md), [contamination](../01_AI_SYSTEM/AI_CONTAMINATION_ANALYSIS.md), [evaluation protocol](../03_EVALUATION/EVALUATION_PROTOCOL.md).
