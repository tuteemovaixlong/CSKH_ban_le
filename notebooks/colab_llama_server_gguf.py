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

# %% [CELL 3] Mở ngrok HTTPS Tunnel (hỗ trợ NGROK_DOMAIN tĩnh & cập nhật EC2 an toàn)
import urllib.parse
from google.colab import userdata
from pyngrok import ngrok


def open_colab_ngrok_tunnel(ngrok_mod, port, tokens, ngrok_domain=""):
    clean_tokens = [t.strip() for t in (tokens or []) if t and t.strip()]
    if not clean_tokens:
        raise RuntimeError("Không tìm thấy NGROK_AUTHTOKEN hợp lệ để mở tunnel ngrok.")

    raw_domain = (ngrok_domain or "").strip()
    if "://" in raw_domain:
        domain = (urllib.parse.urlsplit(raw_domain).hostname or "").strip()
    else:
        domain = raw_domain.strip().strip("/")

    try:
        for existing in ngrok_mod.get_tunnels():
            ngrok_mod.disconnect(existing.public_url)
    except Exception:
        pass

    if domain:
        ngrok_mod.set_auth_token(clean_tokens[0])
        try:
            tunnel_obj = ngrok_mod.connect(port, "http", domain=domain)
        except Exception as exc:
            raise RuntimeError(
                f"Không mở được tunnel ngrok cho domain tĩnh '{domain}' bằng token đầu tiên: {exc}"
            ) from exc
        public_url = getattr(tunnel_obj, "public_url", None) or (
            tunnel_obj if isinstance(tunnel_obj, str) else ""
        )
        if not public_url:
            raise RuntimeError(f"ngrok không trả về public_url cho domain tĩnh '{domain}'.")
        actual_host = (urllib.parse.urlsplit(public_url).hostname or "").lower()
        if actual_host != domain.lower():
            try:
                ngrok_mod.disconnect(public_url)
            except Exception:
                pass
            raise RuntimeError(
                f"URL tunnel '{public_url}' không khớp với NGROK_DOMAIN '{domain}'."
            )
        return public_url

    errors = []
    for idx, tok in enumerate(clean_tokens, 1):
        try:
            ngrok_mod.set_auth_token(tok)
            tunnel_obj = ngrok_mod.connect(port, "http")
            public_url = getattr(tunnel_obj, "public_url", None) or (
                tunnel_obj if isinstance(tunnel_obj, str) else ""
            )
            if public_url:
                return public_url
            errors.append(f"token #{idx}: public_url rỗng")
        except Exception as exc:
            errors.append(f"token #{idx}: {exc}")
    raise RuntimeError(
        "Không mở được bất kỳ tunnel ngrok nào sau khi thử các token: " + "; ".join(errors)
    )


def _read_colab_secret(name):
    try:
        val = userdata.get(name)
        if val is not None:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


raw_tokens = _read_colab_secret("NGROK_AUTHTOKEN")
if not raw_tokens:
    raw_tokens = input("Nhập NGROK_AUTHTOKEN của bạn (nhiều token cách nhau dấu phẩy): ").strip()
ngrok_tokens = [part.strip() for part in raw_tokens.replace("\n", ",").split(",") if part.strip()]
ngrok_domain = _read_colab_secret("NGROK_DOMAIN")

public_url = open_colab_ngrok_tunnel(ngrok, 8001, ngrok_tokens, ngrok_domain=ngrok_domain)
endpoint_url = f"{public_url.rstrip('/')}/v1/chat/completions"

print("\n" + "=" * 70)
print("🎉 TUNNEL NGROK ĐÃ MỞ THÀNH CÔNG:")
print(f"👉 Public URL: {public_url}")
print(f"👉 Endpoint API OpenAI: {endpoint_url}")
print("=" * 70)
print("\nĐể cập nhật endpoint lên EC2 an toàn (qua AWS SSM, chỉ tạo lại container web):")
print(f"1. Cập nhật RETAILOPS_API_ENDPOINT={endpoint_url} (và RETAILOPS_API_MODEL={MODEL_ALIAS}) trong /opt/retailops/api.env")
print(
    "2. Chạy:\n"
    "   sudo docker compose --project-name retailops-web \\\n"
    "     --env-file /opt/retailops/deployed.env \\\n"
    "     --env-file /opt/retailops/public.env \\\n"
    "     -f /opt/retailops/compose.public.yaml \\\n"
    "     -f /opt/retailops/compose.postgres.yaml \\\n"
    "     up -d --no-deps --no-build --pull never --force-recreate web"
)
print("=" * 70)
