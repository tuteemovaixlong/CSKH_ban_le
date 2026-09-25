# TÀI LIỆU BÀN GIAO PHIÊN LÀM VIỆC (SESSION HANDOFF) — 25/09/2026

> **Ngày ghi nhận:** 25/09/2026 (Tối)  
> **Nhánh chính:** `main`  
> **Cam kết mã nguồn:** Sẵn sàng cho Sprint gộp Concurrency + Relational Knowledge  
> **Trạng thái EC2:** `retailops-dev` (`i-0fd116d8927d0e412`, `t3.large`) — Sẵn sàng **STOPPED** để tối ưu hóa chi phí điện toán đám mây.  
> **Trạng thái Model vLLM:** Google Colab L4 vLLM serving `yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2` qua ngrok.

---

## 1. TỔNG KẾT THÀNH TỰU PHIÊN LÀM VIỆC (SESSION HIGHLIGHTS)

Trong phiên hôm nay, hệ thống đã hoàn thành 4 hạng mục lớn:

1. **Trực quan hóa vòng lặp suy luận ReAct & Backtracking lên UI (Commit `35dfa03`)**:
   - Giao diện người dùng Web Chat (`retailops/http/static/index.html` và `app.js`) hiển thị minh bạch toàn bộ các chặng:
     - 💭 **Suy luận (Reasoning)** của model.
     - ⚙️ **Gọi công cụ (Tool Call)** với arguments chuẩn xác.
     - 📋 **Kết quả thực tế (Observation)** trả về từ tool.
     - 🔄 **Đánh giá & Quay lui (Evaluation & Backtracking)** khi model phân tích lại ngữ cảnh.
   - Thêm dropdown "Chuỗi suy luận agent & công cụ" cho phép người dùng/kiểm toán viên mở ra xem chi tiết kỹ thuật từng bước.

2. **Khắc phục lỗi sập HTTP 500 khi xử lý đơn/sản phẩm rỗng (Commit `2d30cdb`)**:
   - Khắc phục `AttributeError: 'NoneType' object has no attribute 'get'` trong `_summarize_tool_result` khi context trả về `order=None` hoặc `prod=None`.
   - Bổ sung phòng vệ kiểu dữ liệu `isinstance(..., dict)` và bọc khối `try...except Exception`.

3. **Khắc phục lỗi treo suy luận 45.44s & HTTP 503 khi gửi ảnh tới Text-only Model (Commit `c6c7a1a`)**:
   - Model `yuxinlu1/gemma-4-12B-agentic` là Text-only CausalLM, không hỗ trợ Vision Encoder. Việc đẩy Base64 hình ảnh khiến engine vLLM bị treo timeout 45s.
   - Bổ sung hàm kiểm tra `is_vision_model()`: với model thuần text, chuyển file đính kèm thành ngữ cảnh text an toàn, loại bỏ triệt để hiện tượng vLLM hang.

4. **Kế hoạch gộp Phase 3 (Concurrency) & Phase 2 (Relational Knowledge Graph)**:
   - Soạn thảo và hoàn thiện tài liệu kiến trúc gộp: [`docs/PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md`](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md).
   - Thiết kế tích hợp:
     - **Phần A (Bounded Concurrency)**: Gỡ bỏ `self.agent_lock` toàn cục tàn dư trong `application.py`, chuẩn hóa `InferenceGate` ($K=1$, queue=8, timeout 10s $\rightarrow$ 429 Retry-After).
     - **Phần B (SQL Relational Knowledge Linkage)**: Nâng schema database lên `v5` với bảng `product_policy_links`, hạt nhân hóa tri thức quan hệ giữa sản phẩm thời trang và chính sách bảo hành 180 ngày (P-603).

5. **Kết quả kiểm thử & hợp đồng chất lượng**:
   - **415/415 tests PASS** (0 failures, 43 skipped).
   - Toàn bộ 4/4 cổng hợp đồng (docs, deployment, eval dataset, notebook) đạt **PASS 100%**.

---

## 2. HƯỚNG DẪN TẮT MÁY EC2 TỐI ƯU CHI PHÍ (SHUTDOWN RUNBOOK)

Sau khi lưu trữ mã nguồn lên GitHub, bạn hãy tắt máy EC2 để không phát sinh chi phí theo giờ:

