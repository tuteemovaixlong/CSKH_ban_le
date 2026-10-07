# Phase 4 — Threats to Validity

> Tài liệu này ghi rõ vì sao kết quả trên benchmark 250 ca có thể bị lệch và mức độ ngoại suy được phép. Đây là phần giới hạn phương pháp, không phải bằng chứng production readiness.

> **Trạng thái:** `READY FOR HARNESS/PREFLIGHT`. Các mitigation có dấu “artifact bắt buộc” là backlog; chưa được coi là đã thu thập.

## 1. Internal validity

| Threat | Cơ chế gây lệch | Mitigation bắt buộc | Residual risk |
|---|---|---|---|
| Data leakage | Prompt, qrels hoặc expected outcome lọt vào runtime/grader | Tách input/evidence/grader; kiểm tra secret và leakage audit | Vẫn có thể có mẫu gần nhau |
| Grader bias | Người chấm ưu ái câu trả lời dài hoặc một provider | Rubric mù provider, adjudication và inter-rater agreement | Rubric vẫn có chủ quan |
| Frozen-set overfitting | Tối ưu theo 250 ca khiến điểm tăng giả | Dùng held_out 100 ca; giữ một tập mới cho kiểm tra sau | Tập mới chưa đại diện mọi traffic |
| Split imbalance | Category hoặc độ khó phân bố không đều | Báo cáo category × split, không chỉ macro average | Dev/held_out đã cố định 150/100 |
| Provider/model drift | API/model thay đổi giữa các run | Pin digest/revision, lưu timestamp và manifest | API ngoài vẫn có drift |
| Prompt/config drift | Prompt, tools, temperature hoặc retry khác nhau | Version hóa prompt/protocol/config; reject manifest thiếu | Khó kiểm soát thay đổi ngoài repo |
| Randomness | Sampling tạo khác biệt giữa run | Seed cố định nếu provider hỗ trợ; lặp run và CI | Một số API không deterministic |
| Cache contamination | Warm cache làm giảm latency hoặc thay đổi output | Chạy cold/warm riêng; reset cache giữa arms | Reset không mô phỏng mọi production pattern |
| Retry/timeout policy | Retry biến lỗi thành pass hoặc kéo dài latency | Ghi từng attempt; báo first failure và final outcome | Khó phân biệt retry hữu ích/harmful |
| Instrumentation error | Missing/false telemetry làm sai metric | Contract tests, đối chiếu raw trace với server log | Log có thể thiếu khi crash |
| Concurrency interference | Các ca dùng chung DB/cache/gate | Isolate tenant/session; ghi queue/cache state; lặp tải | Không bao phủ mọi interleaving |
| Seed/demo dependency | Dữ liệu fixture khác dữ liệu thật | Ghi seed version và DB snapshot; không gọi seed là live | Benchmark vẫn chủ yếu synthetic |
| Missing/skipped cases | Bỏ timeout/skip làm điểm cao giả | Mọi ID phải có record; skip có lý do và mẫu số rõ | Một số external integration không chạy local |
| Label ambiguity | Expected outcome có thể có nhiều câu trả lời hợp lệ | Rubric theo invariant/tool/safety; adjudicate | Ngôn ngữ tự nhiên vẫn mơ hồ |
| Multiple comparisons | Nhiều metric/arms tạo p-value giả | Paired CI, effect size, correction hoặc pre-register primary metrics | Có thể giảm power |
| Template/group leakage | Dev và held-out chia sẻ template/scenario family | Sidecar `scenario_family`, overlap report và grouped holdout bổ sung (artifact bắt buộc) | Frozen split có thể vẫn tương quan |
| Held-out exposure | Held-out đã được dùng để tune hoặc xem trước | Audit log commit/annotation, declaration of exposure và không tune lại trên held-out | Không thể khôi phục tính mới nếu đã lộ |
| Cluster dependence | Nhiều run/retry/burst trên cùng case hoặc worker | Bootstrap theo case/template/run block; ghi repetition/workload cap | CI rộng hơn và power thấp hơn |
| Selective availability | Skip theo môi trường làm mẫu số đẹp hơn | `skip_reason`, scheduled-vs-graded denominator và lane readiness riêng | Kết quả vẫn lệch về lane chạy được |
| Fixture/identity mismatch | Case chạy với tenant/principal/order không đúng | Immutable fixture map, preflight owner assertion và negative-owner pair (artifact bắt buộc) | Fixture chưa đại diện traffic thật |
| Grader/schema failure | Grader hoặc writer loại/đổi kết quả | Adversarial grader tests, append-only writer round-trip, schema/checksum validation | Có thể còn lỗi annotation |
| Quota/budget stopping | App quota hoặc cost cap dừng giữa run | Quota ledger, budget stop event, không gán missing là quality pass | Run không hoàn tất vẫn không kết luận full set |

