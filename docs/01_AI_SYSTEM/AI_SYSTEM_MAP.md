# AI System Map

Trạng thái nguồn: code digest được tạo từ SHA `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`; merged SHA sau G2 là `[UNVERIFIED]`. Tài liệu này mô tả những gì code hiện chỉ ra, không suy ra deployment.

## Luồng xử lý

1. API tạo state gồm message, trace, context đã bind và thông tin model; graph LangGraph bắt đầu ở `supervisor` ([AGENTS digest](../_digest/code/AGENTS.digest), [`graph.py#L87-L147`](../../retailops/workflow/graph.py#L87)).
2. Supervisor đọc tin nhắn gần nhất, context, lịch sử, attachment và guardrails rồi gán `next_worker` ([`supervisor.py#L82-L89`](../../retailops/workflow/supervisor.py#L82)).
3. Graph route đến một trong bốn worker: order, policy, dispute hoặc witty; nhánh direct/human kết thúc graph ([`graph.py#L53-L82`](../../retailops/workflow/graph.py#L53)).
4. Worker gọi gateway với prompt riêng và allowlist tool. `read_worker` xác thực tool, ghi trace, giới hạn số bước và có renderer dự phòng dựa trên dữ kiện đã lấy ([`read_worker.py#L149-L188`](../../retailops/workflow/subagents/read_worker.py#L149)).
5. Dữ kiện knowledge đi qua retrieval repository và citation validator; citation thiếu hoặc sai làm lượt trả lời fail closed ([`agent.py#L71-L79`](../../retailops/workflow/agent.py#L71)). Chi tiết RAG nằm ở `../_digest/code/RAG.digest` nếu đã được tạo.
6. State được checkpoint theo run/tenant fence khi saver được bật ([`checkpoints.py#L19-L39`](../../retailops/workflow/checkpoints.py#L19)).

## Giới hạn AI đã thấy trong code

- Native protocol giới hạn 4 model calls và 8 tool calls; request có seed 42 và temperature 0.2 ([`agent_protocol.py#L6-L10`](../../agent_protocol.py#L6) [`agent_protocol.py#L359-L391`](../../agent_protocol.py#L359)).
- Worker scope được kiểm tra trước khi thực thi; tool ngoài scope ghi lỗi và không chạy ([`read_worker.py#L224-L256`](../../retailops/workflow/subagents/read_worker.py#L224)).
- Không có bằng chứng từ các file này về model/provider đang phục vụ production; xem `MODELS.digest` và đánh dấu `[UNVERIFIED]`.

## Đọc tiếp

- [AGENTS digest](../_digest/code/AGENTS.digest) · [TOOLS digest](../_digest/code/TOOLS.digest) · [MODELS digest](../_digest/code/MODELS.digest)
- [Model card](AI_MODEL_CARD.md) · [Agent catalog](AI_AGENT_CATALOG.md) · [Prompt catalog](AI_PROMPT_CATALOG.md)
