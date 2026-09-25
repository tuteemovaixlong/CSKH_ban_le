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

# %% [CELL 2] Khởi động vLLM Server tối ưu tốc độ cho Gemma-4-12B (L4 FP8 + CUDA Graphs + Prefix Caching)
subprocess.run(["pkill", "-9", "-f", "vllm"], stderr=subprocess.DEVNULL)
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

# Tải tool_chat_template_gemma4.jinja và VÁ LỖI STRING ARGUMENTS AN TOÀN
template_path = "/content/tool_chat_template_gemma4.jinja"
template_url = "https://raw.githubusercontent.com/vllm-project/vllm/main/examples/tool_chat_template_gemma4.jinja"

print("⏳ Đang tải Jinja chat template chuẩn từ vLLM...", flush=True)
req = urllib.request.Request(template_url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Tải template thất bại với HTTP status: {resp.status}")
        tmpl = resp.read().decode('utf-8')
except Exception as e:
    raise RuntimeError(f"Không thể tải template từ GitHub: {e}")

if len(tmpl) < 1000:
    raise RuntimeError(f"File template quá nhỏ hoặc không hợp lệ (kích thước: {len(tmpl)} bytes).")

bad_block = """                    {%- elif function['arguments'] is none -%}
                    {%- else -%}
                        {{- raise_exception(
                            "chat_template: tool_calls[].function.arguments must be a "
                            "JSON object (mapping), not a string. Deserialize arguments "
                            "before passing to the template."
                        ) -}}
                    {%- endif -%}"""

good_block = """                    {%- elif function['arguments'] is string -%}
                        {%- set raw_args = function['arguments'] | trim -%}
                        {%- if raw_args.startswith('{') and raw_args.endswith('}') -%}
                            {{- raw_args[1:-1] | trim -}}
                        {%- else -%}
                            {{- raw_args -}}
                        {%- endif -%}
                    {%- elif function['arguments'] is none -%}
                    {%- endif -%}"""

if bad_block in tmpl:
    tmpl = tmpl.replace(bad_block, good_block)
    print("✅ Đã vá lỗi JSON string arguments cho template thành công!")
else:
    print("ℹ️ Template không chứa khối lỗi hoặc đã có định dạng tương thích.")

with open(template_path, 'w', encoding='utf-8') as f:
    f.write(tmpl)

MODEL = "yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2"
print(f"Khởi động vLLM Server tối ưu cho model: {MODEL} trên GPU L4...")

# CHỌN 1 TRONG 2 CÁCH QUANTIZATION DƯỚI ĐÂY:
# -----------------------------------------------------------------------------------------------------
# CÁCH 1 (KHUYÊN DÙNG CHO L4): Dùng FP8 Native (Ada Lovelace Tensor Core).
# Model 12B chiếm ~12GB/24GB VRAM, còn dư 12GB cho KV cache, tốc độ cực nhanh, không giảm độ chính xác.
QUANT_MODE = "fp8"  # Hoặc đổi thành "bitsandbytes" nếu muốn ép về 4-bit (~6GB VRAM)

if QUANT_MODE == "fp8":
    quant_flags = ["--quantization", "fp8"]
else:
    quant_flags = ["--quantization", "bitsandbytes", "--load-format", "bitsandbytes"]

# Tắt FlashInfer JIT ninja để tránh xung đột thư viện trên Colab
os.environ["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
os.environ["VLLM_USE_FLASHINFER"] = "0"

# CẤU HÌNH TỐI ƯU HIỆU NĂNG CHO GPU L4 (ADA LOVELACE):
# 1. Bỏ --enforce-eager: Cho phép CUDA Graphs để tăng tốc decoding lên 1.5x - 2x.
# 2. --enable-prefix-caching: Giữ cache KV của System Prompt + Tool Schema (giảm 1.5s TTFT).
# 3. --kv-cache-dtype fp8: Tận dụng phần cứng FP8 của GPU L4, giảm 50% băng thông đọc/ghi KV.
# 4. --max-model-len 4096: Vừa vặn CSKH, khởi tạo CUDA Graph cực nhanh, tránh OOM.
vllm_cmd = [
    sys.executable, "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL,
    *quant_flags,
    "--port", "8001",
    "--gpu-memory-utilization", "0.88",
    "--max-model-len", "8192",
    "--kv-cache-dtype", "fp8",
    "--enable-prefix-caching",
    "--trust-remote-code",
    "--enable-auto-tool-choice",
    "--tool-call-parser", "gemma4",
    "--reasoning-parser", "gemma4",
    "--chat-template", template_path,
    "--default-chat-template-kwargs", '{"enable_thinking": true}'
]

log_file = open("/tmp/vllm.log", "w")
vllm_proc = subprocess.Popen(
    vllm_cmd,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    start_new_session=True
)
globals()["_vllm_process"] = vllm_proc

print(f"Đang nạp model ({QUANT_MODE}) và biên dịch CUDA Graphs trên GPU L4 (khoảng 1.5 - 2 phút)...", flush=True)
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

print("✅ vLLM GEMMA-4-12B AGENTIC ĐÃ SẴN SÀNG TRÊN CỔNG 8001 (CUDA GRAPHS + PREFIX CACHING ON)!")

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
