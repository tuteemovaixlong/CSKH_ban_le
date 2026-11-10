# ==============================================================================
# RETAILOPS 2026 — Gemma-4-12B-Agentic trên Google Colab (GPU L4)
# Model: yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2
# Bảo vệ 2 lớp (W4-D2, W4-D10):
#   Lớp 1 (biên ngrok): NGROK_DOMAIN tĩnh + Traffic Policy kiểm X-RetailOps-Tunnel-Token
#   Lớp 2 (ứng dụng):   vLLM --api-key (RETAILOPS_API_KEY trong Colab Secrets)
# ==============================================================================
# Hướng dẫn sử dụng:
# 1. Chọn Runtime -> Change runtime type -> L4 GPU.
# 2. Điền Colab Secrets (KHÔNG dán khóa vào code/log):
#    - NGROK_AUTHTOKEN      : token tài khoản ngrok
#    - NGROK_DOMAIN         : domain tĩnh đã đăng ký trên ngrok (bắt buộc cho production)
#    - NGROK_TUNNEL_TOKEN   : khóa bí mật lớp 1 (32-256 ký tự URL-safe, khớp EC2 api.env)
#    - RETAILOPS_API_KEY    : khóa bí mật lớp 2 cho vLLM --api-key (khớp EC2 api.env)
#    - HF_TOKEN             : (tùy chọn) token HuggingFace để tải model nhanh
# 3. Chạy từng CELL theo thứ tự bên dưới.
# ==============================================================================

# %% [CELL 1] Cài đặt dependencies với phiên bản vLLM cố định (W4-D10)
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

VLLM_VERSION = "0.32.0"
VLLM_PACKAGE = "vllm==0.32.0"
TEMPLATE_URL = f"https://raw.githubusercontent.com/vllm-project/vllm/v{VLLM_VERSION}/examples/tool_chat_template_gemma4.jinja"
TEMPLATE_SHA256 = "afdbb2abe3667ccde95cc2f86919f05370339399bab5f750950a4390523b8927"
MAX_IMAGES_PER_REQUEST = 3
MAX_MODEL_LEN = int(os.environ.get("RETAILOPS_MAX_MODEL_LEN", "16384"))
if not 4096 <= MAX_MODEL_LEN <= 131072:
    raise ValueError("RETAILOPS_MAX_MODEL_LEN must be 4096–131072")

print(f"Đang cài đặt {VLLM_PACKAGE}, plugin lượng tử hóa và pyngrok...", flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=False)
subprocess.run([
    sys.executable, "-m", "pip", "install",
    VLLM_PACKAGE,
    "vllm-bnb-plugin",          # BẮT BUỘC nếu dùng bitsandbytes 4-bit
    "bitsandbytes>=0.45.0",      # Hỗ trợ 4-bit NF4
    "accelerate",
    "pyngrok>=7,<8",
], check=True)

# Dọn dẹp xung đột torchaudio nếu có
for path in glob.glob("/usr/local/lib/python*/dist-packages/torchaudio*"):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    except Exception:
        pass

print(f"CELL 1 HOÀN TẤT: Môi trường vLLM=={VLLM_VERSION} đã sẵn sàng.")


# %% [CELL 2] Khởi động vLLM Server (2 lớp bảo vệ + ghim digest template + tắt log request)
def _read_colab_secret(name):
    try:
        from google.colab import userdata
        val = userdata.get(name)
        if val is not None:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


def verify_and_patch_chat_template(raw_bytes, expected_sha256=TEMPLATE_SHA256):
    if not isinstance(raw_bytes, (bytes, bytearray)) or len(raw_bytes) < 1000:
        raise RuntimeError("File chat template quá nhỏ hoặc không hợp lệ.")
    actual_sha256 = hashlib.sha256(bytes(raw_bytes)).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"SHA-256 của chat template không khớp digest đã ghim: "
            f"nhận {actual_sha256}, kỳ vọng {expected_sha256}."
        )
    tmpl = bytes(raw_bytes).decode("utf-8")
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
    return tmpl