1. Mở [AWS EC2 Console (us-east-1)](https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances:instanceState=running).
2. Tích chọn instance `i-0fd116d8927d0e412` (`retailops-dev`).
3. Nhấp vào menu **Instance state** $\rightarrow$ Chọn **Stop instance** (tuyệt đối không chọn *Terminate*).
4. Instance sẽ chuyển sang trạng thái `Stopping` rồi `Stopped`. Chi phí compute CPU/RAM sẽ dừng tính ngay lập tức.

---

## 3. QUY TRÌNH BẬT MÁY LÀM TIẾP Ở PHIÊN SAU (COLD-START RESUME RUNBOOK)

Khi bạn bật máy lên làm tiếp, thực hiện theo 4 bước nhanh dưới đây:

### Bước 1: Khởi Động Instance Trên AWS Console
1. Truy cập [AWS EC2 Console (us-east-1)](https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances:instanceState=stopped).
2. Tích chọn `i-0fd116d8927d0e412` $\rightarrow$ Nhấn **Instance state** $\rightarrow$ Chọn **Start instance**.
3. Chờ 1-2 phút cho instance chuyển sang `Running` và copy địa chỉ **Public IPv4 mới** (ví dụ: `54.210.88.99`).

### Bước 2: Cập Nhật IP Mới Vào `public.env` (Qua SSM Session Manager)
1. Trong EC2 Console, chọn instance $\rightarrow$ Nhấn nút **Connect** $\rightarrow$ Chọn tab **Session Manager** $\rightarrow$ Nhấn **Connect**.
2. Chạy 2 lệnh cập nhật IP mới (thay `X-X-X-X` bằng IP mới với dấu gạch ngang, ví dụ IP `54.210.88.99` là `54-210-88-99`):
   ```bash
   sudo sed -i 's/RETAILOPS_PUBLIC_HOST=.*/RETAILOPS_PUBLIC_HOST=retailops.X-X-X-X.sslip.io/' /opt/retailops/public.env
   sudo sed -i 's|RETAILOPS_PUBLIC_ORIGIN=.*|RETAILOPS_PUBLIC_ORIGIN=https://retailops.X-X-X-X.sslip.io|' /opt/retailops/public.env
   sudo systemctl restart caddy retailops
   ```

### Bước 3: Khởi Động Colab vLLM & Đồng Bộ Ngrok Endpoint
1. Mở Google Colab: chạy **Cell 1**, **Cell 2** (Khởi động vLLM Gemma-4-12B) và **Cell 3** (Ngrok Tunnel).
2. Copy URL ngrok sinh ra (ví dụ: `https://xxxx.ngrok-free.app/v1/chat/completions`).
3. Trong cửa sổ SSM Session Manager trên EC2, cập nhật endpoint cho RetailOps:
   ```bash
   sudo python3 /opt/retailops/scripts/update_ec2.py --api-endpoint "https://xxxx.ngrok-free.app/v1/chat/completions"
   ```

### Bước 4: Kiểm Tra Nhanh (Smoke Test)
1. Mở trình duyệt truy cập: `https://retailops.X-X-X-X.sslip.io`
2. Kiểm tra giao diện Web Chat, đặt câu hỏi test:
   *"Chính sách bảo hành sản phẩm SP-002 thế nào?"* hoặc kiểm tra chuỗi suy luận ReAct.

---

## 4. KẾ HOẠCH BẮT TAY VÀO LÀM NGAY (NEXT SPRINT TASKS)

Khi bật máy phiên tới, tiến hành triển khai Sprint gộp theo đúng tài liệu [`docs/PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md`](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md):

1. **Task 1: Nâng cấp Schema v5 (`product_policy_links`)**:
   - Thêm bảng liên kết quan hệ trong `retailops/data/store.py` (hỗ trợ cả SQLite & PostgreSQL).
   - Nâng `BUSINESS_SCHEMA_CURRENT = 5`.
2. **Task 2: Seed dữ liệu quan hệ cho P-603**:
   - Seed quan hệ chính sách bảo hành 180 ngày cho danh mục túi xách thời trang cao cấp (`BAG-001`, `BAG-002`).
3. **Task 3: Triển khai công cụ `query_related_policies`**:
   - Cho phép Agent truy vấn trực tiếp chính sách liên kết của từng sản phẩm thay vì quét text thô.
4. **Task 4: Dọn sạch `self.agent_lock` trong `application.py`**:
   - Chuyển hoàn toàn sang cơ chế giới hạn hàng đợi `InferenceGate` ($K=1$, timeout 10s, trả 429 kèm header `Retry-After`).
5. **Task 5: Viết bộ test suite mới**:
   - `tests/test_concurrency_and_relational_knowledge.py` kiểm định toàn diện cả hai năng lực mới.
