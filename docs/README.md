# RetailOps documentation

Đây là điểm vào duy nhất của bộ tài liệu. Đọc theo câu hỏi bạn cần trả lời:

## Workstream hiện hành

- [Phase 5 — Identity, Sales Simulator và Complaint E2E](phase5/README.md)
- [Phase 4 execution handoff](phase4/PHASE_4_EXECUTION_HANDOFF.md)

| Muốn hiểu | Mở |
|---|---|
| Hệ thống là gì và các thành phần nằm ở đâu | [Project overview](00_OVERVIEW/PROJECT_OVERVIEW.md) → [Codebase map](00_OVERVIEW/CODEBASE_MAP.md) |
| Model, agent, prompt và RAG chạy thế nào | [AI system index](01_AI_SYSTEM/README.md) |
| Dữ liệu, hash và công thức chỉ số | [Data contracts](02_DATA_CONTRACTS/DATA_CONTRACT.md) |
| Quy trình nghiệm thu và thí nghiệm | [Evaluation protocol](03_EVALUATION/EVALUATION_PROTOCOL.md) |
| Trạng thái nghiệm thu toàn dự án | [Acceptance matrix](03_EVALUATION/ACCEPTANCE_MATRIX.md) |
| CI, deploy, rollback và rủi ro | [Operations runbook](04_OPERATIONS/RUNBOOK.md) |
| Quyết định và thuật ngữ viết tắt | [Decision log](04_OPERATIONS/DECISION_LOG.md) · [Glossary](00_OVERVIEW/PROJECT_GLOSSARY.md) |

## Năm tầng

1. [00_OVERVIEW](00_OVERVIEW/PROJECT_OVERVIEW.md) — bối cảnh, bản đồ code và glossary.
2. [01_AI_SYSTEM](01_AI_SYSTEM/README.md) — model, agent, prompt, RAG, safety và reproducibility.
3. [02_DATA_CONTRACTS](02_DATA_CONTRACTS/DATA_CONTRACT.md) — dữ liệu đầu vào và metric contract.
4. [03_EVALUATION](03_EVALUATION/EVALUATION_PROTOCOL.md) — protocol, gate và experiment log.
5. [04_OPERATIONS](04_OPERATIONS/RUNBOOK.md) — CI/CD, vận hành, risk và decision records.

`_digest/` là lớp trích xuất có citation để các public docs tham chiếu. `phase4/` giữ hồ sơ nghiệm thu chi tiết. [Audit file classification](_audit/FILE_CLASSIFICATION.md) là inventory, không phải tài liệu kiến trúc.

## Mốc nguồn

Các digest giữ snapshot `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`. [G2 evidence](phase5/PHASE_5_G2_EVIDENCE_8868c5c.md) ghi PASS trên `8868c5c`; P5-B đã merge/deploy tại `80f5156`. P5-C đã merge tại `a34b479`; deploy workflow rerun `38335308481`, job `115122302562` SUCCESS. Snapshot EC2 `2026-10-13T04:36:57Z` xác nhận runtime; hai smoke report PASS và đóng P5-K1. **Bước kế tiếp là candidate CI cho P5-D trên cùng workstream SHA; CI phải chạy test PostgreSQL/pgvector không bị skip, rồi dừng để Codex xác minh.** D-R2/D-R3 đã qua implementation re-review; P5-K7/K8 chưa được accepted. Live Google-customer E2E cần P5-K3 OAuth trước. Operational smoke không cấp G5; xem [current status](CURRENT_PROJECT_STATUS.md) và [acceptance matrix](03_EVALUATION/ACCEPTANCE_MATRIX.md).
