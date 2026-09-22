---
trạng_thái: SUPERSEDED / NEEDS UPDATE (Post-Thesis Scaling Roadmap)
mã_kế_hoạch: PLAN_PRODUCTION_SCALING
nguồn_sự_thật:
  - retailops/storage/pg_schema.py
  - retailops_providers.py
cập_nhật_cuối: 2026-09-22
---

# Kế Hoạch Mở Rộng Quy Mô Hạ Tầng (Production Scaling Architecture)

> [!NOTE]
> **Lịch trình Triển khai: GIAI ĐOẠN 6 (Post-Thesis / Mở Rộng Thương Mại Sau Khóa Luận)**  
> Ở giai đoạn làm Khóa luận Tốt nghiệp, hệ thống tập trung vận hành ổn định trên máy chủ EC2 đơn lẻ (Single-instance HTTPS via Caddy) kết hợp máy chủ WSGI Waitress (8 threads) và Bounded Concurrency Gate để phục vụ chấm điểm và demo live 100% tin cậy. Kiến trúc phân tán AWS ALB + Amazon RDS Multi-AZ + vLLM Cluster sẽ được đưa vào phần **Hướng phát triển tương lai** của Luận văn và triển khai sau khi bảo vệ xong.

Tài liệu này xác định kiến trúc mở rộng (Scaling Architecture) cho RetailOps từ mô hình triển khai máy chủ đơn lẻ (Single-instance EC2) hiện tại sang kiến trúc phân tán có tính sẵn sàng cao (High Availability), chịu tải lớn và tối ưu hóa chi phí vận hành.

---

## 1. Phân Tích Hiện Trạng & Ranh Giới Tối Ưu

* **Mô hình hiện tại**:
  - Toàn bộ dịch vụ (Caddy Reverse Proxy, Web API container, PostgreSQL database) chạy trên máy chủ EC2 `retailops-dev` (t3.large).
  - Model Inference kết nối vLLM tự host (GPU Colab L4 qua ngrok) hoặc Cloud API (OpenRouter/DeepSeek).
* **Định hướng tối ưu hóa đúng đắn**:
  1. **Tài nguyên CPU/RAM & WSGI Headroom**: Bounded InferenceGate giới hạn số lượt suy luận đồng thời, kiểm soát hàng đợi để luôn chừa ít nhất 2 luồng trống cho healthcheck và API quản trị.
  2. **Cơ sở dữ liệu & Tri thức**: Khảo sát pooling (`psycopg_pool`) sau khi benchmark chứng minh overhead > 5ms/turn; GraphRAG Apache AGE quản lý phiên an toàn.
  3. **Ranh giới Cache Coherence**: Loại bỏ giả định "Semantic Cache hit 60% cho policy/retail". Tra cứu chính sách và nghiệp vụ bắt buộc truy xuấtสด và kiểm tra trích dẫn sống. Semantic cache chỉ dùng cho câu hỏi xã giao thông thường (`mode == 'general'`).

---

## 2. Kiến Trúc Mở Rộng Đích Sau Khóa Luận (Target Scale Architecture)

```mermaid
flowchart TD
    subgraph Client Tier
        Browser["Trình duyệt Khách hàng"]
        Widget["Nhúng Web (embed.js)"]
    end

    Browser & Widget --> ALB["AWS Application Load Balancer (ALB) + Caddy"]

    subgraph App Tier (Horizontal Auto-scaling)
        ALB --> Web1["RetailOps Web Pod #1 (Waitress / Concurrency Gate)"]
        ALB --> Web2["RetailOps Web Pod #2 (Waitress / Concurrency Gate)"]
        ALB --> WebN["RetailOps Web Pod #N (Waitress / Concurrency Gate)"]
    end

    subgraph Data & Knowledge Tier
        Web1 & Web2 & WebN --> RDS["Amazon RDS for PostgreSQL (Multi-AZ)"]
        RDS --> Replica["RDS Read Replica (pgvector + Apache AGE)"]
    end

    subgraph Inference Tier (Dedicated Serving)
        Web1 & Web2 & WebN --> InfGate["InferenceGate (Bounded Semaphores)"]
        InfGate --> vLLM["vLLM GPU Cluster (AWS G5 / RunPod)"]
        InfGate --> CloudAPI["Cloud API (OpenRouter / DeepSeek API)"]
    end
```

---

## 3. Lộ Trình Mở Rộng 3 Giai Đoạn (Sau Khi Bảo Vệ Khóa Luận)

### Giai Đoạn 1: Tách Tầng Cơ Sở Dữ Liệu & Connection Pooling
1. **Chuyển PostgreSQL sang AWS RDS**:
   - Chuyển cơ sở dữ liệu từ container EC2 sang **Amazon RDS for PostgreSQL 16** có extension `pgvector` và `age`.
   - Bật sao lưu tự động (Automated Backups) và Multi-AZ dự phòng.
2. **Kích hoạt Bounded Connection Pooling**:
   - Triển khai `psycopg_pool.ConnectionPool` với kích thước phù hợp, có reset hook để quản lý phiên Apache AGE và role `retailops`.

### Giai Đoạn 2: Mở Rộng Không Trạng Thái Tầng Web API (AWS ECS Fargate)
1. **Auto Scaling Containers**:
   - Do mã nguồn RetailOps tuân thủ kiến trúc Stateless (session lưu trong PostgreSQL), có thể cấu hình Auto Scaling Group (ASG) tăng giảm số container theo lưu lượng.
2. **Phân tải qua AWS Application Load Balancer (ALB)**:
   - Phân chia lưu lượng mạng đồng đều, tích hợp AWS WAF chống tấn công DDoS.

### Giai Đoạn 3: Cụm Serving Model Tự Host Chuyên Dụng
1. **vLLM Cluster Trên GPU Dedicated**:
   - Triển khai cụm GPU AWS EC2 G5 (NVIDIA A10G) hoặc máy chủ chuyên dụng chạy vLLM PagedAttention phục vụ mô hình Gemma-4-12B / Qwen2.5-7B đã fine-tune.
2. **Đo đạc & Giám sát Toàn Tuyến**:
   - Tích hợp Prometheus / Grafana giám sát `queue_wait_ms`, `provider_inference_ms`, `in_flight_inferences` và Jain's Fairness Index thời gian thực.
