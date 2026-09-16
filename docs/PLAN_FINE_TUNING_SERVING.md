# Kế hoạch Huấn luyện (Fine-Tuning) & Tích hợp Model Chuyên môn hóa

> [!IMPORTANT]
> **Lịch trình Triển khai: GIAI ĐOẠN 2 (Sau khi Hoàn thành & Bảo vệ Khóa luận Tốt nghiệp)**  
> Để đảm bảo độ ổn định tuyệt đối và tránh rủi ro mô hình sinh lỗi khi demo trước Hội đồng chấm khóa luận, giai đoạn Fine-tuning chỉ được kích hoạt sau khi hệ thống nền tảng, bộ thu thập dữ liệu (Flywheel) và Báo cáo luận văn đã hoàn tất 100%. Trong thời gian bảo vệ khóa luận, hệ thống sử dụng các mô hình đã được kiểm chứng (Gemini Flash, Claude Haiku hoặc Qwen2.5-7B-Instruct pretrained).

Tài liệu này xác định quy trình kỹ thuật để huấn luyện (Fine-tuning) mô hình mã nguồn mở gọn nhẹ bằng phương pháp LoRA / QLoRA, đánh giá chất lượng bằng bộ benchmark của RetailOps, và đóng gói triển khai cắm trực tiếp vào hệ thống.

---

## 1. Lựa chọn Mô hình Nền (Base Student Model)

Mục tiêu là chọn mô hình có kích thước vừa phải (từ 3B đến 8B parameters), có khả năng chạy mượt mà trên phần cứng khiêm tốn (GPU 16GB VRAM như NVIDIA T4 / L4 / RTX 4070/4090 hoặc chạy CPU qua quantization):

1. **`Qwen/Qwen2.5-7B-Instruct` (Khuyến nghị số 1)**:
   - Điểm mạnh: Khả năng gọi tool (function calling) và xử lý cú pháp JSON đứng đầu thế giới trong phân khúc mã nguồn mở.
   - Hỗ trợ tiếng Việt rất tốt, khả năng bám sát ngữ cảnh và độ dài prompt lớn.
2. **`deepseek-ai/DeepSeek-R1-Distill-Qwen-7B`**:
   - Điểm mạnh: Được chưng cất sẵn khả năng suy luận logic (Reasoning) từ DeepSeek-R1, rất thích hợp cho tác vụ giải quyết tranh chấp (`dispute_agent`) và giải thích chính sách.
3. **`google/gemma-2-9b-it`**:
   - Điểm mạnh: Khả năng đối đáp tự nhiên, văn phong tinh tế cho chế độ xã giao (`witty_agent`).

---

## 2. Công nghệ & Môi trường Huấn luyện

* **Thư viện chính**:
  * **Unsloth**: Tối ưu hóa tốc độ huấn luyện nhanh gấp 2–5 lần, giảm 80% bộ nhớ VRAM, cho phép fine-tune model 7B trên một GPU 16GB VRAM (như Google Colab miễn phí hoặc GPU thuê ngắn hạn trên RunPod với giá ~$0.2/h).
  * **Hugging Face PEFT & TRL**: Sử dụng thuật toán `SFTTrainer` và `DPOTrainer`.
* **Phương pháp huấn luyện**:
  * **Giai đoạn 1: Supervised Fine-Tuning (SFT)**:
    - Huấn luyện trên tập `data/distilled_sft.jsonl` (3.000–5.000 mẫu).
    - Mục tiêu: Ép model học thuộc 100% cú pháp gọi công cụ, định dạng JSON và giọng điệu chuẩn CSKH bán lẻ.
    - Cấu hình LoRA: `r=16, lora_alpha=32, target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]`.
  * **Giai đoạn 2: Direct Preference Optimization (DPO)** (Tùy chọn nâng cao):
    - Huấn luyện trên các cặp `chosen` vs `rejected` trích xuất từ dữ liệu người dùng/tư vấn viên.
    - Mục tiêu: Giảm thiểu hiện tượng ảo giác (hallucination) và tránh nói cộc lốc khi khách hàng bức xúc.

---

## 3. Quy trình Đánh giá & Kiểm định (Evaluation Benchmark)

Trước khi đưa model vào phục vụ thực tế, model phải vượt qua bộ đánh giá tự động có sẵn trong kho mã nguồn RetailOps:

1. **Bộ Test Dataset Contract ([scripts/check_eval_dataset.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/scripts/check_eval_dataset.py))**:
   - Chạy kiểm tra trên toàn bộ 30 ca kiểm thử tiêu chuẩn (`evals/cases.jsonl`):
     - `order_lookup`: 5 ca tra cứu và trích xuất `order_id`.
     - `policy`: 5 ca hỏi đáp chính sách đổi trả.
     - `product`: 5 ca tra cứu hàng tồn kho.
     - `safety`: 5 ca phát hiện tấn công, chửi bới, chuyển giao tư vấn viên.
     - `general & mixed`: 10 ca xã giao và bẻ lái bán hàng.
2. **Tiêu chí Đạt (Pass Criteria)**:
   - Cú pháp Tool Calling hợp lệ: **100%** (không có ngoại lệ ném ra `ProtocolError`).
   - Tỷ lệ hoàn thành nhiệm vụ đúng kịch bản (Task Success Rate): **>= 90%**.
   - Độ trễ sinh token (Latency): **< 1.5s** cho token đầu tiên (TTFT).

---

## 4. Đóng gói & Tích hợp vào RetailOps (Plug & Play)

Sau khi huấn luyện hoàn tất, model được xuất ra theo 2 hình thức:

### Cách 1: Xuất GGUF và chạy qua Ollama (Dành cho môi trường nội bộ / Colab)
* Lệnh merge LoRA weights và export sang GGUF định dạng `Q4_K_M` hoặc `Q8_0`.
* Tạo file `Modelfile`:
  ```dockerfile
  FROM ./retailops-qwen2.5-7b-q4.gguf
  PARAMETER temperature 0.2
  PARAMETER stop "<|im_end|>"
  ```
* Kết nối thông qua [notebooks/colab_agent.ipynb](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/notebooks/colab_agent.ipynb) hoặc Ollama endpoint.

### Cách 2: Phục vụ qua vLLM chuẩn OpenAI API (Dành cho EC2 Production)
* Khởi động server vLLM trên máy chủ GPU:
  ```bash
  vllm serve ./retailops-qwen2.5-7b-merged \
      --port 8000 \
      --served-model-name retailops-specialized-v1 \
      --max-model-len 4096 \
      --gpu-memory-utilization 0.9
  ```
* Khai báo provider trong [retailops_providers.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops_providers.py):
  - Khai báo model name `retailops-specialized-v1`.
  - Hệ thống tự động nhận diện và chuyển tiếp truy vấn qua giao thức chuẩn mà không cần viết lại mã nguồn backend.

---

## 5. Kế hoạch Thực hiện

- [ ] Tạo notebook mẫu `notebooks/train_unsloth_sft.ipynb` chạy trên Google Colab / GPU.
- [ ] Tích hợp script nạp tập dữ liệu `distilled_sft.jsonl`.
- [ ] Thực hiện huấn luyện LoRA (khoảng 3 epochs, ~45 phút trên T4/L4).
- [ ] Chạy benchmark tự động trên 30 cases trong `evals/`.
- [ ] Export weights sang GGUF và kiểm thử cắm vào hệ sinh thái RetailOps.