def build_vllm_server_command(
    python_exe,
    model,
    quant_mode,
    template_path,
    api_key,
    *,
    port=8001,
    max_images=MAX_IMAGES_PER_REQUEST,
):
    clean_key = (api_key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{32,256}", clean_key):
        raise RuntimeError(
            "Thiếu hoặc sai định dạng RETAILOPS_API_KEY trong Colab Secrets "
            "(yêu cầu chuỗi 32-256 ký tự URL-safe cho vLLM --api-key)."
        )
    if quant_mode == "fp8":
        quant_flags = ["--quantization", "fp8"]
    else:
        quant_flags = ["--quantization", "bitsandbytes", "--load-format", "bitsandbytes"]
    mm_limit_json = json.dumps({"image": int(max_images)})
    return [
        python_exe, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model,
        *quant_flags,
        "--host", "127.0.0.1",
        "--port", str(int(port)),
        "--api-key", clean_key,
        "--no-enable-log-requests",
        "--disable-uvicorn-access-log",
        "--limit-mm-per-prompt", mm_limit_json,
        "--gpu-memory-utilization", "0.88",
        "--max-model-len", str(MAX_MODEL_LEN),
        "--kv-cache-dtype", "fp8",
        "--enable-prefix-caching",
        "--trust-remote-code",
        "--enable-auto-tool-choice",
        "--tool-call-parser", "gemma4",
        "--reasoning-parser", "gemma4",
        "--chat-template", template_path,
        "--default-chat-template-kwargs", '{"enable_thinking": true}',
    ]


subprocess.run(["pkill", "-9", "-f", "vllm"], stderr=subprocess.DEVNULL)
time.sleep(2)

hf_tok = _read_colab_secret("HF_TOKEN")
if hf_tok:
    os.environ["HF_TOKEN"] = hf_tok
    os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_tok
    print("✅ Đã nạp HF_TOKEN từ Secrets.")
del hf_tok

vllm_api_key = _read_colab_secret("RETAILOPS_API_KEY") or _read_colab_secret("VLLM_API_KEY")
if not re.fullmatch(r"[A-Za-z0-9_.-]{32,256}", vllm_api_key):
    raise RuntimeError(
        "Bắt buộc đặt RETAILOPS_API_KEY (32-256 ký tự) trong Colab Secrets trước khi mở vLLM."
    )

template_path = "/content/tool_chat_template_gemma4.jinja"
print(f"⏳ Đang tải Jinja chat template đã ghim (v{VLLM_VERSION})...", flush=True)
req = urllib.request.Request(TEMPLATE_URL, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Tải template thất bại với HTTP status: {resp.status}")
        raw_template_bytes = resp.read()
except Exception as e:
    raise RuntimeError(f"Không thể tải template từ GitHub: {e}") from e

patched_tmpl = verify_and_patch_chat_template(raw_template_bytes, TEMPLATE_SHA256)
with open(template_path, "w", encoding="utf-8") as f:
    f.write(patched_tmpl)
print(f"✅ Đã xác minh SHA-256 ({TEMPLATE_SHA256[:12]}…) và ghi chat template an toàn.")

MODEL = "yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2"
QUANT_MODE = "fp8"  # Hoặc "bitsandbytes" nếu muốn ép về 4-bit

os.environ["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
os.environ["VLLM_USE_FLASHINFER"] = "0"

vllm_cmd = build_vllm_server_command(
    sys.executable,
    MODEL,
    QUANT_MODE,
    template_path,
    vllm_api_key,
    port=8001,
    max_images=MAX_IMAGES_PER_REQUEST,
)

log_file = open("/tmp/vllm.log", "w")
vllm_proc = subprocess.Popen(
    vllm_cmd,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
del vllm_cmd
globals()["_vllm_process"] = vllm_proc

print(f"Đang nạp model ({QUANT_MODE}) và biên dịch CUDA Graphs trên GPU L4...", flush=True)
deadline = time.monotonic() + 450
ready = False
local_auth_headers = {"Authorization": f"Bearer {vllm_api_key}"}

while time.monotonic() < deadline:
    if vllm_proc.poll() is not None:
        raise RuntimeError("vLLM crash khi khởi động! Kiểm tra /tmp/vllm.log trên runtime.")
    try:
        req = urllib.request.Request("http://127.0.0.1:8001/v1/models", headers=local_auth_headers)
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                ready = True
                break
    except Exception:
        time.sleep(3)

if not ready:
    raise RuntimeError("Quá thời gian chờ vLLM khởi động. Xem log: /tmp/vllm.log")

print("✅ vLLM GEMMA-4-12B AGENTIC ĐÃ SẴN SÀNG TRÊN 127.0.0.1:8001 (API-KEY + NO REQUEST LOGS)!")

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
                "required": ["order_id"],
            },
        },
    }],
    "tool_choice": "auto",
}
req = urllib.request.Request(
    "http://127.0.0.1:8001/v1/chat/completions",
    data=json.dumps(test_payload).encode("utf-8"),
    headers={"Content-Type": "application/json", **local_auth_headers},
)
with urllib.request.urlopen(req, timeout=30) as resp:
    warmup_res = json.loads(resp.read().decode("utf-8"))
    print("Warmup kết quả với Tool Calling:", warmup_res["choices"][0]["message"].get("role"))

