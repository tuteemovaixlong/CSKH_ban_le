"""Colab setup cell source; embedded by scripts/build_colab_notebook.py.

No setup executes when imported. This helper only manages a local Ollama server.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def setup_colab_runtime(base, state, model="qwen3.5:4b"):
    base = Path(base)
    artifacts = base / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    if not shutil.which("nvidia-smi"):
        raise RuntimeError("Chưa có GPU. Chọn Runtime > Change runtime type > T4 GPU, rồi chạy lại từ ô đầu.")
    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv"],
        text=True, capture_output=True,
    )
    if gpu.returncode or not gpu.stdout.strip():
        raise RuntimeError("Không đọc được GPU. Kiểm tra runtime Colab và chạy lại nvidia-smi.")
    print(gpu.stdout, flush=True)
    (artifacts / "gpu.txt").write_text(gpu.stdout, encoding="utf-8")
    if not shutil.which("ollama"):
        privileged = [] if os.geteuid() == 0 else ["sudo"]
        print("Cài curl và zstd cho bộ cài Ollama…", flush=True)
        subprocess.run(privileged + ["apt-get", "update", "-qq"], check=True)
        subprocess.run(privileged + ["apt-get", "install", "-y", "-qq", "curl", "zstd", "ca-certificates"], check=True)
        installer = base / "ollama-install.sh"
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                        "--connect-timeout", "20", "--max-time", "120",
                        "https://ollama.com/install.sh", "--output", str(installer)], check=True)
        subprocess.run(["sh", str(installer)], check=True)

    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_NO_CLOUD="1",
               OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1", RETAILOPS_MODEL=model,
               RETAILOPS_MODEL_URL="http://127.0.0.1:11434", RETAILOPS_OUTPUT=str(artifacts))
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def probe():
        try:
            with http.open("http://127.0.0.1:11434/api/version", timeout=2) as response:
                data = json.load(response)
            return data if isinstance(data, dict) and data.get("version") else None
        except (OSError, ValueError):
            return None

    identity = probe()
    log_path = base / "ollama-server.log"
    if identity:
        print("Ollama đã sẵn sàng; dùng lại server hiện có.", flush=True)
    else:
        process = state.get("process")
        if process is None or process.poll() is not None:
            # The child owns its descriptor; no open log handle remains in the notebook.
            with log_path.open("ab") as stream:
                process = subprocess.Popen(["ollama", "serve"], env=env,
                                           stdout=stream, stderr=subprocess.STDOUT)
            state["process"] = process
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            identity = probe()
            if identity:
                break
            time.sleep(0.5)
        if not identity:
            details = log_path.read_text(errors="replace")[-4000:] if log_path.exists() else "Không có log server."
            raise RuntimeError("Ollama chưa sẵn sàng. Log server:\n" + details)
    print("Ollama version:", identity["version"], flush=True)
    (artifacts / "ollama-version.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    print("Đang tải/kiểm tra model " + model + "…", flush=True)
    subprocess.run(["ollama", "pull", model], env=env, check=True)
    print("MODEL_READY:", model, flush=True)
    return env, http
