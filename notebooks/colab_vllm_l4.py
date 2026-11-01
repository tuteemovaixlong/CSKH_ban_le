# ==============================================================================
# RETAILOPS 2026 — Gemma-4-12B-Agentic trên Google Colab (GPU L4)
# Model: yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2
# Hỗ trợ: FP8 Native (Khuyên dùng cho L4 Ada Lovelace) hoặc BitsAndBytes 4-bit
# ==============================================================================
# Hướng dẫn sử dụng:
# 1. Chọn Runtime -> Change runtime type -> L4 GPU.
# 2. Điền Colab Secrets: NGROK_AUTHTOKEN (có thể nhiều token cách nhau bởi dấu phẩy),
#    và tùy chọn NGROK_DOMAIN nếu dùng domain ngrok tĩnh.
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
print(f"1. Cập nhật RETAILOPS_API_ENDPOINT={endpoint_url} (và RETAILOPS_API_MODEL={MODEL}) trong /opt/retailops/api.env")
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
