# Kế hoạch Mở rộng Quy mô Hạ tầng (Production Scaling Architecture)

> [!NOTE]
> **Lịch trình Triển khai: GIAI ĐOẠN 2 (Post-Thesis / Mở rộng Thương mại)**  
> Ở giai đoạn làm Khóa luận Tốt nghiệp, hệ thống tập trung vận hành ổn định trên máy chủ EC2 đơn lẻ (Single-instance HTTPS via Caddy) để phục vụ chấm điểm và demo live 100% tin cậy. Kiến trúc phân tán AWS ALB + Amazon RDS Multi-AZ + vLLM Cluster sẽ được đưa vào phần **Hướng phát triển tương lai** của Luận văn và triển khai sau khi bảo vệ xong.

Tài liệu này xác định kiến trúc mở rộng (Scaling Architecture) cho RetailOps từ mô hình triển khai máy chủ đơn lẻ (Single-instance EC2) hiện tại sang kiến trúc phân tán có tính sẵn sàng cao (High Availability), chịu tải lớn và tối ưu hóa chi phí vận hành.

---

## 1. Phân tích Hiện trạng & Các Điểm nghẽn (Bottlenecks)

* **Mô hình hiện tại**:
  - Toàn bộ dịch vụ (Caddy Reverse Proxy, Web API container, PostgreSQL database) đang cùng chạy trên một máy chủ EC2 duy nhất.
  - Model Inference đang sử dụng API bên ngoài (Gemini/Claude) hoặc máy chủ Colab/Ollama phụ trợ.
* **Các điểm nghẽn khi người dùng tăng đột biến**:
  1. **Tài nguyên CPU/RAM**: Một máy chủ EC2 đơn lẻ sẽ bị nghẽn RAM khi nhiều người đồng thời tải trang hoặc thực hiện tra cứu.
  2. **Cơ sở dữ liệu**: PostgreSQL chạy trong container trên cùng ổ đĩa EBS với ứng dụng sẽ cạnh tranh IOPS với web server.
  3. **Thời gian suy luận của Model**: Nếu sử dụng model mã nguồn mở tự host mà chỉ chạy đơn luồng (Ollama), thời gian xếp hàng (queue latency) sẽ tăng vọt khi có trên 5 người chat cùng lúc.

---

## 2. Kiến trúc Mở rộng Đích (Target Scale Architecture)

```mermaid
flowchart TD
    subgraph Client Tier
        Browser["Trình duyệt Khách hàng"]
        Widget["Nhúng Web (embed.js)"]
    end

    Browser --> ALB["AWS Application Load Balancer (ALB) + Caddy"]
    Widget --> ALB

    subgraph App Tier (Horizontal Auto-scaling)
        ALB --> Web1["RetailOps Web Pod / Container #1"]
        ALB --> Web2["RetailOps Web Pod / Container #2"]
        ALB --> WebN["RetailOps Web Pod / Container #N"]
    end

    subgraph Data & Cache Tier
        Web1 & Web2 & WebN --> Cache["Redis / In-Memory State Cache"]
        Web1 & Web2 & WebN --> RDS["Amazon RDS for PostgreSQL (Multi-AZ)"]
        RDS --> Replica["RDS Read Replica + pgvector HNSW"]
    end

    subgraph Inference Tier (Dedicated GPU Serving)
        Web1 & Web2 & WebN --> Router["Inference Router / Semantic Cache"]
        Router -->|Cache Hit 60%| SemanticDB["pgvector Semantic Cache"]
        Router -->|Cache Miss| vLLM["vLLM GPU Cluster (AWS G5 / RunPod / SageMaker)"]
        Router -->|Fallback| CloudAPI["Cloud API (Gemini / Claude)"]
    end
```

---

## 3. Lộ trình Mở rộng 3 Giai đoạn

