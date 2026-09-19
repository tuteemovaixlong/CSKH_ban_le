# ==============================================================================
# RETAILOPS 2026 — Gemma-4-12B-Agentic trên Google Colab (GPU L4)
# Model: yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2
# Hỗ trợ: FP8 Native (Khuyên dùng cho L4 Ada Lovelace) hoặc BitsAndBytes 4-bit
# ==============================================================================
# Hướng dẫn sử dụng:
# 1. Chọn Runtime -> Change runtime type -> L4 GPU.
# 2. Điền Colab Secrets: NGROK_AUTHTOKEN.
# 3. Chạy từng CELL theo thứ tự bên dưới.
# ==============================================================================

# %% [CELL 1] Cài đặt dependencies vLLM, vllm-bnb-plugin & pyngrok
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

print("Đang cài đặt vLLM, plugin lượng tử hóa và pyngrok...", flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=False)
subprocess.run([
    sys.executable, "-m", "pip", "install",
    "vllm>=0.6.0",
    "vllm-bnb-plugin",          # BẮT BUỘC nếu dùng bitsandbytes 4-bit
    "bitsandbytes>=0.45.0",      # Hỗ trợ 4-bit NF4
    "accelerate",
    "pyngrok>=7,<8"
], check=True)

# Dọn dẹp xung đột torchaudio nếu có
for path in glob.glob('/usr/local/lib/python*/dist-packages/torchaudio*'):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    except Exception:
        pass

print("CELL 1 HOÀN TẤT: Môi trường vLLM đã sẵn sàng.")

# %% [CELL 2] Khởi động vLLM Server với Tool Calling
subprocess.run(["pkill", "-9", "-f", "vllm.entrypoints.openai.api_server"], stderr=subprocess.DEVNULL)
time.sleep(2)

# Nạp HF_TOKEN từ Secrets nếu có (để HuggingFace Hub không bị giới hạn tải trọng số)
try:
    from google.colab import userdata
    hf_tok = userdata.get('HF_TOKEN')
    if hf_tok:
        os.environ['HF_TOKEN'] = hf_tok
        os.environ['HUGGING_FACE_HUB_TOKEN'] = hf_tok
        print("✅ Đã nạp HF_TOKEN từ Secrets.")
except Exception:
    pass

MODEL = "yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2"
print(f"Khởi động vLLM Server cho model: {MODEL} trên GPU L4...")

# CHỌN 1 TRONG 2 CÁCH QUANTIZATION DƯỚI ĐÂY:
# -----------------------------------------------------------------------------------------------------
# CÁCH 1 (KHUYÊN DÙNG CHO L4): Dùng FP8 Native (Ada Lovelace Tensor Core).
# Model 12B chiếm ~12GB/24GB VRAM, còn dư 12GB cho KV cache, tốc độ cực nhanh, không giảm độ chính xác.
QUANT_MODE = "fp8"  # Hoặc đổi thành "bitsandbytes" nếu muốn ép về 4-bit (~6GB VRAM)

if QUANT_MODE == "fp8":
    quant_flags = ["--quantization", "fp8"]
else:
    quant_flags = ["--quantization", "bitsandbytes", "--load-format", "bitsandbytes"]

# Tắt FlashInfer JIT ninja build và bật eager mode để khởi động nhanh trong 20 giây (không bị timeout)
os.environ["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
os.environ["VLLM_USE_FLASHINFER"] = "0"

vllm_cmd = [
    sys.executable, "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL,
    *quant_flags,
    "--port", "8001",
    "--gpu-memory-utilization", "0.80",    # Dành 80% VRAM (chừa 5GB trống an toàn tuyệt đối)
    "--max-model-len", "8192",             # Context 8k tokens cho chuỗi hội thoại CSKH dài
    "--enforce-eager",                     # BỎ QUA torch.compile & CUDA Graph JIT (khởi động tức thì)
    "--trust-remote-code",
    "--enable-auto-tool-choice",           # BẮT BUỘC: Tự động kích hoạt function calling
    "--tool-call-parser", "gemma4"         # BẮT BUỘC: Parser tool-calling native cho Gemma 4
]

log_file = open("/tmp/vllm.log", "w")
vllm_proc = subprocess.Popen(vllm_cmd, stdout=log_file, stderr=subprocess.STDOUT)
globals()["_vllm_process"] = vllm_proc

print(f"Đang nạp model ({QUANT_MODE}) vào GPU L4 (khoảng 1.5 - 2 phút)...", flush=True)
deadline = time.monotonic() + 450
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

print("✅ vLLM GEMMA-4-12B AGENTIC ĐÃ SẴN SÀNG TRÊN CỔNG 8001 (TOOL CALLING ON)!")

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