del local_auth_headers, vllm_api_key
print("CELL 2 SẴN SÀNG!")

# %% [CELL 3] Mở ngrok HTTPS Tunnel với Traffic Policy 2 lớp trên NGROK_DOMAIN tĩnh (W4-D2)
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
            "Production vLLM yêu cầu NGROK_DOMAIN tĩnh để gắn Traffic Policy bảo vệ 2 lớp (W4-D2)."
        )
    if require_two_layer and not clean_tunnel_token:
        raise RuntimeError(
            "Production vLLM yêu cầu NGROK_TUNNEL_TOKEN trong Colab Secrets để chặn request lạ tại biên ngrok (W4-D2)."
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
print("🎉 TUNNEL NGROK 2 LỚP ĐÃ MỞ THÀNH CÔNG:")
print(f"👉 Public URL: {public_url}")
print(f"👉 Endpoint API OpenAI: {endpoint_url}")
print("🔒 Bảo vệ biên (Lớp 1): Traffic Policy kiểm X-RetailOps-Tunnel-Token trên /v1/*")
print("🔒 Bảo vệ ứng dụng (Lớp 2): vLLM --api-key (Bearer token)")
print("=" * 70)
print("\nĐể cập nhật endpoint lên EC2 an toàn (qua AWS SSM):")
print(
    f"1. Ghi giá trị TRỰC TIẾP vào /opt/retailops/api.env:\n"
    f"   - Cập nhật endpoint & model:\n"
    f"     RETAILOPS_API_ENABLED=true\n"
    f"     RETAILOPS_API_ENDPOINT={endpoint_url}\n"
    f"     RETAILOPS_API_MODEL={MODEL}\n"
    f"   - SỬA dòng RETAILOPS_API_KEY có sẵn trong api.env (KHÔNG thêm dòng mới):\n"
    f"     RETAILOPS_API_KEY=<giá trị RETAILOPS_API_KEY trong Colab Secrets>\n"
    f"   - Thêm mới (hoặc cập nhật nếu đã có):\n"
    f"     RETAILOPS_API_TUNNEL_TOKEN=<giá trị NGROK_TUNNEL_TOKEN trong Colab Secrets>\n"
    f"     RETAILOPS_CUSTOMER_REF_KEY=<khóa HMAC bí mật tối thiểu 16 ký tự>\n"
    f"   - Lưu ý: KHÔNG dùng biến dạng *_FILE trên EC2 (container web không mount thư mục secret ngoài; đặt cả biến trực tiếp lẫn *_FILE sẽ báo lỗi 'Set only one of...')."
)
print(
    '2. Chạy:\n'
    '   sudo /opt/retailops/rollout-public-web.sh "<RETAILOPS_IMAGE trong deployed.env>"'
)
print("=" * 70)