### Giai đoạn 1: Mở rộng Cụm Cơ sở Dữ liệu & Tách Tầng (Quy mô 1.000 – 10.000 yêu cầu/ngày)
1. **Tách PostgreSQL ra AWS RDS**:
   - Chuyển cơ sở dữ liệu từ container EC2 sang **Amazon RDS for PostgreSQL** (phiên bản 16+) kích hoạt sẵn extension `pgvector`.
   - Lợi ích: Tự động sao lưu (Automated Backups), Multi-AZ dự phòng hỏng hóc, không sợ mất dữ liệu khi restart EC2.
2. **Kích hoạt Semantic Cache tối đa**:
   - Sử dụng bảng `semantic_cache` trong [retailops/storage/pg_schema.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/storage/pg_schema.py#L70-L79) để hấp thụ phần lớn các câu hỏi lặp lại, giữ thời gian phản hồi dưới 50ms cho khách hàng.

### Giai đoạn 2: Mở rộng Tầng Web API không trạng thái (Quy mô 10.000 – 100.000 yêu cầu/ngày)
1. **Chuyển đổi sang Container Orchestration (AWS ECS Fargate hoặc EKS)**:
   - Vì mã nguồn Web/API của RetailOps đã tuân thủ kiến trúc **Stateless** (dữ liệu phiên lưu hoàn toàn trong DB), ta có thể cấu hình **Auto Scaling Group (ASG)**:
     - Tự động tăng số container từ 2 lên 10 khi CPU vượt 70%.
     - Tự động giảm số container khi đêm muộn để tiết kiệm chi phí.
2. **Phân tải qua AWS Application Load Balancer (ALB)**:
   - ALB đảm nhận phân phối lưu lượng và quản lý chứng chỉ SSL/TLS tự động thay cho Caddy cục bộ.

### Giai đoạn 3: Mở rộng Tầng Suy luận Model Chuyên biệt (vLLM Cluster)
1. **Thay thế Ollama bằng vLLM Engine**:
   - Triển khai model fine-tune (`retailops-qwen2.5-7b`) lên máy chủ GPU chuyên dụng (AWS EC2 g5.xlarge hoặc g6.xlarge với GPU NVIDIA A10G/L4).
   - vLLM sử dụng cơ chế **PagedAttention** và **Continuous Batching**, cho phép phục vụ đồng thời 50–100 người dùng trên cùng một GPU mà không bị tụt tốc độ (throughput gấp 10–20 lần so với Ollama đơn lẻ).
2. **Cơ chế Chuyển đổi Dự phòng (Circuit Breaker & Fallback)**:
   - Nếu cụm GPU quá tải hoặc gặp sự cố, Router trong [retailops_providers.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops_providers.py) tự động chuyển sang gọi Gemini Flash API trong tích tắc để dịch vụ không bao giờ bị gián đoạn.

---

## 4. Dự toán Chi phí Vận hành (Cost Optimization)

| Tầng | Cấu hình đề xuất | Chi phí ước tính/tháng |
| :--- | :--- | :--- |
| **Web Tier** | 2x AWS ECS Fargate Tasks (0.5 vCPU, 1GB RAM) | ~$25 |
| **Database Tier** | AWS RDS PostgreSQL `db.t4g.medium` (Multi-AZ) | ~$65 |
| **Inference Tier** | AWS EC2 `g5.xlarge` (1x A10G 24GB VRAM) (khi tự host) HOẶC dùng Serverless vLLM | ~$200 - $350 (hoặc pay-as-you-go qua RunPod ~$100) |
| **Network & Cache** | ALB, CloudFront, Semantic Cache | ~$20 |
| **Tổng cộng** | Hệ thống phục vụ 500.000+ tin nhắn/tháng | **~$300 - $450/tháng** |

---

## 5. Kế hoạch Thực hiện

- [ ] Chuẩn hóa Dockerfile hỗ trợ môi trường multi-task (`Dockerfile`).
- [ ] Soạn thảo template AWS CloudFormation / Terraform khởi tạo RDS PostgreSQL + ALB.
- [ ] Thử nghiệm hiệu năng của vLLM với mô hình Qwen2.5-7B trên môi trường GPU thử nghiệm.
- [ ] Cấu hình cơ chế fallback tự động trong `retailops_providers.py` khi inference timeout.
