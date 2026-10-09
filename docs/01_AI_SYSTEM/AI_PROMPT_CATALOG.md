# AI Prompt Catalog

Tài liệu này trỏ đến prompt literal trong code và phân biệt prompt runtime với prompt đánh giá.

## Runtime prompts

| Prompt | Nội dung được xác nhận | Source |
|---|---|---|
| RetailOps system | Tool-first cho dữ kiện cửa hàng, cấm đoán và secret leakage | [`agent_protocol.py#L11-L60`](../../agent_protocol.py#L11) |
| General | Trợ lý tiếng Việt tool-free, không claim live facts/KB | [`agent_protocol.py#L63-L78`](../../agent_protocol.py#L63) |
| Order | Quy tắc ID, ownership, product/order separation, missing-field honesty | [`order_agent.py#L7-L50`](../../retailops/workflow/subagents/order_agent.py#L7) |
| Policy | Chỉ excerpt từ `search_knowledge` với `[KB:...]` | [`policy_agent.py#L5-L10`](../../retailops/workflow/subagents/policy_agent.py#L5) |
| Witty | Trả lời 1–2 câu và pivot sang shop; không bịa thời tiết | [`witty_agent.py#L12-L22`](../../retailops/workflow/subagents/witty_agent.py#L12) |
| Dispute | Proposal, kiểm tra target và human approval | [`dispute_agent.py#L13-L23`](../../retailops/workflow/subagents/dispute_agent.py#L13) |
| MCP client prompt | SOP prompt được đăng ký cho MCP clients | [`retailops_mcp_server.py#L1324-L1335`](../../retailops_mcp_server.py#L1324) |

## Tool descriptions and dynamic composition

Native tool descriptions nằm trong `TOOLS`; `scoped_tools` tạo danh sách theo allowlist ([`agent_protocol.py#L83-L110`](../../agent_protocol.py#L83) [`agent_protocol.py#L345-L356`](../../agent_protocol.py#L345)). Prompt worker được ghép với history trong `worker_messages` ([`read_worker.py#L20-L27`](../../retailops/workflow/subagents/read_worker.py#L20)).

## Evaluation prompts

- `evals/prompts/RetailOps_MASTER_PROMPT.txt` và `evals/prompts/RETAILOPS_DISPATCH_COMMANDS.md` là nguồn prompt đánh giá trong phạm vi digest; nội dung chính xác cần đọc theo file hiện tại ([PROMPTS digest](../_digest/code/PROMPTS.digest)).
- Không dùng prompt đánh giá để khẳng định runtime deployment nếu chưa có bằng chứng.

## Unknown / Unverified

- [UNVERIFIED] Nội dung cell notebook `colab_agent.ipynb` và prompt evaluation chưa được line-address đầy đủ trong digest.
- [UNVERIFIED] Prompt sau khi provider adapter biến đổi nếu deployment dùng custom endpoint.
