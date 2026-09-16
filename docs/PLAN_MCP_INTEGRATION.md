# Kế hoạch Tích hợp MCP Server (Model Context Protocol Integration Plan)

> [!IMPORTANT]
> **Ưu tiên Triển khai: GIAI ĐOẠN 1 (Phục vụ Khóa luận Tốt nghiệp — Bước 2)**  
> Chuẩn hóa bộ công cụ sang giao thức mở **Model Context Protocol (MCP)** là điểm nhấn công nghệ tiên tiến nhất của đề tài. Tính năng này chứng minh năng lực thiết kế hệ thống dạng **Microservices decoupled** và khả năng tương thích 2 chiều (với Claude Desktop, Cursor, n8n, LangGraph) để đưa vào **Chương 3 (Kiến trúc Hệ thống)** của Báo cáo Luận văn.

Tài liệu này xác định kiến trúc, lộ trình triển khai và giải pháp kỹ thuật để chuẩn hóa toàn bộ hệ thống công cụ nghiệp vụ của RetailOps theo tiêu chuẩn **Model Context Protocol (MCP)** — giao thức mở chuẩn công nghiệp do Anthropic khởi xướng.

---

## 1. Mục tiêu & Giá trị Chiến lược

1. **Chuẩn hóa Giao diện Công cụ (Standardized Tool Interface)**:
   - Thay thế việc gọi hàm nội bộ (In-process Function Calling) bằng giao thức MCP chuẩn mở, giúp Agent độc lập hoàn toàn với việc triển khai chi tiết của từng công cụ.
2. **Tách rời Hệ thống (Decoupled Microservice Architecture)**:
   - Tách các kết nối đến bên thứ 3 (Kho hàng ERP KiotViet/Sapo, Bưu cục GHN/GHTK, Cổng thanh toán, Tổng đài Zalo/Telegram) ra một tiến trình riêng biệt (**RetailOps MCP Server**).
3. **Khả năng Tái sử dụng Đa Nền tảng (Two-way Interoperability)**:
   - **RetailOps as MCP Server**: Cho phép các nền tảng AI khác (Claude Desktop, Cursor, Antigravity IDE, n8n, LangChain, CrewAI) cắm trực tiếp vào hệ sinh thái RetailOps để tra cứu đơn và quản lý kho.
   - **RetailOps as MCP Client**: Cho phép LangGraph Supervisor tự động khám phá (`tools/list`) và nạp thêm các công cụ mới từ bất kỳ MCP server bên ngoài nào mà không cần sửa mã nguồn lõi.

---

## 2. Kiến trúc Tổng thể MCP trong RetailOps

```mermaid
flowchart TD
    subgraph Client & UI
        WebUser["Khách hàng Chat trên Web / Widget"]
        ExternalClient["External Client (Claude Desktop / Cursor / n8n)"]
    end

    WebUser --> WebBackend["RetailOps Web Backend / API"]
    WebBackend --> LangGraph["LangGraph Supervisor & Subagents"]

    subgraph MCP Layer
        LangGraph <-->|MCP Client Protocol (SSE / HTTP)| MCPServer["RetailOps MCP Server (FastMCP :8002)"]
        ExternalClient <-->|MCP Protocol (SSE / stdio)| MCPServer
    end

    subgraph Real-world Integrations
        MCPServer <--> ShippingAPI["Bưu điện (GHN / GHTK / Viettel Post)"]
        MCPServer <--> ERPAPI["Kho hàng & Đơn (KiotViet / Sapo / Haravan)"]
        MCPServer <--> TelegramZalo["Tổng đài CSKH (Telegram Bot / Zalo OA)"]
        MCPServer <--> KnowledgeDB["PostgreSQL / pgvector (RAG Search)"]
    end
```

---

## 3. Thiết kế Kỹ thuật Chi tiết

### 3.1. Công nghệ Sử dụng
* **Thư viện**: `mcp` (Official Python SDK) kết hợp `FastMCP`.
* **Giao thức Truyền tải (Transports)**:
  * **SSE (Server-Sent Events) qua HTTP**: Sử dụng cho production trên EC2 (chạy tại cổng nội bộ `http://127.0.0.1:8002/sse`).
  * **stdio (Standard I/O)**: Sử dụng cho chạy local CLI, debug, hoặc cắm vào desktop client (như Claude Desktop / Cursor).

### 3.2. Danh mục Công cụ Chuyển đổi (MCP Tools Specification)

