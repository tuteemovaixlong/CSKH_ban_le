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

Các digest giữ snapshot `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`. [G2 evidence](phase5/PHASE_5_G2_EVIDENCE_8868c5c.md) ghi PASS trên `8868c5c`; P5-A merge `dd0947aad3a2dc8884710c8f6c609f42b67417bd`. Bước kế tiếp là [P5-B](phase5/PHASE_5_EXECUTION_HANDOFF.md); operational smoke PASS không cấp G5.
