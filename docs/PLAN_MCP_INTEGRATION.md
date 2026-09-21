---
trạng_thái: STANDALONE IMPLEMENTED / PRODUCTION WIRING PENDING
mã_kế_hoạch: PLAN_MCP_INTEGRATION
nguồn_sự_thật:
  - tests/test_mcp_protocol.py
  - retailops_mcp_server.py
  - retailops/workflow/mcp_client.py
  - retailops/workflow/agent.py
  - retailops/workflow/graph.py
cập_nhật_cuối: 2026-09-21
---

# Kế hoạch Tích hợp MCP Server (Model Context Protocol Integration Plan)

> [!IMPORTANT]
> **Hiện trạng Triển khai Thực tế (Tháng 09/2026):**  
> 1. **Standalone Server & Adapter ĐÃ HOÀN TẤT**: Máy chủ giao thức độc lập [retailops_mcp_server.py](../retailops_mcp_server.py) (hỗ trợ cả stdio và SSE port 8002) cùng client adapter [retailops/workflow/mcp_client.py](../retailops/workflow/mcp_client.py) đã được hiện thực và kiểm thử tự động đạt 20/20 test pass ([tests/test_mcp_protocol.py](../tests/test_mcp_protocol.py)).
> 2. **Production Pipeline Hiện Tại**: Pipeline LangGraph chính chạy trên EC2 ([retailops/workflow/agent.py](../retailops/workflow/agent.py), [retailops/workflow/graph.py](../retailops/workflow/graph.py)) đang trực tiếp sử dụng in-process `BoundTools` ([retailops_tools.py](../retailops_tools.py)) nhằm tối ưu độ trễ và giữ container tối giản (`mcp` không nằm trong `requirements-runtime.txt`). Việc chuyển toàn bộ runtime chính sang gọi qua MCP SSE server là tùy chọn kiến trúc decoupling sẵn sàng kích hoạt khi mở rộng microservices.

Tài liệu này xác định kiến trúc, lộ trình triển khai và giải pháp kỹ thuật để chuẩn hóa toàn bộ hệ thống công cụ nghiệp vụ của RetailOps theo tiêu chuẩn **Model Context Protocol (MCP)** — giao thức mở chuẩn công nghiệp do Anthropic khởi xướng.

---

## 1. Mục tiêu & Giá trị Chiến lược

1. **Chuẩn hóa Giao diện Công cụ (Standardized Tool Interface)**:
   - Cung cấp giao thức MCP chuẩn mở, giúp các agent bên ngoài độc lập hoàn toàn với việc triển khai chi tiết của từng công cụ nội bộ.
2. **Tách rời Hệ thống (Decoupled Microservice Architecture)**:
   - Cho phép chạy các kết nối nghiệp vụ (Kho hàng ERP KiotViet/Sapo, Bưu cục GHN/GHTK, Cổng thanh toán, Tổng đài Zalo/Telegram) ra một tiến trình microservice riêng biệt (**RetailOps MCP Server**).
3. **Khả năng Tái sử dụng Đa Nền tảng (Two-way Interoperability)**:
   - **RetailOps as MCP Server**: Cho phép các nền tảng AI khác (Claude Desktop, Cursor, Antigravity IDE, n8n, LangChain, CrewAI) cắm trực tiếp vào hệ sinh thái RetailOps qua stdio hoặc SSE.
   - **RetailOps as MCP Client**: Cho phép LangGraph Supervisor nạp công cụ qua [retailops/workflow/mcp_client.py](../retailops/workflow/mcp_client.py) khi cần tích hợp thêm server bên ngoài.

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

    subgraph Runtime Direct Path
        LangGraph -->|In-process Direct Call (Default Runtime)| BoundTools["BoundTools (retailops_tools.py)"]
    end

    subgraph MCP Microservice Layer
        LangGraph -.->|Optional MCP Client Adapter (mcp_client.py)| MCPServer["RetailOps MCP Server (FastMCP :8002)"]
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
  * **SSE (Server-Sent Events) qua HTTP**: Sử dụng cho microservices nội bộ (port `8002/sse`).
  * **stdio (Standard I/O)**: Sử dụng cho chạy local CLI, debug, hoặc cắm vào desktop client (như Claude Desktop / Cursor).

