"""Build the standalone RetailOps Colab agent notebook.

The generated notebook has one linear startup path:
1. bootstrap reviewed source + dependencies,
2. start Ollama/Qwen and LocalAgent,
3. start the v2 inference proxy + ngrok.

Run: python scripts/build_agent_notebook.py [--check]
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
    source = textwrap.dedent(source).strip()
    result = {
        "cell_type": kind,
        "id": identity,
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }
    if kind == "code":
        compile(source, identity, "exec")
        result.update(execution_count=None, outputs=[])
    return result


def build():
    names = [
        "requirements-graph.txt",
        "retailops_baseline.py",
        "inference_proxy.py",
        "retailops_agent.py",
        "agent_protocol.py",
        "retailops_api.py",
        "retailops_public.py",
        "retailops_providers.py",
        "retailops_tools.py",
        "retailops_conversation.py",
        "data/products.json",
        "data/smoke.jsonl",
        "notebooks/agent_smoke.py",
        "notebooks/colab_runtime.py",
    ]
    names += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "tests").glob("*.py"))]
    names += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "retailops").rglob("*.py"))]
    names += [
        p.relative_to(ROOT).as_posix()
        for p in sorted((ROOT / "web").glob("*"))
        if p.is_file()
    ]
    names += [
        p.relative_to(ROOT).as_posix()
        for p in sorted((ROOT / "data/knowledge").glob("*.md"))
    ]

    files = {name: (ROOT / name).read_text(encoding="utf-8") for name in names}
    raw = json.dumps(
        files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    encoded = base64.b64encode(zlib.compress(raw, 9)).decode()
    digest = hashlib.sha256(raw).hexdigest()

    bootstrap = fr'''
    # CELL 1 — Bootstrap source + dependencies (fresh runtime: run this first)
    import base64, hashlib, json, re, subprocess, sys, zlib
    from pathlib import Path

    BASE = Path('/content/retailops_agent')
    ARTIFACTS = BASE / 'artifacts'
    SOURCE_BUNDLE_SHA256 = {digest!r}

    # A rerun of Cell 1 is allowed only after Cell 3 has been stopped.
    if globals().get('_agent_proxy') is not None:
        raise RuntimeError('Proxy đang chạy. Chạy cell STOP trước, rồi mới chạy lại Cell 1.')

    print('Python:', sys.version.split()[0])
    print('Preparing reviewed RetailOps source…', flush=True)

    _raw = zlib.decompress(base64.b64decode({encoded!r}))
    if hashlib.sha256(_raw).hexdigest() != SOURCE_BUNDLE_SHA256:
        raise RuntimeError('Source bundle checksum mismatch.')
    _sources = json.loads(_raw)

    BASE.mkdir(parents=True, exist_ok=True)
    for _name, _source in _sources.items():
        _dest = (BASE / _name).resolve()
        if not _dest.is_relative_to(BASE.resolve()):
            raise RuntimeError('Invalid embedded source path')
        _dest.parent.mkdir(parents=True, exist_ok=True)
        _dest.write_text(_source, encoding='utf-8')

    # Never reuse v1 modules from a previous notebook execution.
    for _name in (
        'agent_protocol', 'retailops_agent', 'retailops_tools',
        'retailops_providers', 'retailops_public', 'retailops_api',
        'retailops_conversation', 'retailops_baseline', 'inference_proxy',
    ):
        sys.modules.pop(_name, None)
    for _name in list(sys.modules):
        if _name == 'retailops' or _name.startswith('retailops.'):
            sys.modules.pop(_name, None)
    if str(BASE) in sys.path:
        sys.path.remove(str(BASE))
    sys.path.insert(0, str(BASE))

    ARTIFACTS.mkdir(exist_ok=True)
    _manifest = {{
        'bundle_sha256': SOURCE_BUNDLE_SHA256,
        'files': {{k: hashlib.sha256(v.encode()).hexdigest() for k, v in _sources.items()}},
    }}
    (ARTIFACTS / 'source-manifest.json').write_text(
        json.dumps(_manifest, indent=2), encoding='utf-8'
    )

    # requirements-graph.txt is hash-locked for CPython 3.11/3.12.
    # Colab can move to a newer CPython before the repository lock is regenerated.
    # For 3.11/3.12 keep strict --require-hashes. For newer runtimes keep exact
    # versions + binary-only wheels, and reject any non-exact requirement line.
    _lock = BASE / 'requirements-graph.txt'
    _pip = [sys.executable, '-m', 'pip', 'install', '--only-binary=:all:']
    if sys.version_info[:2] in ((3, 11), (3, 12)):
        _pip += ['--require-hashes', '-r', str(_lock)]
        _dependency_mode = 'hash-locked'
    else:
        _compat = Path('/tmp/retailops-requirements-runtime.txt')
        _lines = []
        for _line in _lock.read_text(encoding='utf-8').splitlines():
            _line = _line.strip()
            if not _line or _line.startswith('#'):
                continue
            _line = re.sub(r'\s+--hash=sha256:[0-9a-f]{{64}}', '', _line).strip()
            if not re.fullmatch(r'[A-Za-z0-9_.-]+==[^\s]+', _line):
                raise RuntimeError('Non-exact requirement in compatibility mode: ' + _line)
            _lines.append(_line)
        _compat.write_text('\n'.join(_lines) + '\n', encoding='utf-8')
        _pip += ['-r', str(_compat)]
        _dependency_mode = 'exact-binary-compat'

    print('Dependency mode:', _dependency_mode, flush=True)
    subprocess.run(_pip, check=True)

    from agent_protocol import PROTOCOL, TOOLS
    _tool_names = {{item['function']['name'] for item in TOOLS}}
    if PROTOCOL != 'retailops-agent-v2':
        raise RuntimeError('Expected retailops-agent-v2, got ' + str(PROTOCOL))
    if 'search_knowledge' not in _tool_names:
        raise RuntimeError('search_knowledge is missing from the v2 tool contract.')

    print('CELL_1_READY')
    print('SOURCE_BUNDLE_SHA256=' + SOURCE_BUNDLE_SHA256)
    print('AGENT_PROTOCOL=' + PROTOCOL)
    print('SEARCH_KNOWLEDGE_TOOL=True')
    '''

    runtime = '''
    # CELL 2 — Start/reuse Ollama + Qwen and create LocalAgent v2
    import subprocess

    if 'BASE' not in globals():
        raise RuntimeError('Chạy Cell 1 trước.')

    _agent_runtime_state = globals().setdefault('_agent_runtime_state', {})
    MODEL = 'qwen3.5:4b'

    exec(compile(
        (BASE / 'notebooks/colab_runtime.py').read_text(),
        'colab_runtime.py',
        'exec',
    ))
    OLLAMA_ENV, LOCAL_HTTP = setup_colab_runtime(
        BASE, _agent_runtime_state, model=MODEL
    )

    from retailops_agent import LocalAgent
    from retailops_baseline import ModelConfig
    from agent_protocol import PROTOCOL, TOOLS, assistant_message

    if PROTOCOL != 'retailops-agent-v2':
        raise RuntimeError('Cell 1 chưa nạp agent v2.')
    if not any(x['function']['name'] == 'search_knowledge' for x in TOOLS):
        raise RuntimeError('RAG tool contract chưa sẵn sàng.')

    LOCAL_AGENT = LocalAgent(ModelConfig(model=MODEL, timeout_s=180))
    print('Warming Qwen context; first run can take a little longer…', flush=True)
    _warm = LOCAL_AGENT.chat(
        [{'role': 'user', 'content': 'Chỉ trả lời đúng một từ: OK'}],
        False,
        180,
    )
    print('Warmup:', assistant_message(_warm)['content'])
    print('CELL_2_READY')
    print('AGENT_MODEL_READY:', MODEL, PROTOCOL)
    print(subprocess.run(
        ['ollama', 'ps'], env=OLLAMA_ENV, text=True,
        capture_output=True, check=True,
    ).stdout)
    '''

    tunnel = '''
    # CELL 3 — Start/replace Agent Proxy v2 + HTTPS ngrok tunnel
    import json, re, subprocess, sys, threading, time, urllib.request
    from urllib.parse import urlsplit
    from google.colab import userdata

    if 'LOCAL_AGENT' not in globals() or 'LOCAL_HTTP' not in globals():
        raise RuntimeError('Chạy Cell 2 trước.')

    from agent_protocol import PROTOCOL
    from retailops_baseline import ModelConfig
    from inference_proxy import create_server

    if PROTOCOL != 'retailops-agent-v2':
        raise RuntimeError('Agent protocol không phải v2.')

    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet', 'pyngrok>=7,<8'],
        check=True,
    )
    from pyngrok import ngrok

    try:
        _inference_token = userdata.get('RETAILOPS_INFERENCE_TOKEN')
        _ngrok_token = userdata.get('NGROK_AUTHTOKEN')
    except Exception:
        raise RuntimeError(
            'Thiếu hoặc chưa cấp quyền Colab Secrets: '
            'RETAILOPS_INFERENCE_TOKEN và NGROK_AUTHTOKEN.'
        ) from None
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', _inference_token or ''):
        raise RuntimeError('RETAILOPS_INFERENCE_TOKEN không đúng định dạng.')

    # Cell 3 is deliberately rerunnable: it replaces only proxy/tunnel state.
    _old_tunnel = globals().get('_agent_tunnel')
    if _old_tunnel is not None:
        try:
            ngrok.disconnect(_old_tunnel.public_url)
        except Exception as _exc:
            print('Old tunnel stop warning:', type(_exc).__name__)
        _agent_tunnel = None

    _old_proxy = globals().get('_agent_proxy')
    if _old_proxy is not None:
        try:
            _old_proxy.shutdown()
        finally:
            try:
                _old_proxy.server_close()
            except Exception:
                pass
        _agent_proxy = None
    time.sleep(0.5)

    _agent_proxy = create_server(
        ModelConfig(model=MODEL, timeout_s=180),
        _inference_token,
        port=8002,
    )
    _agent_proxy_thread = threading.Thread(
        target=_agent_proxy.serve_forever,
        daemon=True,
        name='retailops-agent-proxy-v2',
    )
    _agent_proxy_thread.start()

    _proxy_identity = None
    _last_error = None
    for _attempt in range(20):
        try:
            _request = urllib.request.Request(
                'http://127.0.0.1:8002/agent/identity',
                headers={'Authorization': 'Bearer ' + _inference_token},
            )
            with LOCAL_HTTP.open(_request, timeout=5) as _response:
                _proxy_identity = json.load(_response)
            break
        except Exception as _exc:
            _last_error = _exc
            time.sleep(0.5)

    if _proxy_identity is None:
        _agent_proxy.shutdown(); _agent_proxy.server_close(); _agent_proxy = None
        raise RuntimeError(
            'Local proxy không sẵn sàng trên 127.0.0.1:8002: '
            + type(_last_error).__name__ + ': ' + str(_last_error)
        )
    if _proxy_identity.get('agent_protocol') != PROTOCOL:
        _agent_proxy.shutdown(); _agent_proxy.server_close(); _agent_proxy = None
        raise RuntimeError('Agent proxy protocol mismatch.')

    try:
        ngrok.set_auth_token(_ngrok_token)
        _agent_tunnel = ngrok.connect(
            addr='http://127.0.0.1:8002', proto='http',
            bind_tls=True, inspect=False,
        )
        _public = urlsplit(_agent_tunnel.public_url)
        if _public.scheme != 'https' or not _public.hostname:
            raise RuntimeError('HTTPS tunnel required')
    except Exception:
        if globals().get('_agent_tunnel') is not None:
            try:
                ngrok.disconnect(_agent_tunnel.public_url)
            except Exception:
                pass
            _agent_tunnel = None
        _agent_proxy.shutdown(); _agent_proxy.server_close(); _agent_proxy = None
        raise
    finally:
        del _ngrok_token, _inference_token

    print('CELL_3_READY')
    print('LOCAL_PROXY_V2_OK')
    print('AGENT_PROXY_READY:', PROTOCOL)
    print('RETAILOPS_MODEL_URL=' + _agent_tunnel.public_url)
    print('RETAILOPS_ALLOWED_HOST=' + _public.hostname)
    print('LOCAL_PROXY_THREAD_ALIVE=' + str(_agent_proxy_thread.is_alive()))
    print()
    print('Copy ONLY RETAILOPS_MODEL_URL and RETAILOPS_ALLOWED_HOST to EC2 inference.env.')
    '''

    diagnostics = '''
    # OPTIONAL — Diagnostics only; does not expose secrets
    import json, urllib.request

    if globals().get('_agent_proxy') is None:
        raise RuntimeError('Proxy chưa chạy. Chạy Cell 3 trước.')
    from google.colab import userdata
    _token = userdata.get('RETAILOPS_INFERENCE_TOKEN')
    _request = urllib.request.Request(
        'http://127.0.0.1:8002/agent/identity',
        headers={'Authorization': 'Bearer ' + _token},
    )
    with LOCAL_HTTP.open(_request, timeout=10) as _response:
        _identity = json.load(_response)
    del _token
    print(json.dumps({
        'agent_protocol': _identity.get('agent_protocol'),
        'model': _identity.get('model'),
        'inference_session_id': _identity.get('inference_session_id'),
        'proxy_sha256': _identity.get('proxy_sha256'),
    }, ensure_ascii=False, indent=2))
    print('DIAGNOSTICS_OK')
    '''

    stop = '''
    # STOP — End tunnel/proxy/model before disconnecting the runtime
    import subprocess

    if globals().get('_agent_tunnel') is not None:
        try:
            from pyngrok import ngrok
            ngrok.disconnect(_agent_tunnel.public_url)
        except Exception as _exc:
            print('Tunnel stop warning:', type(_exc).__name__)
        _agent_tunnel = None

    if globals().get('_agent_proxy') is not None:
        try:
            _agent_proxy.shutdown()
        finally:
            _agent_proxy.server_close()
        _agent_proxy = None

    if 'OLLAMA_ENV' in globals() and 'MODEL' in globals():
        subprocess.run(['ollama', 'stop', MODEL], env=OLLAMA_ENV, check=False)

    _process = globals().get('_agent_runtime_state', {}).get('process')
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _process.kill(); _process.wait(timeout=5)

    print('STOP_COMPLETE — now Runtime > Disconnect and delete runtime.')
    '''

    cells = [
        cell('markdown', '''
        # RetailOps Colab Agent v2 — Qwen + RAG proxy

        Notebook này có **một luồng chạy chính, chỉ 3 code cell**.

        **Runtime mới:** chạy `CELL 1 → CELL 2 → CELL 3`.

        - **CELL 1**: giải nén source đã review, cài dependency và xác nhận `retailops-agent-v2` + `search_knowledge`.
        - **CELL 2**: cài/dùng lại Ollama, tải `qwen3.5:4b`, tạo LocalAgent và warm GPU.
        - **CELL 3**: mở proxy `127.0.0.1:8002`, tự đợi proxy ready, rồi mở ngrok HTTPS.

        Nếu **chỉ tunnel/proxy chết nhưng runtime còn sống**, chạy lại **CELL 3**.
        Nếu **Ollama/model chết**, chạy lại **CELL 2 → CELL 3**.
        Nếu đã **Disconnect and delete runtime**, chạy lại **1 → 2 → 3**.

        Colab Secrets cần `NGROK_AUTHTOKEN` và `RETAILOPS_INFERENCE_TOKEN`.
        Notebook không in hai secret này. Chỉ dùng dữ liệu demo/synthetic.
        ''', 'intro'),
        cell('markdown', '## CELL 1 — Bootstrap source + dependencies', 'cell-1-heading'),
        cell('code', bootstrap, 'bootstrap'),
        cell('markdown', '## CELL 2 — Ollama + Qwen + LocalAgent v2', 'cell-2-heading'),
        cell('code', runtime, 'runtime'),
        cell('markdown', '## CELL 3 — Proxy v2 + ngrok HTTPS', 'cell-3-heading'),
        cell('code', tunnel, 'tunnel'),
        cell('markdown', '''
        ## Sau CELL 3

        Copy **chỉ** hai dòng `RETAILOPS_MODEL_URL=...` và `RETAILOPS_ALLOWED_HOST=...`
        sang `/opt/retailops/inference.env` trên EC2 rồi recreate `web` để nạp endpoint mới.
        Không gửi inference token/ngrok token qua chat.
        ''', 'after-start'),
        cell('markdown', '## OPTIONAL — Diagnostics', 'diagnostics-heading'),
        cell('code', diagnostics, 'diagnostics'),
        cell('markdown', '## STOP — Kết thúc phiên Colab', 'stop-heading'),
        cell('code', stop, 'stop'),
    ]

    return json.dumps(
        {
            'cells': cells,
            'metadata': {
                'accelerator': 'GPU',
                'colab': {'provenance': []},
                'kernelspec': {'display_name': 'Python 3', 'name': 'python3'},
                'language_info': {'name': 'python'},
            },
            'nbformat': 4,
            'nbformat_minor': 5,
        },
        ensure_ascii=False,
        indent=1,
    ) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'notebooks/colab_agent.ipynb'
    content = build()
    if args.check:
        if not target.is_file() or target.read_text(encoding='utf-8') != content:
            raise SystemExit('Notebook is stale: run python scripts/build_agent_notebook.py')
        print('AGENT_NOTEBOOK_SOURCE_SYNC_OK')
    else:
        target.write_text(content, encoding='utf-8')
        print(target.relative_to(ROOT))
