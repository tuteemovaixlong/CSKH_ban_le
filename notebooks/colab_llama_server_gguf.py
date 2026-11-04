# ==============================================================================
# RETAILOPS 2026 — Gemma-4-12B-Agentic 4-bit GGUF (llama-server) trên Colab
# CẢNH BÁO QUAN TRỌNG (§16 / W4-D10):
#   KHÔNG DÙNG TRÊN PRODUCTION. Bản GGUF llama-server chỉ dành cho thử nghiệm kỹ thuật
#   ngoài production với dữ liệu giả lập. Production bắt buộc dùng notebooks/colab_vllm_l4.py
#   (vLLM đã ghim phiên bản + bảo vệ 2 lớp NGROK_TUNNEL_TOKEN & RETAILOPS_API_KEY).
# ==============================================================================

# %% [CELL 1] Cài đặt llama-cpp-python (CUDA) & pyngrok & huggingface_hub (NON-PRODUCTION ONLY)
import os
import re
import subprocess
import sys
import time

NON_PRODUCTION_ONLY = True
if os.environ.get("RETAILOPS_ALLOW_NON_PROD_GGUF", "").strip().lower() not in ("1", "true", "yes"):
    raise RuntimeError(
        "colab_llama_server_gguf.py KHÔNG ĐƯỢC DÙNG CHO PRODUCTION (§16 / W4-D10). "
        "Hãy dùng notebooks/colab_vllm_l4.py. Nếu chỉ thử nghiệm kỹ thuật cục bộ, "
        "đặt RETAILOPS_ALLOW_NON_PROD_GGUF=true trước khi chạy."
    )

print("Đang cài đặt llama-cpp-python với CUDA và pyngrok (NON-PRODUCTION)...", flush=True)
env = dict(os.environ, CMAKE_ARGS="-DGGML_CUDA=on")
subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub", "pyngrok>=7,<8"], check=True)
subprocess.run([
    sys.executable, "-m", "pip", "install", "llama-cpp-python",
    "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cu122"
], check=True)

print("CELL 1 HOÀN TẤT (NON-PRODUCTION).")

# %% [CELL 2] Tải file GGUF Q4_K_M và khởi động llama-server (NON-PRODUCTION ONLY)
from huggingface_hub import hf_hub_download

REPO_ID = "yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF"
FILENAME = "gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2.Q4_K_M.gguf"

print(f"Đang tải {FILENAME} từ HuggingFace (khoảng 1 - 2 phút)...", flush=True)
model_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME)
print(f"Đã tải thành công: {model_path}")

subprocess.run(["pkill", "-9", "-f", "llama_cpp.server"], stderr=subprocess.DEVNULL)
time.sleep(2)


def _read_colab_secret(name):
    try:
        from google.colab import userdata
        val = userdata.get(name)
        if val is not None:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


llama_api_key = _read_colab_secret("RETAILOPS_API_KEY")
if not re.fullmatch(r"[A-Za-z0-9_.-]{32,256}", llama_api_key):
    raise RuntimeError("Yêu cầu RETAILOPS_API_KEY (32-256 ký tự) trong Colab Secrets.")

MODEL_ALIAS = "yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2"

cmd = [
    sys.executable, "-m", "llama_cpp.server",
    "--model", model_path,
    "--model_alias", MODEL_ALIAS,
    "--api_key", llama_api_key,
    "--n_gpu_layers", "-1",
    "--n_ctx", "8192",
    "--port", "8001",
    "--host", "127.0.0.1",
]

log_file = open("/tmp/llama_server.log", "w")
proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
del cmd
globals()["_llama_proc"] = proc

