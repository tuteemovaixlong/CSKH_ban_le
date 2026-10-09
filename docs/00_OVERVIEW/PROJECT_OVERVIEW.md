# Project overview

RetailOps là hệ thống CSKH bán lẻ có web, identity/session, nghiệp vụ đơn hàng và một workflow đa agent. Người dùng gửi yêu cầu qua HTTP; application bind tenant/customer/role, điều phối agent, gọi model và tool, rồi lưu conversation/checkpoint và kết quả nghiệp vụ.

## Ai sử dụng

Khách hàng dùng web để hỏi chính sách, tra đơn và yêu cầu hỗ trợ. Nhân viên hoặc quản trị viên xử lý các thao tác cần quyền. Người phát triển dùng harness offline, CI và Ops Console để kiểm tra tính đúng của hệ thống. Model thật có thể đi qua endpoint Custom hoặc API được cấu hình; deployment model thực tế chưa được xác minh trong checkout này.

## Các lớp chính

| Lớp | Điểm vào |
|---|---|
| Web/API và identity | [`retailops/http/`](../../retailops/http/) · [`retailops/identity/`](../../retailops/identity/) |
| Nghiệp vụ và quyền | [`retailops/business/application.py`](../../retailops/business/application.py) · [`retailops/business/permissions.py`](../../retailops/business/permissions.py) |
| AI workflow | [`retailops/workflow/graph.py`](../../retailops/workflow/graph.py) · [AI system map](../01_AI_SYSTEM/AI_SYSTEM_MAP.md) |
| Knowledge/RAG | [`retailops/knowledge/`](../../retailops/knowledge/) · [RAG pipeline](../01_AI_SYSTEM/AI_RAG_PIPELINE.md) |
| Evaluation | [`evals/harness/`](../../evals/harness/) · [Evaluation protocol](../03_EVALUATION/EVALUATION_PROTOCOL.md) |
| Delivery | [`deploy/`](../../deploy/) · [Runbook](../04_OPERATIONS/RUNBOOK.md) |

## Bằng chứng và giới hạn

Engineering acceptance của harness được ghi trong [Phase 4 acceptance](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md). Mock replay là bằng chứng plumbing, không phải bằng chứng chất lượng model thật. Mọi nhận định về provider đang phục vụ production, chi phí, latency và readiness phải có evidence riêng hoặc đánh dấu `[UNVERIFIED]`.
