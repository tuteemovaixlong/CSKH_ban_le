# ==============================================================================
# RETAILOPS 2026 — Gemma-4-12B-Agentic 4-bit GGUF (llama-server) trên Colab
# Model: yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF (Q4_K_M)
# Tối ưu tải cực nhanh (~7GB), khởi động tức thì, VRAM ~5.2GB, OpenAI Compatible
# ==============================================================================

# %% [CELL 1] Cài đặt llama-cpp-python (CUDA) & pyngrok & huggingface_hub
import os
import subprocess
import sys
import time

print("Đang cài đặt llama-cpp-python với CUDA và pyngrok...", flush=True)
env = dict(os.environ, CMAKE_ARGS="-DGGML_CUDA=on")
subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub", "pyngrok>=7,<8"], check=True)
subprocess.run([
    sys.executable, "-m", "pip", "install", "llama-cpp-python",
    "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cu122"
], check=True)

print("CELL 1 HOÀN TẤT.")

# %% [CELL 2] Tải file GGUF Q4_K_M và khởi động llama-server
from huggingface_hub import hf_hub_download

REPO_ID = "yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF"
FILENAME = "gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2.Q4_K_M.gguf"

print(f"Đang tải {FILENAME} từ HuggingFace (khoảng 1 - 2 phút)...", flush=True)
model_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME)
print(f"Đã tải thành công: {model_path}")

subprocess.run(["pkill", "-9", "-f", "llama_cpp.server"], stderr=subprocess.DEVNULL)
time.sleep(2)

MODEL_ALIAS = "yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2"

cmd = [
    sys.executable, "-m", "llama_cpp.server",
    "--model", model_path,
    "--model_alias", MODEL_ALIAS,
    "--n_gpu_layers", "-1",        # Đẩy toàn bộ layers lên GPU (100% VRAM offload)
    "--n_ctx", "8192",              # 8k context tokens
    "--port", "8001",
    "--host", "127.0.0.1"
]

log_file = open("/tmp/llama_server.log", "w")
proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
globals()["_llama_proc"] = proc

import urllib.request
deadline = time.monotonic() + 180
ready = False
while time.monotonic() < deadline:
    if proc.poll() is not None:
        raise RuntimeError("llama-server crash! Log:\n" + open("/tmp/llama_server.log").read()[-3000:])
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/v1/models", timeout=2) as resp:
            if resp.status == 200:
                ready = True
                break
    except Exception:
        time.sleep(2)

if not ready:
    raise RuntimeError("Quá thời gian chờ llama-server khởi động. Log: /tmp/llama_server.log")

print("✅ LLAMA-SERVER GEMMA-4 12B Q4_K_M ĐÃ SẴN SÀNG TRÊN CỔNG 8001!")

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
print(f"python3 scripts/update_ec2.py --api-endpoint {tunnel.public_url}/v1/chat/completions --api-model {MODEL_ALIAS}")
print("="*70)