import urllib.request
deadline = time.monotonic() + 180
ready = False
while time.monotonic() < deadline:
    if proc.poll() is not None:
        raise RuntimeError("llama-server crash! Xem /tmp/llama_server.log")
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8001/v1/models",
            headers={"Authorization": f"Bearer {llama_api_key}"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                ready = True
                break
    except Exception:
        time.sleep(2)

del llama_api_key
if not ready:
    raise RuntimeError("Quá thời gian chờ llama-server khởi động. Log: /tmp/llama_server.log")

print("✅ LLAMA-SERVER NON-PRODUCTION ĐÃ SẴN SÀNG TRÊN CỔNG 8001!")

# %% [CELL 3] Mở ngrok HTTPS Tunnel (NON-PRODUCTION; dùng cùng helper NGROK_DOMAIN tĩnh)
import urllib.parse
from pyngrok import ngrok


def open_colab_ngrok_tunnel(
    ngrok_mod,
    port,
    tokens,
    ngrok_domain="",
    *,
    tunnel_token="",
    require_two_layer=False,
):
    import re as _re

    clean_tokens = [t.strip() for t in (tokens or []) if t and t.strip()]
    if not clean_tokens:
        raise RuntimeError("Không tìm thấy NGROK_AUTHTOKEN hợp lệ để mở tunnel ngrok.")

    raw_domain = (ngrok_domain or "").strip()
    if "://" in raw_domain:
        domain = (urllib.parse.urlsplit(raw_domain).hostname or "").strip()
    else:
        domain = raw_domain.strip().strip("/")

    clean_tunnel_token = (tunnel_token or "").strip()
    if require_two_layer and not domain:
        raise RuntimeError(
            "Yêu cầu NGROK_DOMAIN tĩnh để gắn Traffic Policy bảo vệ 2 lớp (W4-D2)."
        )
    if require_two_layer and not clean_tunnel_token:
        raise RuntimeError(
            "Yêu cầu NGROK_TUNNEL_TOKEN trong Colab Secrets để chặn request lạ tại biên ngrok (W4-D2)."
        )
    if clean_tunnel_token and not _re.fullmatch(r"[A-Za-z0-9_.-]{32,256}", clean_tunnel_token):
        raise RuntimeError(
            "NGROK_TUNNEL_TOKEN không đúng định dạng (yêu cầu 32-256 ký tự A-Z, a-z, 0-9, _, ., -)."
        )

    traffic_policy = None
    if clean_tunnel_token:
        deny_expr = (
            '!req.url.path.startsWith("/v1/") || '
            '!("x-retailops-tunnel-token" in req.headers) || '
            f'req.headers["x-retailops-tunnel-token"][0] != "{clean_tunnel_token}"'
        )
        traffic_policy = {
            "on_http_request": [
                {
                    "expressions": [deny_expr],
                    "actions": [
                        {
                            "type": "custom-response",
                            "config": {
                                "status_code": 403,
                                "headers": {"content-type": "application/json"},
                                "content": '{"error":"tunnel_forbidden"}',
                            },
                        }
                    ],
                }
            ]
        }

    try:
        for existing in ngrok_mod.get_tunnels():
            ngrok_mod.disconnect(existing.public_url)
    except Exception:
        pass

    if domain:
        ngrok_mod.set_auth_token(clean_tokens[0])
        connect_kwargs = {"domain": domain}
        if traffic_policy is not None:
            connect_kwargs["traffic_policy"] = traffic_policy
        try:
            tunnel_obj = ngrok_mod.connect(port, "http", **connect_kwargs)
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
    connect_kwargs = {"traffic_policy": traffic_policy} if traffic_policy is not None else {}
    for idx, tok in enumerate(clean_tokens, 1):
        try:
            ngrok_mod.set_auth_token(tok)
            tunnel_obj = ngrok_mod.connect(port, "http", **connect_kwargs)
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


raw_tokens = _read_colab_secret("NGROK_AUTHTOKEN")
if not raw_tokens:
    raise RuntimeError("Thiếu NGROK_AUTHTOKEN trong Colab Secrets.")
ngrok_tokens = [part.strip() for part in raw_tokens.replace("\n", ",").split(",") if part.strip()]
ngrok_domain = _read_colab_secret("NGROK_DOMAIN")
ngrok_tunnel_token = _read_colab_secret("NGROK_TUNNEL_TOKEN")

public_url = open_colab_ngrok_tunnel(
    ngrok,
    8001,
    ngrok_tokens,
    ngrok_domain=ngrok_domain,
    tunnel_token=ngrok_tunnel_token,
    require_two_layer=True,
)
del raw_tokens, ngrok_tokens, ngrok_tunnel_token
endpoint_url = f"{public_url.rstrip('/')}/v1/chat/completions"

print("\n" + "=" * 70)
print("⚠️ TUNNEL NGROK (NON-PRODUCTION GGUF — KHÔNG DÙNG CHO PRODUCTION):")
print(f"👉 Public URL: {public_url}")
print(f"👉 Endpoint API OpenAI: {endpoint_url}")
print("Đối với production EC2 (RETAILOPS_API_ENDPOINT trong api.env, --force-recreate web),")
print("bắt buộc dùng notebooks/colab_vllm_l4.py.")
print("=" * 70)
