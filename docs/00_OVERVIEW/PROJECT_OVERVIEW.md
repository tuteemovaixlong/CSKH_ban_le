# Project overview

RetailOps là hệ thống CSKH bán lẻ có web, identity/session, nghiệp vụ đơn hàng và một workflow đa agent. Người dùng gửi yêu cầu qua HTTP; application bind tenant/customer/role, điều phối agent, gọi model và tool, rồi lưu conversation/checkpoint và kết quả nghiệp vụ.

Repo hiện cũng có luồng Phase 5 mô phỏng event bán hàng, ánh xạ khách hàng ngoài hệ thống vào customer RetailOps, rồi kiểm thử complaint/proposal/confirmation trên cùng identity. P5-C đã merge/deploy theo project status; P5-D đang ở candidate-CI gate: test PostgreSQL/pgvector chưa có kết quả CI không-skip, nên P5-K7/K8 chưa accepted. Đây là tiến độ workstream, không phải tuyên bố mọi capability đã sẵn sàng live.

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

## Trạng thái và giới hạn bằng chứng

Engineering acceptance theo phase nằm ở [Phase 4 acceptance](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md) và [Phase 5 acceptance](../phase5/PHASE_5_ACCEPTANCE_CRITERIA.md); trạng thái gộp ở [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md). Mock replay và offline tests chứng minh plumbing/contracts, không phải chất lượng model thật. Operational smoke không chứng minh live Google OAuth hay AI-lane G4/G5. Mọi nhận định về provider đang phục vụ, chi phí, latency và readiness phải có evidence riêng hoặc đánh dấu `[UNVERIFIED]`.
