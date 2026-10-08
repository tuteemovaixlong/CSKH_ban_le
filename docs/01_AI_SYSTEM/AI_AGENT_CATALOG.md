# AI Agent Catalog

## Supervisor và routing

Supervisor là node đầu tiên sau START, dùng guardrails, sentiment, topic và context để đặt `intent`/`next_worker` ([`graph.py#L24-L25`](../../retailops/workflow/graph.py#L24) [`supervisor.py#L82-L89`](../../retailops/workflow/supervisor.py#L82)). Graph có bốn worker được route: `order_agent`, `policy_agent`, `dispute_agent`, `witty_agent` ([`graph.py#L53-L65`](../../retailops/workflow/graph.py#L53)). `read_worker` là helper runtime dùng chung, không phải worker route thứ năm ([`order_agent.py#L5-L6`](../../retailops/workflow/subagents/order_agent.py#L5)).

| Agent | Nhiệm vụ | Tool scope / bằng chứng |
|---|---|---|
| Order | Tra cứu đơn, sản phẩm và vận chuyển; không xác nhận hành động chưa xảy ra | [`order_agent.py#L7-L50`](../../retailops/workflow/subagents/order_agent.py#L7) · allowlist [`order_agent.py#L52-L53`](../../retailops/workflow/subagents/order_agent.py#L52) |
| Policy | Tra cứu chính sách tenant bằng evidence và citation | [`policy_agent.py#L5-L10`](../../retailops/workflow/subagents/policy_agent.py#L5) |
| Dispute | Xử lý đổi/hủy/khiếu nại theo proposal và human approval | [`dispute_agent.py#L13-L23`](../../retailops/workflow/subagents/dispute_agent.py#L13) |
| Witty | Câu hỏi chung/chitchat, không dùng tool | [`witty_agent.py#L12-L22`](../../retailops/workflow/subagents/witty_agent.py#L12) [`witty_agent.py#L59-L81`](../../retailops/workflow/subagents/witty_agent.py#L59) |

## Shared runtime

`read_worker` truyền prompt riêng, giữ history, gọi model tối đa theo protocol budget, kiểm tra tool scope, ghi trace và renderer fallback khi đã có records an toàn ([`read_worker.py#L20-L27`](../../retailops/workflow/subagents/read_worker.py#L20) [`read_worker.py#L164-L216`](../../retailops/workflow/subagents/read_worker.py#L164)).

## State and approval

State gồm message/fresh/trace, intent/worker history, sentiment/strict mode, proposal và human flags ([`state.py#L28-L50`](../../retailops/workflow/state.py#L28)). Checkpoint saver giới hạn thread theo server run ID và tenant lease ([`checkpoints.py#L19-L39`](../../retailops/workflow/checkpoints.py#L19)). Chi tiết MCP/tool ở [TOOLS digest](../_digest/code/TOOLS.digest).

## Unknown / Unverified

- [UNVERIFIED] Prompt/model thực tế của deployment đang chạy và tỷ lệ route production.
- [UNVERIFIED] Approval graph có được bật trên mọi deployment hay không; source chỉ chứng minh module tồn tại.
