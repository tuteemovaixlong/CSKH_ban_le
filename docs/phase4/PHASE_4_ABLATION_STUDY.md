# Phase 4 — Ablation Study

> **Mục tiêu:** đo đóng góp của từng thành phần bằng cách giữ nguyên mọi yếu tố khác. Ablation là thí nghiệm đánh giá; không được tắt guardrail hoặc ownership check trong môi trường phục vụ người dùng.

> **Trạng thái (2026-10-06):** `READY FOR HARNESS/PREFLIGHT`. Các arm dưới đây là thiết kế; chưa arm nào được coi là đã chạy chỉ vì có trong tài liệu.

## 1. Nguyên tắc thiết kế

- Mỗi arm dùng cùng benchmark ID, split, prompt, tool contract, timeout, seed và grader.
- Dùng paired comparison theo từng case; không chỉ so sánh trung bình giữa hai run độc lập.
- Thứ tự chạy được randomize hoặc counterbalance khi có nguy cơ drift/cost bias.
- `held_out` là tập kết luận chính; `dev` chỉ dùng để kiểm tra harness và phát hiện lỗi.
- Ghi cả chất lượng và tác động runtime: latency, model calls, tool calls, token/cost, 429 và error taxonomy.
- Bất kỳ arm nào làm tăng S0/S1 hoặc vi phạm quyền đều bị loại dù điểm tổng tăng.

## 2. Phân kỳ Phase 4A/4B

- **Phase 4A — Baseline + decision:** xây harness/fixture/grader/qrels/telemetry, chạy A0 quality baseline và load/cost subset khi preflight đạt. Không chạy embedding/reranker upgrade trong 4A.
- **Phase 4B — Targeted ablation:** chỉ mở arm được chọn bởi lỗi baseline và có acceptance evidence; mỗi arm có `arm_id`, config hash, raw artifact và decision record riêng.
- Chưa có F01/F02/F09 và M01/M02/M03/M05/M06 thì chỉ được gọi `READY FOR HARNESS/PREFLIGHT`; không trình bày arm thiết kế như kết quả Chương 4.

## 3. Arms nền tảng

| Arm | Thành phần | Cấu hình | Trạng thái |
|---|---|---|---|
| A0 | Full current system quality baseline | Routing + guardrail + hybrid retrieval + **application Semantic Cache OFF**, ToolCache/DB state theo manifest + bounded history | **Phase 4A bắt buộc; cache OFF là canonical quality protocol** |
| A1 | Cache contribution | A0 so với Semantic Cache ON; warm-up/reset/population được pin riêng, không trộn quality sample | Phase 4B sau cache/config assertions |
| A2 | Retrieval contribution | Không dùng RAG cho nhóm policy, buộc abstain/clarify | Đo tác động của evidence đối với policy; không dùng như production mode |
| A3 | History contribution | Multi-turn sidecar có prior turns; cửa sổ history `0` so với bounded `6` | Phase 4B; **blocked** nếu chưa có prior-turn fixture |
| A4 | Provider contribution | Cùng protocol, so sánh api-vllm-selfhost-v1 và api-reference-v1 | So sánh model/provider, không phải component isolation tuyệt đối |

Các arm A1–A3 chỉ được chạy nếu trace chứng minh component đã thực sự được bật/tắt theo manifest. Không mô phỏng bằng cách đổi nhãn kết quả. Cache warm/cold và application cache/tool cache phải là các mode khác nhau, không gộp vào A0.

## 4. Arms retrieval nâng cấp (chỉ khi baseline cần)

| Arm | Thay đổi duy nhất | Metric chính |
|---|---|---|
| R0 | `feature-hash-v1` hiện tại | Recall@k, MRR/nDCG, claim support, latency |
| R1 | `paraphrase-multilingual-MiniLM-L12-v2` | Cùng qrels/corpus; version và dimension riêng |
| R2 | `multilingual-e5-base` với `query:`/`passage:` | Cùng qrels; cần index/vector dimension 768 riêng |
| R3 | R0/R1/R2 + neural reranker | nDCG/MRR sau rerank và p95 latency/cost |

