# Project glossary

Các thuật ngữ dưới đây được chuẩn hóa theo source và hồ sơ Phase 4. Chi tiết quyết định nằm trong [DECISIONS digest](../_digest/meta/DECISIONS.digest) và [ACRONYMS digest](../_digest/meta/ACRONYMS.digest).

| Nhóm | Thuật ngữ | Nghĩa ngắn |
|---|---|---|
| R | R10–R13 | Các yêu cầu thiết kế/evidence cho telemetry, reproducibility, safety và deployment guard. |
| G | G0–G7 | Các cổng từ chuẩn bị harness đến measurement; G5 là measurement readiness. |
| S | S0–S3 | Mức severity của failure/safety taxonomy. |
| K | K1–K8 | Checklist nghiệm thu frozen harness; không tự thêm K9. |
| C | C1–C6 | Sáu contract checks dùng cùng K8. |
| H/F/B/N/L | H, F, B, N, L | Nhãn finding, blocker, boundary hoặc backlog trong các review lịch sử; xem source cụ thể trước khi dùng. |
| P5 | P5-01… | Backlog Phase 5 cho phần deferred ngoài acceptance v1. |
| AI | model, inference, token, seed | Thành phần và tham số của đường suy luận; giá trị phải lấy từ [model card](../01_AI_SYSTEM/AI_MODEL_CARD.md). |
| Provider | Custom/API/OpenRouter/Anthropic/Google | Đường kết nối model được source hỗ trợ; không đồng nghĩa deployment hiện hành. |
| Workflow | supervisor, worker, tool, checkpoint | Các nút điều phối, worker chuyên môn, tool có quyền và state resume. |
| RAG | chunk, embedding, retrieval, citation | Pipeline knowledge từ tài liệu nguồn đến bằng chứng trong câu trả lời. |
| Data | baseline, benchmark, qrels, fixture | Dữ liệu evaluation và expected evidence. |
| Contract | schema, validator, gate | Điều kiện máy kiểm được để reject bundle hoặc chặn hành động. |
| Evidence | digest, packet, artifact | Dấu vết có source, hash và thời điểm; không thay thế model-quality measurement. |
