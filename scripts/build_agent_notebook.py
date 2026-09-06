"""Deterministically embed reviewed repository source into a standalone Colab notebook.

Run from any directory: python scripts/build_agent_notebook.py [--check]
The bundle is inspectable through the source manifest, includes no credentials.
"""
import argparse
import base64
import hashlib
import json
import textwrap
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cell(kind, source, identity):
    result = {'cell_type': kind, 'id': identity, 'metadata': {},
              'source': textwrap.dedent(source).strip().splitlines(keepends=True)}
    if kind == 'code':
        compile(textwrap.dedent(source).strip(), identity, 'exec')
        result.update(execution_count=None, outputs=[])
    return result


def build():
    names = ['retailops_baseline.py', 'inference_proxy.py', 'retailops_agent.py', 'agent_protocol.py',
             'retailops_api.py', 'retailops_public.py', 'retailops_providers.py', 'retailops_tools.py', 'retailops_conversation.py', 'data/products.json',
             'data/smoke.jsonl', 'notebooks/agent_smoke.py', 'notebooks/colab_runtime.py']
    names += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'tests').glob('*.py'))]
    names += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'web').glob('*')) if p.is_file()]
    files = {name: (ROOT/name).read_text(encoding='utf-8') for name in names}
    raw = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    encoded = base64.b64encode(zlib.compress(raw, 9)).decode()
    digest = hashlib.sha256(raw).hexdigest()
    bootstrap = f'''
import base64, hashlib, json, os, subprocess, sys, zlib
from pathlib import Path
BASE = Path('/content/retailops_agent')
if globals().get('_agent_proxy') is not None:
    raise RuntimeError('Dừng proxy bằng ô cuối trước khi chạy lại ô source.')
SOURCE_BUNDLE_SHA256 = {digest!r}
_raw = zlib.decompress(base64.b64decode({encoded!r}))
assert hashlib.sha256(_raw).hexdigest() == SOURCE_BUNDLE_SHA256
_sources = json.loads(_raw)
BASE.mkdir(parents=True, exist_ok=True)
for _name, _source in _sources.items():
    _dest = (BASE / _name).resolve()
    if not _dest.is_relative_to(BASE.resolve()):
        raise RuntimeError('Invalid embedded source path')
    _dest.parent.mkdir(parents=True, exist_ok=True)
    _dest.write_text(_source, encoding='utf-8')
for _name in ('agent_protocol', 'retailops_agent', 'retailops_tools', 'retailops_providers', 'retailops_public', 'retailops_api', 'retailops_conversation', 'retailops_baseline', 'inference_proxy'):
    sys.modules.pop(_name, None)
if str(BASE) in sys.path: sys.path.remove(str(BASE))
sys.path.insert(0, str(BASE))
ARTIFACTS = BASE / 'artifacts'
ARTIFACTS.mkdir(exist_ok=True)
_manifest = {{'bundle_sha256': SOURCE_BUNDLE_SHA256, 'files': {{k: hashlib.sha256(v.encode()).hexdigest() for k, v in _sources.items()}}}}
(ARTIFACTS / 'source-manifest.json').write_text(json.dumps(_manifest, indent=2), encoding='utf-8')
subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'], cwd=BASE, check=True)
print('AGENT_SOURCE_READY: không cần upload ZIP.')
'''
    cells = [
        cell('markdown', '''# RetailOps 0.4 — Qwen hội thoại và gọi công cụ
        Notebook tự chứa source; dành cho phiên thử có người theo dõi trên Colab L4.
        Chạy từng ô, không Run all (ô cuối dừng proxy). Chọn GPU L4 nếu được cấp.
        Trước khi đổi notebook, tải báo cáo cũ và dừng tunnel/proxy của notebook cũ.
        Đây là bài kiểm tra agent mới, không thay thế báo cáo baseline 24 mẫu.
        Chỉ dùng dữ liệu giả lập. Token nằm trong Colab Secrets, không dán vào code/output.
        ''', 'intro'),
        cell('markdown', '## 1. Chuẩn bị source và chạy test không cần model', 'source-heading'),
        cell('code', bootstrap, 'source'),
        cell('markdown', '## 2. Cài/kiểm tra Ollama và nạp Qwen\nÔ này có thể mất vài phút ở lần đầu. Dùng lại model/server nếu còn trong runtime.', 'runtime-heading'),
        cell('code', '''
        _agent_runtime_state = globals().setdefault('_agent_runtime_state', {})
        MODEL = 'qwen3.5:4b'
        exec(compile((BASE/'notebooks/colab_runtime.py').read_text(), 'colab_runtime.py', 'exec'))
        OLLAMA_ENV, LOCAL_HTTP = setup_colab_runtime(BASE, _agent_runtime_state, model=MODEL)
        from retailops_agent import LocalAgent
        from retailops_baseline import ModelConfig
        from agent_protocol import PROTOCOL, assistant_message
        LOCAL_AGENT = LocalAgent(ModelConfig(model=MODEL, timeout_s=180))
        print('Làm nóng context agent 8192; lượt đầu có thể chậm…', flush=True)
        _warm = LOCAL_AGENT.chat([{'role': 'user', 'content': 'Xin chào!'}], False, 180)
        print('Qwen:', assistant_message(_warm)['content'])
        print('AGENT_MODEL_READY:', MODEL, PROTOCOL)
        print(subprocess.run(['ollama', 'ps'], env=OLLAMA_ENV, text=True, capture_output=True, check=True).stdout)
        ''', 'runtime'),
        cell('markdown', '''## 3. Thử hội thoại thật ngay trong Colab
        Dùng cùng vòng agent và công cụ như EC2, với database tạm riêng. Không đổi đơn trên EC2.
        Báo cáo ghi câu trả lời thật, các tool và latency. Nếu FAIL/REVIEW, tải JSON để phân tích;
        không gọi đó là kết quả đạt. Đọc câu trả lời để phát hiện thông tin model tự thêm.
        ''', 'smoke-heading'),
        cell('code', '''
        exec(compile((BASE/'notebooks/agent_smoke.py').read_text(), 'agent_smoke.py', 'exec'))
        AGENT_REPORT = run_live_smoke(LOCAL_AGENT, ARTIFACTS)
        print(subprocess.run(['ollama', 'ps'], env=OLLAMA_ENV, text=True, capture_output=True, check=True).stdout)
        ''', 'smoke'),
        cell('markdown', '''## 4. Mở proxy mới và tunnel để EC2 kết nối
        Colab Secrets (biểu tượng chìa khóa) cần `NGROK_AUTHTOKEN` và `RETAILOPS_INFERENCE_TOKEN`.
        Bật quyền đọc cho notebook. Dùng cùng inference token đã cấu hình trên EC2.
        Proxy agent chạy ở cổng nội bộ 8002. Ô này chỉ in URL và hostname, không in token.
        ''', 'tunnel-heading'),
        cell('code', '''
        import hmac, re, threading, urllib.request
        from urllib.parse import urlsplit
        from google.colab import userdata
        from inference_proxy import create_server
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', 'pyngrok>=7,<8'], check=True)
        from pyngrok import ngrok
        try:
            _inference_token = userdata.get('RETAILOPS_INFERENCE_TOKEN')
            _ngrok_token = userdata.get('NGROK_AUTHTOKEN')
        except Exception:
            raise RuntimeError('Thiếu secret hoặc chưa cấp quyền: NGROK_AUTHTOKEN và RETAILOPS_INFERENCE_TOKEN.') from None
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', _inference_token or ''):
            raise RuntimeError('Inference token phải là chuỗi URL-safe 32–128 ký tự, giống token trên EC2.')
        if globals().get('_agent_tunnel') is not None:
            ngrok.disconnect(_agent_tunnel.public_url)
            _agent_tunnel = None
        if globals().get('_agent_proxy') is not None:
            _agent_proxy.shutdown(); _agent_proxy.server_close(); _agent_proxy = None
        _agent_proxy = create_server(ModelConfig(model=MODEL), _inference_token, port=8002)
        threading.Thread(target=_agent_proxy.serve_forever, daemon=True).start()
        try:
            _request = urllib.request.Request('http://127.0.0.1:8002/agent/identity',
                headers={'Authorization': 'Bearer ' + _inference_token})
            with LOCAL_HTTP.open(_request, timeout=15) as _response:
                _proxy_identity = json.load(_response)
            if _proxy_identity.get('agent_protocol') != PROTOCOL:
                raise RuntimeError('Agent proxy version mismatch')
            ngrok.set_auth_token(_ngrok_token)
            _agent_tunnel = ngrok.connect(addr='http://127.0.0.1:8002', proto='http', bind_tls=True, inspect=False)
            _public = urlsplit(_agent_tunnel.public_url)
            if _public.scheme != 'https' or not _public.hostname:
                raise RuntimeError('HTTPS tunnel required')
        except Exception:
            if globals().get('_agent_tunnel') is not None:
                ngrok.disconnect(_agent_tunnel.public_url); _agent_tunnel = None
            _agent_proxy.shutdown(); _agent_proxy.server_close(); _agent_proxy = None
            raise RuntimeError('Chưa mở được proxy/tunnel. Kiểm tra secrets và dừng tunnel ở notebook cũ; không gửi token qua chat.') from None
        finally:
            del _ngrok_token, _inference_token
        print('AGENT_PROXY_READY:', PROTOCOL)
        print('RETAILOPS_MODEL_URL=' + _agent_tunnel.public_url)
        print('RETAILOPS_ALLOWED_HOST=' + _public.hostname)
        print('Cập nhật hai giá trị này trong inference.env trên EC2 rồi tạo lại container API/web đang dùng custom model.')
        ''', 'tunnel'),
        cell('markdown', '## 5. Tải báo cáo\nChỉ xuất báo cáo agent, thông tin GPU/runtime và manifest; không xuất token hoặc file cấu hình.', 'export-heading'),
        cell('code', '''
        import zipfile
        from google.colab import files
        _export = BASE / 'retailops-agent-results.zip'
        _names = ['gpu.txt', 'ollama-version.json', 'source-manifest.json']
        _reports = sorted(ARTIFACTS.glob('agent-smoke-*.json'))
        with zipfile.ZipFile(_export, 'w', compression=zipfile.ZIP_DEFLATED) as _zip:
            for _path in [ARTIFACTS/n for n in _names] + _reports:
                if _path.is_file(): _zip.write(_path, arcname=_path.name)
        files.download(str(_export))
        ''', 'export'),
        cell('markdown', '## 6. Dừng khi kết thúc phiên\nTải báo cáo trước. Sau ô này, chọn Runtime → Disconnect and delete runtime để trả GPU.', 'stop-heading'),
        cell('code', '''
        if globals().get('_agent_tunnel') is not None:
            ngrok.disconnect(_agent_tunnel.public_url); _agent_tunnel = None
        if globals().get('_agent_proxy') is not None:
            _agent_proxy.shutdown(); _agent_proxy.server_close(); _agent_proxy = None
        if 'OLLAMA_ENV' in globals():
            subprocess.run(['ollama', 'stop', MODEL], env=OLLAMA_ENV, check=False)
        _process = globals().get('_agent_runtime_state', {}).get('process')
        if _process is not None and _process.poll() is None:
            _process.terminate()
            try: _process.wait(timeout=10)
            except subprocess.TimeoutExpired: _process.kill(); _process.wait(timeout=5)
        print('Proxy/tunnel đã dừng. Chọn Disconnect and delete runtime để trả GPU.')
        ''', 'stop'),
    ]
    return json.dumps({'cells': cells, 'metadata': {'accelerator': 'GPU', 'colab': {'provenance': []},
        'kernelspec': {'display_name': 'Python 3', 'name': 'python3'},
        'language_info': {'name': 'python', 'version': '3.11'}}, 'nbformat': 4, 'nbformat_minor': 5}, ensure_ascii=False, indent=1)+'\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    target = ROOT/'notebooks/colab_agent.ipynb'; content = build()
    if args.check:
        if not target.is_file() or target.read_text(encoding='utf-8') != content:
            raise SystemExit('Notebook is stale: run python scripts/build_agent_notebook.py')
        print('AGENT_NOTEBOOK_SOURCE_SYNC_OK')
    else:
        target.write_text(content, encoding='utf-8'); print(target.relative_to(ROOT))
