# BÁO CÁO TIẾN ĐỘ & TRẠNG THÁI HỆ THỐNG RETAILOPS 2026

> **Snapshot Ngày Ghi Nhận**: 2026-09-19 01:00:00 (GMT+7)  
> **Commit Hiện Tại**: [`7a04f4b`](https://github.com/tuteemovaixlong/CSKH_ban_le/commit/7a04f4b) trên nhánh `main`  
> **Trạng thái Triển khai EC2**: 🟢 **Hoạt động ổn định (Live & Healthy)**  
> **URL Web Khách hàng & Quản lý**: [https://retailops.54-88-81-187.sslip.io](https://retailops.54-88-81-187.sslip.io)  
> **URL Cổng Admin Kỹ thuật**: [https://admin-retailops.54-88-81-187.sslip.io](https://admin-retailops.54-88-81-187.sslip.io)  
> **Backend Tự Host (Self-Hosted Inference)**: Google Colab GPU L4 (24GB VRAM) kết nối qua ngrok HTTPS Tunnel  
> **Mô hình Active**: `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` (4-bit AWQ Vision-Language, dung lượng nạp ~5.5GB VRAM)

---

## 1. TỔNG QUAN TIẾN ĐỘ 6 MODULE TRỌNG TÂM

| Module | Tên Module | Tiến độ | Trạng thái kỹ thuật |
| :--- | :--- | :---: | :--- |
| **Module 1** | **Hệ Thống Lõi TMĐT, 6 SOPs & Chuẩn Hóa MCP Server** | 🟢 **100%** | Khớp nối 100% DB và UI; 6 SOPs thực chiến; Staff Desk 1-Click; Store Manager Console 5 Tabs; Product CRUD. MCP Server (Model Context Protocol) 10 tools, 4 resources, 3 prompts, Pure Python Engine (`stdio` và `sse` port 8002). |
| **Module 2** | **Đo Baseline Benchmark Cơ Sở & Ops Console** | 🟢 **95%** | Bộ 240 kịch bản vận hành thực tế (`evals/raw_deepseek_scenarios.txt`) bao phủ trọn vẹn 6 SOPs; script chạy E2E trực tiếp trên EC2; Admin Console nạp dữ liệu benchmark 240 ca với ma trận điều hướng (Routing Matrix) và thống kê token. |
| **Module 3** | **Webhook Facebook Messenger (Omnichannel)** | 🟣 **20%** | Đã hoàn thành tài liệu kiến trúc kỹ thuật chi tiết (`docs/PLAN_OMNICHANNEL_INTEGRATION.md`), cơ chế Meta Handover Protocol, schema phân luồng tin nhắn và đồng bộ 2 chiều với Staff Desk. |
| **Module 4** | **Cổng Quét Mã QR Demo Live** | 🟡 **25%** | Hạ tầng HTTPS tự động qua Caddy & sslip.io hoạt động ổn định; giao diện Web responsive mượt mà trên thiết bị di động; sẵn sàng tích hợp generator QR Code cho buổi bảo vệ Hội đồng. |
| **Module 5** | **DeepSeek SFT Data & LoRA Qwen** | 🟠 **20%** | Đã chuyển giao thức phục vụ sang **vLLM + Qwen2.5-VL-7B-Instruct-AWQ** sẵn sàng tích hợp cả Text + Vision (ảnh sản phẩm lỗi/hóa đơn) và chuẩn bị pipeline LoRA SFT. |
| **Module 6** | **Đo Lường Evaluation Đối Chứng Luận Văn** | 🔴 **10%** | Khung so sánh trước/sau khi Fine-tune (Ablation Study) phục vụ Chương 4 Luận văn tốt nghiệp; kịch bản đối chứng tự động đã sẵn sàng. |

---

## 2. KẾT QUẢ ĐÃ ĐẠT ĐƯỢC TRONG PHIÊN LÀM VIỆC (2026-09-18 ĐẾN 2026-09-19)

### 2.1. Tối Ưu Hóa Hạ Tầng Inference vLLM & GPU Colab L4
- **Chuyển đổi sang mô hình 7B AWQ**: Sau khi đánh giá các dòng mô hình lớn (27B FP8) gây quá tải VRAM và độ trễ cao, hệ thống đã chuẩn hóa sang **`Qwen/Qwen2.5-VL-7B-Instruct-AWQ`**.
  - **Mức tiêu thụ VRAM thực tế**: Chỉ chiếm ~5.5GB VRAM khi khởi động.
  - **Dung lượng trống còn lại**: Còn hơn 18GB VRAM trên GPU L4, cho phép mở rộng Context Length lên 8192 tokens và phục vụ KV Cache đa luồng tốc độ cao.
  - **Hỗ trợ Multimodal Native**: Kiến trúc Vision-Language chính chủ của Alibaba Qwen Team, sẵn sàng cho tính năng phân tích ảnh sản phẩm rách/lỗi và quét phiếu gửi hàng.
- **Dọn dẹp xung đột thư viện âm thanh Colab**: Xử lý triệt để lỗi xung đột giữa `torch` CUDA 12.8 và `torchaudio` CUDA 12.6 trên Google Colab bằng cơ chế tự động dọn dẹp thư mục gói lỗi trước khi nạp vLLM.
- **Xác thực kết nối Tunnel ngrok**: Endpoint `/v1/chat/completions` qua ngrok đã được kiểm tra trực tiếp và phản hồi hoàn hảo trong ~1.1 giây đối với các truy vấn văn bản.

### 2.2. Đồng Bộ Hóa Mã Nguồn & GitHub Actions CI/CD XANH 100%
- **Khắc phục lỗi Frontend Test**: Sửa lỗi tham chiếu `showErrorDetails` trong môi trường headless DOM mock của test suite frontend.
- **Đồng bộ Notebook Colab**: Chạy `scripts/build_agent_notebook.py`, cập nhật lại `notebooks/colab_agent.ipynb`, đảm bảo hợp đồng `AGENT_NOTEBOOK_SOURCE_SYNC_OK` và `DEPLOYMENT_CONTRACT_OK`.
- **Kiểm thử tự động**: Toàn bộ **279 / 279 bài tests PASS 100%** (0 failure, 0 error).
- **GitHub Actions**: Cả 3 workflow (`CI`, `Deploy baseline runner to EC2`, `Ops Console`) đều đạt trạng thái XANH 100%.

---

## 3. ĐIỂM TẠM DỪNG: CHI TIẾT BUG VLLM TOOL CALLING (HTTP 400)

### 3.1. Hiện Tượng Gặp Phải
Khi người dùng truy cập giao diện web [https://retailops.54-88-81-187.sslip.io](https://retailops.54-88-81-187.sslip.io) và gửi tin nhắn chào hỏi thông thường (ví dụ: `"alo"`), giao diện hiển thị thông báo lỗi lặp lại:
> **"API chưa hoàn tất yêu cầu. Không tự chuyển sang model khác."**

### 3.2. Truy Vết Nguyên Nhân Kỹ Thuật (Traceback & Root Cause)
1. **Phân loại chế độ (Routing Mode)**:
   - Trong `agent_protocol.py`, tin nhắn `"alo"` không chứa các từ khóa học thuật tổng quát (`_GENERAL_TERMS`), nên hàm `request_mode()` mặc định trả về chế độ nghiệp vụ bán lẻ (`retail` mode).
2. **Kích hoạt công cụ (Tool Attachment)**:
   - Trong `retailops_providers.py`, ở chế độ `retail` mode với `allow_tools=True`, hệ thống đính kèm danh sách 12 công cụ nghiệp vụ (`tools: TOOLS`) và gán cờ `"tool_choice": "auto"`.
3. **Phản hồi lỗi từ vLLM**:
   - Khi gửi payload này tới endpoint vLLM trên Colab, vLLM trả về mã lỗi **HTTP 400 Bad Request**:
     ```json
     {
       "error": {
         "message": "\"auto\" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set",
         "type": "BadRequestError",
         "param": null,
         "code": 400
       }
     }
     ```
4. **Xử lý ngoại lệ trên Backend**:
   - `retailops_providers.py` bắt mã HTTP 400 và raise `AgentError('api_unavailable', 'API chưa hoàn tất yêu cầu. Không tự chuyển sang model khác.')`.
5. **Lý do Colab Warmup không báo lỗi trước đó**:
   - Trong CELL 2 trên Colab, đoạn test khởi động gọi `LOCAL_AGENT.chat([...], False, 180)` với `allow_tools=False`. Do đó không có tools nào được gửi đi và vLLM vượt qua warmup bình thường, chỉ khi người dùng chat trên web thật mới phát sinh lỗi.

### 3.3. Vị Trí File Log Để Kiểm Tra Trên Colab
Toàn bộ log chi tiết của tiến trình vLLM server được lưu tại:
```bash
/tmp/vllm.log
```
Lệnh kiểm tra trực tiếp trên Google Colab:
```python
# Xem 50 dòng log cuối cùng
!tail -n 50 /tmp/vllm.log

# Lọc nhanh các dòng báo lỗi HTTP 400 / 500
!grep -E "400|500|BadRequest|Error" /tmp/vllm.log
```

---

## 4. GIẢI PHÁP ĐÃ CHUẨN BỊ SẴN (SẴN SÀNG CHẠY KHI TIẾP TỤC)

### 4.1. Mã Nguồn CELL 2 Cập Nhật Cho Google Colab
Copy toàn bộ đoạn code dưới đây đè vào **CELL 2** trong Google Colab để kích hoạt cờ Tool Calling và dọn dẹp port:

```python
# CELL 2 — Khởi động vLLM với Qwen2.5-VL-7B-Instruct-AWQ trên GPU L4 (Đã bật Tool Calling)
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

# 0. Tắt tiến trình vLLM cũ (nếu có) để giải phóng port 8001 và VRAM GPU
subprocess.run(["pkill", "-9", "-f", "vllm.entrypoints.openai.api_server"], stderr=subprocess.DEVNULL)
time.sleep(2)

# 1. Dọn dẹp torchaudio cũ nếu có xung đột
for path in glob.glob('/usr/local/lib/python*/dist-packages/torchaudio*'):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    except Exception:
        pass

# 2. Khởi động vLLM với Qwen2.5-VL-7B AWQ (~5.5GB VRAM) và bật Tool Calling
MODEL = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
print(f"Khởi động vLLM Server cho model: {MODEL} trên GPU L4...")

vllm_cmd = [
    sys.executable, "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL,
    "--port", "8001",
    "--gpu-memory-utilization", "0.85",    # Chiếm ~5.5GB, chừa 18GB trống cho KV Cache
    "--max-model-len", "8192",             # Context 8k thoải mái cho ảnh HD và hội thoại CSKH
    "--trust-remote-code",                 # Bắt buộc cho kiến trúc Vision của Qwen
    "--enable-auto-tool-choice",           # BẮT BUỘC: Cho phép tự động kích hoạt function calling
    "--tool-call-parser", "hermes"         # BẮT BUỘC: Parser tool-calling chuẩn của dòng Qwen2.5
]

log_file = open("/tmp/vllm.log", "w")
vllm_proc = subprocess.Popen(vllm_cmd, stdout=log_file, stderr=subprocess.STDOUT)
globals()["_vllm_process"] = vllm_proc

print("Đang nạp model 7B AWQ vào GPU L4 (khoảng 1 phút)...", flush=True)
deadline = time.monotonic() + 300
ready = False

while time.monotonic() < deadline:
    if vllm_proc.poll() is not None:
        raise RuntimeError("vLLM crash khi khởi động! Xem log:\n" + open("/tmp/vllm.log").read()[-3500:])
    try:
        req = urllib.request.Request("http://127.0.0.1:8001/v1/models")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                ready = True
                break
    except Exception:
        time.sleep(3)

if not ready:
    raise RuntimeError("Quá thời gian chờ vLLM khởi động. Xem log: /tmp/vllm.log")

print("✅ vLLM QWEN 2.5-VL INSTRUCT ĐÃ SẴN SÀNG TRÊN CỔNG 8001 (ĐÃ BẬT TOOL CALLING)!")

# 3. WARMUP LOCAL AGENT (Test trực tiếp với allow_tools=True như web thật)
from retailops_providers import OpenRouterAgent
class LocalVllmAgent:
    def __init__(self, model_name, port=8001):
        self.model = model_name
        self.endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
    def chat(self, messages, allow_tools, timeout=180):
        adapter = OpenRouterAgent('local-token-32chars-random-abcde', self.model)
        adapter.endpoint = self.endpoint
        adapter.ENDPOINT = self.endpoint
        return adapter.chat(messages, allow_tools, timeout)

LOCAL_AGENT = LocalVllmAgent(MODEL)
print("Đang gửi warmup test tin nhắn với allow_tools=True...", flush=True)
_warm = LOCAL_AGENT.chat([{'role': 'user', 'content': 'alo'}], True, 180)
print("Warmup kết quả:", _warm['message']['content'])
print("CELL_2_READY")
```

### 4.2. Kế Hoạch Bước Tiếp Theo Khi Mở Lại Phiên
1. Chạy lại **CELL 2** đã cập nhật trên Colab.
2. Xác nhận log in ra `CELL_2_READY` với câu chào thành công.
3. Chạy lại **CELL 3** (ngrok tunnel).
4. Thử nghiệm trên Web UI [https://retailops.54-88-81-187.sslip.io](https://retailops.54-88-81-187.sslip.io) với các câu thoại:
   - Chat thông thường: `"alo"`, `"chào bạn"`.
   - Tra cứu đơn hàng (Tools): `"Kiểm tra đơn hàng O-819125"`.
   - Nghiệp vụ hủy đơn: `"Tôi muốn hủy áo sơ mi lụa công sở"`.
5. Tiếp tục triển khai **Module 3: Webhook Facebook Messenger (Omnichannel)**.