### 3.2. Danh mục Công cụ Chuyển đổi (MCP Tools Specification)

Toàn bộ công cụ nghiệp vụ trong [retailops_tools.py](../retailops_tools.py) được expose qua MCP:

| Tên MCP Tool | Tham số đầu vào | Mô tả chức năng | Kết nối thực tế |
| :--- | :--- | :--- | :--- |
| `track_shipment` | `order_id: str` | Tra cứu trạng thái vận đơn, vị trí bưu kiện, lịch sử giao vận | API Giao Hàng Nhanh (GHN) / GHTK |
| `check_inventory` | `sku: str, branch_id: str = "all"` | Kiểm tra tồn kho khả dụng theo mã sản phẩm và chi nhánh | API KiotViet / Sapo ERP |
| `search_knowledge`| `query: str, top_k: int = 3` | Tìm kiếm ngữ nghĩa chính sách đổi trả, bảo hành | PostgreSQL pgvector HNSW search |
| `cancel_order` | `order_id: str, reason: str, confirm_key: str = None` | Khởi tạo đề xuất hủy đơn có xác thực 2 bước an toàn | Business Store / OMS nội bộ |
| `request_human_support` | `customer_id: str, urgency: str, summary: str` | Bắn thông báo chuyển giao phiên sang tổng đài viên | Webhook Telegram CSKH / Zalo OA |

---

## 4. Hiện thực Máy chủ Độc lập (`retailops_mcp_server.py`)

File máy chủ hoàn chỉnh đã được triển khai tại [retailops_mcp_server.py](../retailops_mcp_server.py) và cấu hình tại [mcp_config.json](../mcp_config.json).

```python
"""RetailOps Enterprise MCP Server — Standalone Model Context Protocol Provider."""
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("RetailOps-Enterprise-Tools")

# Exposes: track_shipment, check_inventory, search_knowledge,
# cancel_order, request_human_support, search_product_specs, etc.
```

---

## 5. Hiện trạng Tích hợp vào LangGraph Agent

1. **Client Adapter Sẵn sàng**: [retailops/workflow/mcp_client.py](../retailops/workflow/mcp_client.py) cung cấp các hàm chuyển đổi MCP tools thành LangChain/LangGraph tools.
2. **Production Runtime Hiện tại**: Trong [retailops/workflow/agent.py](../retailops/workflow/agent.py) và [retailops/workflow/graph.py](../retailops/workflow/graph.py), agent bind trực tiếp các công cụ Python nội bộ từ `retailops_tools.py` để đạt độ trễ thấp nhất (<5ms so với mạng HTTP/SSE) và hạn chế phụ thuộc thư viện bên thứ 3 trong production Docker container.
3. **Kế hoạch Chuyển đổi**: Khi cần mở rộng phân tán máy chủ công cụ ra cụm riêng, chỉ cần bật cờ `USE_MCP_TOOLS=true` để nạp tools qua adapter `mcp_client.py`.

---

## 6. Trạng thái Triển khai (Checklist)

- [x] **Bước 1**: Xây dựng máy chủ độc lập [retailops_mcp_server.py](../retailops_mcp_server.py) tương thích FastMCP SDK.
- [x] **Bước 2**: Đóng gói đầy đủ 10 công cụ nghiệp vụ TMĐT, 3 resources RAG policies/catalog, 1 prompt template và tính năng tra cứu thông số kỹ thuật bên ngoài có rào chắn an toàn (`search_product_specs`).
- [x] **Bước 3**: Hỗ trợ truyền tải kép: `stdio` (cho Claude Desktop, Cursor, Antigravity IDE) và `sse` (port 8002 cho microservices/n8n), kèm cấu hình [mcp_config.json](../mcp_config.json).
- [x] **Bước 4**: Xây dựng adapter [retailops/workflow/mcp_client.py](../retailops/workflow/mcp_client.py) và bộ kiểm thử tự động toàn diện [tests/test_mcp_protocol.py](../tests/test_mcp_protocol.py) (20/20 test pass).
- [ ] **Bước 5 (Tùy chọn tương lai)**: Đưa `mcp` vào `requirements-runtime.txt` và chuyển toàn bộ runtime chính trong `graph.py` sang gọi qua SSE adapter khi triển khai cụm microservices đa server.