## 2. External validity

| Threat | Giới hạn ngoại suy | Cách ghi trong báo cáo |
|---|---|---|
| Ngôn ngữ | 250 ca tập trung CSKH TMĐT tiếng Việt, không đại diện mọi dialect/kênh | Chỉ kết luận cho miền nhiệm vụ và ngôn ngữ đã đo |
| Synthetic scenarios | Câu sinh/biên soạn không thay thế traffic thật | Gọi là benchmark tác nghiệp, không gọi là production traffic |
| Single business context | Policy, catalog, order state của một miền cửa hàng | Không ngoại suy sang ngành khác hoặc policy khác |
| Provider mismatch | api-vllm-selfhost-v1 và api-reference-v1 có giao thức/cost khác | So sánh đúng cấu hình, không suy ra model “tốt nhất” tuyệt đối |
| No live POS/OMS proof | DB nội bộ không chứng minh đồng bộ hệ thống vận hành thật | Tách “business DB contract” khỏi “live integration” |
| No broad multimodal set | Ảnh/OCR/defect scanning chưa có bộ nhãn đủ lớn | Không kết luận vision/OCR production quality |
| Hardware locality | Một EC2/GPU, tải và network riêng | Báo cáo loại máy, region, network và không ngoại suy cost toàn AWS |
| Short run horizon | Run ngắn không thấy drift, memory leak, incident | Cần soak/long-run riêng trước pilot |
| Human factors | Không đo staff response time và handoff adoption | Không kết luận về hiệu quả vận hành của nhân viên |
| Feature-scope mismatch | Gắn gate OCR/distributed vào deployment text-only/single-instance | Ghi topology/feature scope trong manifest; chỉ áp dụng gate tương ứng | Không ngoại suy sang capability ngoài phạm vi |

## 3. Claim policy

Được phép viết:

- “Trong benchmark 250 ca đã đóng băng, cấu hình X đạt … trên held-out …”.
- “Ở điều kiện tải Y trên môi trường Z, P99 quan sát được …”.
- “Kết quả gợi ý component A đáng thử nghiệm tiếp; chưa đủ để khẳng định production.”

Không được viết nếu chưa có bằng chứng tương ứng:

- “Đạt chuẩn ngành”, “production-ready”, “real-time POS/OMS” hoặc “an toàn tuyệt đối”.
- “Reranker/embedding mới chắc chắn tốt hơn” khi chưa có qrels và paired comparison.
- “OCR nhận diện lỗi chính xác” khi chưa có bộ ảnh có nhãn và field-level metric.
- “Model tổng quát” chỉ vì pass các ca trong benchmark CSKH.

## 4. Tối thiểu cần nêu trong luận văn

Chương 4 phải có một tiểu mục giới hạn, nêu rõ benchmark là bằng chứng L2/L3 trong miền chọn mẫu. Các threat còn residual phải được giữ trong bảng, không xóa vì kết quả đẹp. Kết luận nâng cấp chỉ được đưa ra sau khi xem đồng thời chất lượng, safety, latency, cost và khả năng tái lập.

## 5. Liên kết threat với artifact và decision gate

| Nhóm threat | Artifact kiểm chứng | Nếu thiếu artifact |
|---|---|---|
| Leakage/independence | `scenario_family.jsonl`, overlap report, exposure declaration | Chỉ báo cáo benchmark nội bộ; không gọi held-out là bằng chứng tổng quát hóa |
| Fixture/identity | `fixture_manifest.json`, setup log, owner-scope assertions | Block quality measurement cho các ca cần business data |
| Grader/labels | `grading.jsonl`, qrels/claim-label hash, adjudication log | Chỉ được báo harness/preflight; không công bố quality score |
| Retry/cache/telemetry | per-attempt raw JSONL, cache/config assertion, server trace | Chỉ báo reliability/incomplete; không gộp first và eventual outcome |
| Statistical dependence | analysis manifest, cluster unit, repetition/workload cap | `INCONCLUSIVE` cho CI/significance chưa đủ cơ sở |
| Feature/deployment scope | run manifest ghi topology + enabled features | Không áp dụng production gate ngoài phạm vi; tách kết luận text-only/single-instance |

Không được xóa threat chỉ vì mitigation đã được viết trong plan. Chỉ chuyển residual risk khi artifact tương ứng đã tồn tại và validator kiểm được.

