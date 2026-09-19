# ==============================================================================
# RETAILOPS 2026 — vLLM + Qwen2.5-VL-7B-Instruct-AWQ trên GPU L4 (Google Colab)
# Đã kích hoạt đầy đủ Tool Calling / Function Calling và ngrok HTTPS Tunnel
# ==============================================================================
# Hướng dẫn sử dụng:
# 1. Chọn Runtime -> Change runtime type -> L4 GPU (hoặc A100/V100).
# 2. Điền Colab Secrets: NGROK_AUTHTOKEN và RETAILOPS_INFERENCE_TOKEN.
# 3. Chạy từng CELL theo thứ tự bên dưới.
# ==============================================================================

# %% [CELL 1] Cài đặt dependencies vLLM & pyngrok
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

print("Đang cài đặt vLLM và pyngrok...", flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=False)
subprocess.run([sys.executable, "-m", "pip", "install", "vllm>=0.6.0", "pyngrok>=7,<8"], check=True)

# Dọn dẹp xung đột torchaudio nếu có
for path in glob.glob('/usr/local/lib/python*/dist-packages/torchaudio*'):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    except Exception:
        pass

print("CELL 1 HOÀN TẤT: Môi trường đã sẵn sàng.")

# %% [CELL 2] Khởi động vLLM Server với Tool Calling và Warmup Test
subprocess.run(["pkill", "-9", "-f", "vllm.entrypoints.openai.api_server"], stderr=subprocess.DEVNULL)
time.sleep(2)

MODEL = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
print(f"Khởi động vLLM Server cho model: {MODEL} trên GPU L4...")

vllm_cmd = [
    sys.executable, "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL,
    "--port", "8001",
    "--gpu-memory-utilization", "0.85",    # Chiếm ~5.5GB, chừa 18GB trống cho KV Cache
    "--max-model-len", "8192",             # Context 8k tokens cho cả ảnh và text
    "--trust-remote-code",                 # Hỗ trợ kiến trúc Vision của Qwen
    "--enable-auto-tool-choice",           # BẮT BUỘC: Cho phép tự động kích hoạt function calling
    "--tool-call-parser", "hermes"         # BẮT BUỘC: Parser tool-calling chuẩn của Qwen2.5
]

log_file = open("/tmp/vllm.log", "w")
vllm_proc = subprocess.Popen(vllm_cmd, stdout=log_file, stderr=subprocess.STDOUT)
globals()["_vllm_process"] = vllm_proc

print("Đang nạp model 7B AWQ vào GPU (khoảng 1 - 2 phút)...", flush=True)
deadline = time.monotonic() + 300
ready = False

while time.monotonic() < deadline:
    if vllm_proc.poll() is not None:
        raise RuntimeError("vLLM crash khi khởi động! Log:\n" + open("/tmp/vllm.log").read()[-3500:])
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

print("✅ vLLM QWEN 2.5-VL INSTRUCT ĐÃ SẴN SÀNG TRÊN CỔNG 8001 (TOOL CALLING ON)!")

# Warmup test trực tiếp với allow_tools=True
test_payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "alo"}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Tra cứu thông tin chi tiết của một đơn hàng",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"]
            }
        }
    }],
    "tool_choice": "auto"
}
req = urllib.request.Request(
    "http://127.0.0.1:8001/v1/chat/completions",
    data=json.dumps(test_payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=30) as resp:
    warmup_res = json.loads(resp.read().decode("utf-8"))
    print("Warmup kết quả với Tool Calling:", warmup_res["choices"][0]["message"])

print("CELL 2 SẴN SÀNG!")

# %% [CELL 3] Mở ngrok HTTPS Tunnel
from google.colab import userdata
from pyngrok import ngrok

try:
    ngrok_token = userdata.get('NGROK_AUTHTOKEN')
except Exception:
    ngrok_token = input("Nhập NGROK_AUTHTOKEN của bạn: ").strip()

ngrok.set_auth_token(ngrok_token)

# Dọn tunnel cũ nếu có
try:
    for t in ngrok.get_tunnels():
        ngrok.disconnect(t.public_url)
except Exception:
    pass

tunnel = ngrok.connect(8001, "http")
print("\n" + "="*70)
print(f"🎉 TUNNEL NGROK ĐÃ MỞ THÀNH CÔNG:")
print(f"👉 Public URL: {tunnel.public_url}")
print(f"👉 Endpoint API OpenAI: {tunnel.public_url}/v1/chat/completions")
print("="*70)
print("\nĐể cập nhật lên EC2, chạy lệnh trên host EC2:")
print(f"python3 scripts/update_ec2.py --api-endpoint {tunnel.public_url}/v1/chat/completions --api-model {MODEL}")
print("="*70)
