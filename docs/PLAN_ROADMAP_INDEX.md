# Tổng hợp Kế hoạch Chiến lược: Lộ trình Khóa luận Tốt nghiệp & Mở rộng RetailOps

Tài liệu này là chỉ mục tổng hợp (Master Roadmap) được điều chỉnh theo chiến lược: **Ưu tiên hoàn thiện hệ thống, chuẩn hóa kiến trúc, thu thập dữ liệu và báo cáo thực nghiệm phục vụ Khóa luận Tốt nghiệp trước; sau khi bảo vệ hoàn tất mới tiến hành chưng cất dữ liệu quy mô lớn và Fine-tuning mô hình chuyên biệt.**

---

## 1. Sơ đồ Phân kỳ 2 Giai đoạn (Phased Roadmap)

```mermaid
flowchart TD
    subgraph GIAI ĐOẠN 1: PHỤC VỤ KHÓA LUẬN TỐT NGHIỆP (Hiện tại - Ưu tiên hàng đầu)
        P1["1. Data Flywheel UI/API\n(Thu thập CSAT, Like/Dislike, DPO log)"]
        P6["2. MCP Server Integration\n(Chuẩn hóa Tools FastMCP :8002)"]
        P5["3. Model Benchmarking & Evals\n(Đo đạc số liệu thực nghiệm 30+ cases)"]
        P7["4. Omnichannel Social Gateways\n(Facebook Messenger & Zalo OA Webhooks)"]
        Thesis["5. Hoàn thiện Báo cáo Luận văn & Bảo vệ Khóa luận\n(Viết chương 3-4, chuẩn bị Slide & Demo live QR Code EC2)"]
        
        P1 --> P5
        P6 --> P5
        P5 --> P7
        P7 --> Thesis
    end

    subgraph GIAI ĐOẠN 2: POST-THESIS & PRODUCTION (Sau khi bảo vệ xong)
        P2["6. DeepSeek Distillation\n(Sinh 3.000–5.000 mẫu synthetic data)"]
        P3["7. LoRA Fine-Tuning & vLLM\n(Huấn luyện Qwen2.5-7B / Muse Glimmer)"]
        P4["8. Production Cloud Scaling\n(AWS ALB + RDS Multi-AZ + GPU Cluster)"]
        
        Thesis --> P2
        Thesis --> P3
        P2 --> P3
        P3 --> P4
    end
```

---

## 2. Chi tiết Thứ tự Triển khai Mới

### 🎓 GIAI ĐOẠN 1: HOÀN THIỆN HỆ THỐNG & BÁO CÁO KHÓA LUẬN (PRE-DEFENSE)

| Thứ tự | Kế hoạch liên quan | Mục tiêu cụ thể cho Khóa luận | Giá trị học thuật & Bảo vệ |
| :---: | :--- | :--- | :--- |
| **Bước 1** | **[Kế hoạch 1: Data Flywheel](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/PLAN_DATA_COLLECTION_FLYWHEEL.md)** | • Bổ sung bảng DB `conversation_feedback`.<br>• Gắn nút 👍/👎 trên từng tin nhắn AI và popup CSAT kết thúc phiên.<br>• Viết script trích xuất dataset mẫu. | Minh chứng hệ thống có cơ chế **Human-in-the-loop** và vòng lặp cải tiến dữ liệu tự động (Data Flywheel) trong Chương 3. *(Đã hoàn thành)* |
| **Bước 2** | **[Kế hoạch 6: MCP Integration](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/PLAN_MCP_INTEGRATION.md)** | • Tách 5 công cụ hiện tại thành **RetailOps FastMCP Server** (port 8002 SSE).<br>• Cho phép LangGraph kết nối linh hoạt và các client ngoài (Claude/Cursor) kết nối dùng chung tools. | Điểm nhấn công nghệ tiên tiến (**Model Context Protocol**) giúp đồ án vượt trội về tính module hóa và khả năng tích hợp ERP/bưu cục thực tế. |
| **Bước 3** | **[Kế hoạch 5: Model Evaluation](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/PLAN_MODEL_SELECTION_STRATEGY.md)** | • Chạy bộ benchmark 30+ ca kiểm thử chuẩn trong `evals/`.<br>• Đo đạc và lập bảng so sánh: **Tool Accuracy (100%), Latency, Cache Hit Rate 3-Tier, Chi phí** giữa các mô hình (Gemini Flash vs Claude Haiku vs Qwen). | Cung cấp toàn bộ **số liệu thực nghiệm, biểu đồ và bảng so sánh khoa học** làm cốt lõi cho Chương 4 (Đánh giá kết quả thực nghiệm). |
| **Bước 4** | **[Kế hoạch 7: Omnichannel Integration](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/PLAN_OMNICHANNEL_INTEGRATION.md)** | • Xây dựng Webhook tiếp nhận tin nhắn từ **Facebook Fanpage (Messenger)** và **Zalo Official Account (Zalo OA)**.<br>• Tự động định danh khách qua PSID / Zalo ID, không cần nhập mã demo.<br>• Đồng bộ 2 chiều với bàn làm việc nhân viên tư vấn (**Staff Desk**). | Minh chứng năng lực triển khai thương mại đa kênh (**Omnichannel Architecture**) trong Chương 3; tạo kịch bản demo live độc đáo cho Hội đồng. |
| **Bước 5** | **Báo cáo Luận văn & Kịch bản Demo Live** | • Viết hoàn thiện các chương luận văn (Tổng quan, Cơ sở lý thuyết Agentic AI/RAG/MCP, Thiết kế kiến trúc, Thực nghiệm & Kết luận).<br>• Đóng gói kịch bản demo live: Chiếu mã QR để Hội đồng quét chat trực tiếp qua Messenger / Zalo trên điện thoại. | Đảm bảo buổi bảo vệ trước Hội đồng diễn ra mượt mà, trực quan, thuyết phục và tạo ấn tượng mạnh mẽ nhất. |

---

### 🚀 GIAI ĐOẠN 2: CHƯNG CẤT, HUẤN LUYỆN MODEL & MỞ RỘNG (POST-DEFENSE)

Sau khi hoàn thành và bảo vệ thành công khóa luận tốt nghiệp, hệ thống chuyển sang giai đoạn tối ưu hóa mô hình nội bộ và mở rộng thương mại:

| Thứ tự | Kế hoạch liên quan | Mục tiêu cụ thể |
| :---: | :--- | :--- |
| **Bước 6** | **[Kế hoạch 2: DeepSeek Distillation](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/PLAN_DEEPSEEK_DISTILLATION.md)** | Khởi chạy script DeepSeek API sinh 3.000–5.000 cuộc hội thoại đa lượt chuẩn nghiệp vụ, kết hợp với các logs thu được từ Bước 1. |
| **Bước 7** | **[Kế hoạch 3: Fine-Tuning & Serving](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/PLAN_FINE_TUNING_SERVING.md)** | Sử dụng Unsloth huấn luyện LoRA cho mô hình nền Qwen2.5-7B hoặc Muse Glimmer 30B AWQ; benchmark đối chiếu với kết quả ở Bước 3; đóng gói vLLM/GGUF. |
| **Bước 8** | **[Kế hoạch 4: Production Scaling](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/PLAN_PRODUCTION_SCALING.md)** | Tách cơ sở dữ liệu sang Amazon RDS PostgreSQL Multi-AZ, phân tải qua AWS ALB và triển khai cụm GPU vLLM phục vụ hàng trăm ngàn lượt chat. |