Toàn bộ 5 công cụ hiện tại trong [retailops_tools.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops_tools.py) sẽ được chuyển đổi sang chuẩn MCP:

| Tên MCP Tool | Tham số đầu vào | Mô tả chức năng | Kết nối thực tế |
| :--- | :--- | :--- | :--- |
| `track_shipment` | `order_id: str` | Tra cứu trạng thái vận đơn, vị trí bưu kiện, lịch sử giao vận | API Giao Hàng Nhanh (GHN) / GHTK |
| `check_inventory` | `sku: str, branch_id: str = "all"` | Kiểm tra tồn kho khả dụng theo mã sản phẩm và chi nhánh | API KiotViet / Sapo ERP |
| `search_knowledge`| `query: str, top_k: int = 3` | Tìm kiếm ngữ nghĩa chính sách đổi trả, bảo hành | PostgreSQL pgvector HNSW search |
| `cancel_order` | `order_id: str, reason: str, confirm_key: str = None` | Khởi tạo đề xuất hủy đơn có xác thực 2 bước an toàn | Business Store / OMS nội bộ |
| `request_human_support` | `customer_id: str, urgency: str, summary: str` | Bắn thông báo chuyển giao phiên sang tổng đài viên | Webhook Telegram CSKH / Zalo OA |

---

## 4. Mã nguồn Mẫu Triển khai (`retailops_mcp_server.py`)

```python
"""RetailOps Enterprise MCP Server — Standalone Model Context Protocol Provider."""
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("RetailOps-Enterprise-Tools")

@mcp.tool()
def track_shipment(order_id: str) -> dict:
    """Tra cứu trạng thái vận chuyển và lộ trình bưu kiện theo mã đơn hàng."""
    # Kết nối GHN / GHTK API
    return {
        "order_id": order_id,
        "carrier": "Giao Hàng Nhanh (GHN)",
        "status": "delivering",
        "current_hub": "Kho trung chuyển Bắc Ninh",
        "expected_delivery": "Trong ngày mai"
    }

@mcp.tool()
def check_inventory(sku: str, branch_id: str = "all") -> dict:
    """Kiểm tra số lượng tồn kho theo mã SKU sản phẩm và chi nhánh bán hàng."""
    # Kết nối KiotViet / Sapo API
    return {
        "sku": sku,
        "available_qty": 18,
        "is_in_stock": True,
        "locations": ["Kho Hà Nội (12)", "Kho TP.HCM (6)"]
    }

@mcp.tool()
def request_human_support(customer_id: str, urgency: str = "normal", summary: str = "") -> dict:
    """Bắn thông báo chuyển giao khách hàng cần hỗ trợ sang nhân viên tổng đài thật."""
    # Bắn Webhook sang Telegram CSKH hoặc Zalo OA
    # telegram_bot.send_message(f"Khách {customer_id} cần gặp CSKH: {summary}")
    return {
        "handoff_status": "forwarded",
        "assigned_channel": "Telegram-CSKH-Live",
        "queue_position": 1
    }

if __name__ == "__main__":
    port = int(os.getenv("RETAILOPS_MCP_PORT", 8002))
    mcp.run(transport="sse", port=port)
```

---

## 5. Tích hợp MCP Client vào LangGraph Agent

Trong kiến trúc [retailops/workflow/graph.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/workflow/graph.py):
1. **Dynamic Tool Fetching**: Khi khởi động, Agent kết nối tới MCP Server qua endpoint `/sse` để lấy danh sách tool mới nhất qua `tools/list`.
2. **Tool Execution Delegation**: Khi LLM sinh ra lệnh gọi tool, Agent ủy quyền thực thi thẳng sang MCP Server qua `tools/call`, nhận kết quả JSON chuẩn và đưa vào prompt tiếp theo.

---

## 6. Kế hoạch Triển khai (Checklist 4 Bước)

- [ ] **Bước 1**: Cài đặt thư viện `mcp` và tạo file [retailops_mcp_server.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops_mcp_server.py).
- [ ] **Bước 2**: Đóng gói 5 công cụ hiện tại vào MCP Server và viết test kiểm định SSE transport.
- [ ] **Bước 3**: Thêm container `retailops-mcp` vào [deploy/compose.public.yaml](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/deploy/compose.public.yaml) để chạy độc lập trên EC2 (port 8002).
- [ ] **Bước 4**: Thêm adapter MCP Client trong `retailops/workflow/` để LangGraph kết nối mượt mà với MCP Server.