R1–R3 không được coi là đã triển khai. Chỉ chạy sau khi có qrels tiếng Việt và manifest model revision. Không trộn vector giữa các model; E5 không ghi đè trực tiếp cột vector 384 hiện tại nếu chưa có thiết kế index/migration.

## 5. Arms workflow và safety

Các thử nghiệm dưới đây là **offline harness hoặc simulator**, tuyệt đối không đưa vào endpoint phục vụ thật:

- W0: routing hiện tại so với oracle intent để ước lượng phần lỗi do routing.
- W1: có/không có clarification policy trong các ca thiếu mã đơn.
- W2: citation validation bật/tắt để đo tỷ lệ unsupported claim; arm tắt chỉ dùng để chứng minh đóng góp, không dùng làm candidate.
- W3: tool result thật so với fixture bị thiếu/stale để đo khả năng abstain và error propagation.

Không được tắt `owner_scope`, confirmation, mutation guard hoặc secret redaction chỉ để tăng điểm. Các guardrail này là điều kiện hệ thống, không phải biến tối ưu tự do.

## 6. Protocol và phân tích

Với mỗi arm:

1. Chạy toàn bộ 150 `dev` để kiểm tra harness, không tuning trên held-out; ghi `scenario_family` overlap.
2. Đóng băng cấu hình, reset state và chạy 100 `held_out` theo canonical cache/retry protocol; repetition/workload/duration/cap phải có trong manifest.
3. Với A3, nạp prior-turn fixture trước khi so history; với A2/W2, dùng expected rubric riêng cho arm abstain/no-evidence.
4. Ghi per-attempt raw result, fixture/identity ref, retrieval record, grading/claim labels, error taxonomy và telemetry.
5. Tính paired delta theo case/template cluster; bootstrap CI 95%, effect size và p-value khi phù hợp.
6. Kiểm tra severe safety regression trước khi đọc điểm trung bình.
7. Ghi cost/latency trade-off và quyết định `adopt`, `reject`, `needs_more_data`; unrun/blocked arm không xuất hiện trong scorecard.

Primary metrics khuyến nghị: `held_out_outcome_success`, `forbidden_tool_rate`, `unsupported_claim_rate`, `Recall@5` (RAG), `P95/P99 E2E latency`. Secondary: MRR/nDCG, abstention quality, model calls, cost/case, 429 rate.

## 7. Acceptance checks và decision rule

Một ablation chỉ được coi là đã chạy khi có đủ:

- `manifest.json` ghi arm_id, đúng một biến thay đổi, cache/retry/provider mode và expected rubric;
- trace assertion chứng minh component ON/OFF; raw attempts không bị ghi đè;
- qrels/claim labels/fixture refs phù hợp với arm; A3 có prior turns;
- metrics có denominator, cluster unit và safety veto; artifact được validator kiểm tra.

Một arm chỉ được đề xuất thay baseline khi đồng thời:

- Tăng primary quality metric với CI/paired effect phù hợp hoặc giảm lỗi mục tiêu đã định trước.
- Không làm tăng S0/S1, forbidden tool hoặc privacy violation.
- Latency/cost tăng nằm trong ngân sách đã chấp nhận hoặc có lợi ích chất lượng rõ ràng.
- Có manifest và raw artifacts đủ để tái lập.

Nếu chất lượng tăng nhưng grounding/safety giảm, giữ A0 và mở issue nghiên cứu; không merge theo điểm trung bình.

Các arm R1–R3, W0–W3 và A1–A4 là **candidate design/backlog** cho tới khi acceptance evidence được lưu. Không ghi `BASELINE ACCEPTED` hoặc `READY FOR MEASUREMENT` chỉ từ việc hoàn thành văn bản.

