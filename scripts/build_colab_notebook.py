"""Regenerate the self-contained Colab notebook from the repository sources.

No archive upload, GitHub access token, or public copy of a private repo needed.
Run from any directory: python scripts/build_colab_notebook.py
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = ["retailops_baseline.py", "inference_proxy.py", "backup_state.py",
         "data/smoke.jsonl", "tests/test_baseline.py", "tests/test_remote.py", "LICENSE"]


def cell(kind, source, name):
    entry = {"cell_type": kind, "id": name, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        entry.update(execution_count=None, outputs=[])
    return entry


def build():
    files = {path: (ROOT / path).read_text(encoding="utf-8") for path in PATHS}
    hashes = {path: hashlib.sha256(content.encode()).hexdigest() for path, content in files.items()}
    # Plain Python string literals keep the notebook inspectable and executable.
    literals = "SOURCE_FILES = {\n" + "".join("    " + repr(path) + ": " + repr(content) + ",\n" for path, content in files.items()) + "}\n"
    bootstrap = '''import hashlib, json, os, subprocess, sys
from pathlib import Path

BASE = Path('/content/retailops_colab_direct')
BASE.mkdir(parents=True, exist_ok=True)
'''
    bootstrap += literals + "SOURCE_SHA256 = " + repr(hashes) + "\n"
    bootstrap += '''for relative, content in SOURCE_FILES.items():
    if hashlib.sha256(content.encode()).hexdigest() != SOURCE_SHA256[relative]:
        raise RuntimeError('Embedded source hash mismatch: ' + relative)
    destination = BASE / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding='utf-8')
os.chdir(BASE)
(BASE / 'artifacts').mkdir(exist_ok=True)
(BASE / 'artifacts' / 'source-manifest.json').write_text(
    json.dumps(SOURCE_SHA256, indent=2), encoding='utf-8')
subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], check=True)
print('SOURCE_READY: không cần upload ZIP.')
'''
    runtime = (ROOT / "notebooks/colab_runtime.py").read_text(encoding="utf-8") + '''
MODEL = 'qwen3.5:4b'
runtime_state = globals().setdefault('_retailops_runtime_state', {})
OLLAMA_ENV, local_http = setup_colab_runtime(BASE, runtime_state, MODEL)
'''
    predict = '''command = [sys.executable, 'retailops_baseline.py', '--model', MODEL,
           'predict', '--text', 'Hủy đơn O-101 vì tôi đặt nhầm.']
result = subprocess.run(command, env=OLLAMA_ENV, text=True, capture_output=True)
if result.stdout:
    print(result.stdout)
if result.stderr:
    print(result.stderr)
result.check_returncode()
subprocess.run(['ollama', 'ps'], env=OLLAMA_ENV, check=True)
'''
    evaluation = '''identity_text = subprocess.check_output(
    [sys.executable, 'retailops_baseline.py', '--model', MODEL, 'doctor'],
    env=OLLAMA_ENV, text=True)
(BASE / 'artifacts' / 'model-identity.json').write_text(identity_text, encoding='utf-8')
print(identity_text)
subprocess.run([sys.executable, 'retailops_baseline.py', '--model', MODEL,
                'evaluate', '--cases', 'data/smoke.jsonl'], env=OLLAMA_ENV, check=True)
subprocess.run(['ollama', 'ps'], env=OLLAMA_ENV, check=True)
'''
    # Retain optional authenticated tunnel behavior, with an independent opt-in.
    tunnel = '''ENABLE_REMOTE_EXPERIMENT = False
if ENABLE_REMOTE_EXPERIMENT:
    from google.colab import userdata
    import re
    from urllib.parse import urlparse
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyngrok>=7,<8'], check=True)
    from pyngrok import ngrok
    token = userdata.get('RETAILOPS_INFERENCE_TOKEN')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise ValueError('Inference token phải có 32–128 ký tự URL-safe')
    if 'proxy_process' in globals() and proxy_process.poll() is None:
        raise RuntimeError('Proxy đang chạy; dùng URL đã có hoặc chạy ô dừng trước.')
    proxy_env = dict(OLLAMA_ENV, RETAILOPS_INFERENCE_TOKEN=token)
    with (BASE / 'proxy-server.log').open('ab') as log:
        proxy_process = subprocess.Popen([sys.executable, 'inference_proxy.py'], env=proxy_env,
                                        stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        if proxy_process.poll() is not None:
            raise RuntimeError('Proxy không khởi động được; kiểm tra proxy-server.log.')
        try:
            req = urllib.request.Request('http://127.0.0.1:8001/healthz',
                                          headers={'Authorization': 'Bearer ' + token})
            with local_http.open(req, timeout=3) as response:
                json.load(response)
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise RuntimeError('Proxy/model chưa sẵn sàng; chưa mở tunnel.')
    ngrok.set_auth_token(userdata.get('NGROK_AUTHTOKEN'))
    tunnel = ngrok.connect(addr='http://127.0.0.1:8001', proto='http', bind_tls=True, inspect=False)
    if not tunnel.public_url.startswith('https://'):
        ngrok.disconnect(tunnel.public_url)
        raise RuntimeError('Cần HTTPS endpoint')
    print('RETAILOPS_MODEL_URL=' + tunnel.public_url)
    print('RETAILOPS_ALLOWED_HOST=' + urlparse(tunnel.public_url).hostname)
    print('Điền hai giá trị trên và cùng inference token vào inference.env trên EC2.')
else:
    print('Tunnel tắt. Baseline chạy trực tiếp trong notebook.')
'''
    export = '''from google.colab import files
import shutil, uuid
sys.path.insert(0, str(BASE)) if str(BASE) not in sys.path else None
from backup_state import backup
export_dir = Path('/content') / ('retailops-results-' + uuid.uuid4().hex[:8])
export_dir.mkdir()
source_db = BASE / 'artifacts' / 'runs.sqlite3'
if source_db.exists():
    backup(source_db, export_dir / 'runs.sqlite3')
for pattern in ('report-*.json', 'model-identity.json', 'gpu.txt',
                'source-manifest.json', 'ollama-version.json'):
    for source in (BASE / 'artifacts').glob(pattern):
        shutil.copy2(source, export_dir / source.name)
files.download(shutil.make_archive(str(export_dir), 'zip', export_dir))
'''
    stop = '''if 'tunnel' in globals():
    ngrok.disconnect(tunnel.public_url)
processes = [globals().get('proxy_process'),
             globals().get('_retailops_runtime_state', {}).get('process')]
for process in processes:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
print('Đã dừng tiến trình do notebook này tạo. Dùng Disconnect and delete runtime khi xong.')
'''
    cells = [
        cell('markdown', '# RetailOps — chạy trực tiếp trên Colab\n\nChọn **Runtime → Change runtime type → T4 GPU**. Chạy từng ô; không Run all.\nKhông cần upload ZIP hoặc token GitHub. Ô đầu chứa chính source của repository và kiểm tra SHA-256 trước khi ghi.\nChỉ dùng dữ liệu giả lập; yêu cầu và output được lưu nguyên văn.\n\nBản này sửa bootstrap và thêm test một câu trước evaluation. Chưa có traceback từ phiên lỗi của bạn và chưa xác nhận inference GPU thật.\n', 'intro'),
        cell('code', bootstrap, 'source'),
        cell('markdown', '## 1. Chuẩn bị GPU, Ollama và model\nCài `zstd` khi cần; dùng lại Ollama đang trả lời trên loopback. Không dùng `pkill`.\nRuntime version, GPU và model digest được lưu để tái lập.\n', 'runtime-label'),
        cell('code', runtime, 'runtime'),
        cell('markdown', '## 2. Thử một câu\nKết quả là JSON đề xuất, chưa có thao tác hủy đơn. Xem `ollama ps` để kiểm tra GPU thực tế.\n', 'predict-label'),
        cell('code', predict, 'predict'),
        cell('markdown', '## 3. Chạy 24 mẫu và ghi báo cáo\n`FAIL` có thể là lỗi hiểu yêu cầu của model. Đây là smoke test tổng hợp, không phải benchmark độc lập.\nEvaluation luôn bỏ qua cache kết quả.\n', 'evaluation-label'),
        cell('code', evaluation, 'evaluation'),
        cell('markdown', '## 4. Ngrok tùy chọn — tắt mặc định\nChỉ bật khi cách dùng phù hợp với tài khoản Colab. Tạo Colab Secrets `NGROK_AUTHTOKEN` và `RETAILOPS_INFERENCE_TOKEN`; cấp quyền notebook. Token inference 32–128 ký tự URL-safe, dùng chung với EC2, không in ra output.\n[Colab FAQ](https://research.google.com/colaboratory/faq.html) — không có anti-idle hoặc tự reconnect.\n', 'tunnel-label'),
        cell('code', tunnel, 'tunnel'),
        cell('markdown', '## 5. Tải báo cáo và log SQLite\nTải trước khi kết thúc runtime. Dùng SQLite backup để giữ bản ghi trong WAL.\n', 'export-label'),
        cell('code', export, 'export'),
        cell('markdown', '## 6. Dừng khi đã xong\nÔ này dừng model server và proxy do notebook tạo.\n', 'stop-label'),
        cell('code', stop, 'stop'),
    ]
    notebook = {'nbformat': 4, 'nbformat_minor': 5, 'metadata': {
        'accelerator': 'GPU', 'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
        'language_info': {'name': 'python'}, 'colab': {'name': 'RetailOps_Colab_Direct.ipynb', 'provenance': []}}, 'cells': cells}
    path = ROOT / 'notebooks/colab_inference.ipynb'
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(path)


if __name__ == '__main__':
    build()
