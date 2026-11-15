"""W6.4 measurement on Colab only, after W6.4.0 merges. Paste each # %% block into a cell.

Set REPO_SHA to the owner's full merged commit. Run ONE stage, inspect its report, then stop.
D4 order: examples (4) -> pilot (12, inspect gates) -> A -> B, C -> restart at 8192 for D
-> restart at 16384 for regression-w32 and regression-w4 (vision). Never edit the system between stages.
After every batch save caches, run STOP, and Disconnect and delete runtime to stop GPU billing.
Importing this module runs no commands, network, Drive mount or model.
"""

# %% [CELL 0] Pure command and shard planning (offline tested); runtime helpers
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MODEL = 'Qwen/Qwen3.5-9B'
ENDPOINT = 'http://127.0.0.1:8001/v1/chat/completions'
REPO_URL = 'https://github.com/tuteemovaixlong/CSKH_ban_le.git'
CHILDREN = []


def build_vllm_command(model_path, context_tokens, gpu_gb, *, mtp=True, max_num_seqs=6):
    if context_tokens not in (8192, 16384) or max_num_seqs < 1:
        raise ValueError('W6.4 needs 8192/16384 context and positive max_num_seqs')
    command = ['vllm', 'serve', str(model_path), '--served-model-name', MODEL,
               '--host', '127.0.0.1', '--port', '8001', '--max-model-len', str(context_tokens),
               '--gpu-memory-utilization', '0.90', '--max-num-seqs', str(max_num_seqs),
               '--reasoning-parser', 'qwen3', '--enable-auto-tool-choice', '--tool-call-parser', 'qwen3_coder',
               '--no-enable-log-requests']
    if gpu_gb < 40:
        command += ['--quantization', 'fp8']
    if mtp:
        command += ['--speculative-config', json.dumps({'method': 'qwen3_next_mtp', 'num_speculative_tokens': 2})]
    return command


def shard_case_ids(ids, shards):
    ids = sorted(ids)
    if shards < 1 or not ids or len(ids) != len(set(ids)):
        raise ValueError('shards must be positive; case IDs must be nonempty and unique')
    return [ids[i::shards] for i in range(min(shards, len(ids)))]


def runner_command(python, only_file, report, trace, dataset_args, *, agent_mode='agent', thinking='on',
                   context_tokens=16384, repeat=3, max_tokens=2048, vision=False):
    return [str(python), 'scripts/run_agent_scenarios.py', '--endpoint', ENDPOINT, '--model', MODEL,
            *map(str, dataset_args), '--only-file', str(only_file), '--out', str(report), '--trace-out', str(trace),
            '--agent-mode', agent_mode, '--thinking', thinking, '--context-tokens', str(context_tokens),
            '--repeat', str(repeat), '--knowledge', 'real', '--vision', 'on' if vision else 'off',
            '--temperature', '1.0', '--top-p', '0.95', '--top-k', '20', '--presence-penalty', '1.5',
            '--max-tokens', str(max_tokens)]


def clone_commands(repo, sha):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('REPO_SHA must be the full merged commit SHA, not a branch')
    repo = str(repo)
    return [['git', 'clone', '--no-checkout', REPO_URL, repo],
            ['git', '-C', repo, 'fetch', 'origin', sha],
            ['git', '-C', repo, 'checkout', '--detach', sha]]


def requirements_command(python, repo):
    return [str(python), '-m', 'pip', 'install', '--require-hashes',
            '-r', (Path(repo) / 'requirements-web.txt').as_posix(),
            '-r', (Path(repo) / 'requirements-postgres.txt').as_posix(),
            '-r', (Path(repo) / 'requirements-graph.txt').as_posix()]


def report_complete(path, case_ids, repeat):
    try:
        report = json.loads(Path(path).read_text(encoding='utf-8'))
        rows = report['scenarios']
        pairs = [(r['id'], r['run']) for r in rows if type(r['passed']) is bool]
        expected = {(cid, run) for cid in case_ids for run in range(1, repeat + 1)}
        return (bool(report.get('provenance')) and len(pairs) == len(rows) == len(expected)
                and set(pairs) == expected)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def quiet(command, **kwargs):
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    if result.returncode:
        # CalledProcessError would print the command/SQL. Keep all credentials out of cell output.
        raise RuntimeError('Setup command failed; inspect the package/runtime configuration') from None


def stop_process(process):
    if process is None:
        return
    # Children use a separate session; terminate its entire group including vLLM workers.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=15)


def start_server(command, api_key):
    # vLLM reads VLLM_API_KEY; it is absent from command lines and saved files.
    # Suppress startup logs as some versions echo server configuration.
    process = subprocess.Popen(command, env=dict(os.environ, VLLM_API_KEY=api_key),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    CHILDREN.append(process)
    return process


def wait_server(process, api_key, timeout=1500):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        try:
            request = urllib.request.Request('http://127.0.0.1:8001/health',
                                             headers={'Authorization': 'Bearer ' + api_key})
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(5)
    return False


def run_shards(jobs, parallel, *, repo, env):
    if parallel < 1:
        raise ValueError('P must be positive')
    pending, active, result = list(jobs), [], []
    try:
        while pending or active:
            while pending and len(active) < parallel:
                job = pending.pop(0)
                ids, report, trace, command, repeat = job
                if report_complete(report, ids, repeat):
                    result.append('skipped')
                    continue
                process = subprocess.Popen(command, cwd=repo, env=env, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, start_new_session=True)
                CHILDREN.append(process)
                active.append((process, job))
            for process, job in list(active):
                status = process.poll()
                if status is None:
                    continue
                active.remove((process, job))
                ids, report, trace, command, repeat = job
                if status or not report_complete(report, ids, repeat):
                    raise RuntimeError('Shard did not finish; its trace is saved. Resume this same stage after inspection.')
                result.append('done')
            if active:
                time.sleep(.25)
    except BaseException:
        for process in CHILDREN:
            stop_process(process)
        raise
    return result


def provision_database(python, repo, env, password):
    # Only the exact loopback disposable DB is allowed, before any DROP/CREATE operation.
    guard = ('import os,psycopg; from scripts.postgres_test_guard import require_disposable_postgres_test_target; '
             'require_disposable_postgres_test_target(os.environ["RETAILOPS_TEST_DATABASE_URL"], '
             'psycopg.conninfo.conninfo_to_dict)')
    quiet([str(python), '-c', guard], cwd=repo, env=env)
    quiet(['service', 'postgresql', 'start'])
    if not re.fullmatch('[0-9a-f]{64}', password):
        raise ValueError('Disposable DB password must be a generated 32-byte hex value')
    sql = ("DROP DATABASE IF EXISTS retailops_test;\nDROP ROLE IF EXISTS retailops_test;\n"
           f"CREATE ROLE retailops_test LOGIN PASSWORD '{password}';\n"
           "CREATE DATABASE retailops_test OWNER retailops_test;\n")
    quiet(['sudo', '-u', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1'], input=sql, text=True)
    quiet(['sudo', '-u', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1', '-d', 'retailops_test'],
          input='CREATE EXTENSION IF NOT EXISTS vector;\n', text=True)


def pilot_gate(report, traces):
    rows = [json.loads(line) for path in traces for line in Path(path).read_text(encoding='utf-8').splitlines() if line]
    calls = len(rows)
    valid = report['summary']['valid_tool_call_rate']
    length_rate = sum(r['response']['finish_reason'] == 'length' for r in rows) / calls if calls else 1
    timeout_rate = sum((r['response'].get('error') or {}).get('kind') == 'timeout' for r in rows) / calls if calls else 1
    return {'valid_tool_call_rate': valid, 'length_rate': length_rate, 'timeout_rate': timeout_rate,
            'proceed': valid is not None and valid >= .95 and length_rate <= .02 and timeout_rate <= .02}


# %% [CELL 1] Owner inputs. Run one stage only; stop and let Claude inspect before the next stage.
if __name__ == '__main__':
    REPO_SHA = ''                       # full 40-character SHA on main AFTER W6.4.0 merges
    STAGE = 'examples'                  # examples, pilot, A, B, C, D, regression-w32, regression-w4
    RUN_TAG = 'qwen_rec'                # keep fixed to resume; changing settings requires a new measurement
    P, N_SHARDS, MAX_NUM_SEQS = 4, 12, 6
    MAX_TOKENS = 2048                  # initial probe only; owner fixes this at D4 for ALL A-D configs
    USE_MTP = True
    REPO, VENV = Path('/content/CSKH_ban_le'), Path('/content/w64_rvenv312')
    DRIVE_ROOT = Path('/content/drive/MyDrive/retailops_colab')
    LOCAL_MODEL = Path('/content/models') / MODEL.replace('/', '__')
    DRIVE_MODEL = Path('/content/drive/MyDrive/retailops_models') / MODEL.replace('/', '__')
    VLLM_CACHE = Path.home() / '.cache/vllm'
    clone_commands(REPO, REPO_SHA)      # fail before mounting Drive or consuming setup time
    if STAGE not in ('examples', 'pilot', 'A', 'B', 'C', 'D', 'regression-w32', 'regression-w4'):
        raise ValueError('Unknown stage')
    if not re.fullmatch('[A-Za-z0-9_-]+', RUN_TAG) or not (P > 0 and N_SHARDS > 0 and MAX_TOKENS > 0):
        raise ValueError('Invalid run tag or positive run limits')
    CTX = 8192 if STAGE == 'D' else 16384
    REPEAT = 3 if STAGE in ('A', 'B', 'C', 'D') else 1


# %% [CELL 2] Mount and restore Drive: model (including MTP), compilation cache, Python 3.12 venv
if __name__ == '__main__':
    from google.colab import drive
    drive.mount('/content/drive')
    (DRIVE_ROOT / 'cache').mkdir(parents=True, exist_ok=True)
    for archive, parent in [('vllm_cache.tar', VLLM_CACHE.parent), ('w64_rvenv312.tar', Path('/content'))]:
        cached = DRIVE_ROOT / 'cache' / archive
        if cached.is_file():
            parent.mkdir(parents=True, exist_ok=True)
            quiet(['tar', '-xf', str(cached), '-C', str(parent)])
    LOCAL_MODEL.mkdir(parents=True, exist_ok=True)
    if (DRIVE_MODEL / 'config.json').is_file():
        quiet(['rsync', '-a', str(DRIVE_MODEL) + '/', str(LOCAL_MODEL) + '/'])
    else:
        quiet([sys.executable, '-m', 'pip', 'install', '-q', 'huggingface_hub'])
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL, local_dir=str(LOCAL_MODEL))
    print('Drive and model ready; no credentials are saved')


# %% [CELL 3] GPU and installed vLLM. No reinstall or version override of Colab vLLM.
if __name__ == '__main__':
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                         capture_output=True, text=True, check=True).stdout.strip()
    if len(gpu.splitlines()) != 1:
        raise RuntimeError('W6.4 requires exactly one GPU')
    GPU_GB = float(gpu.split(',')[1].strip().split()[0]) / 1024
    import vllm
    print('GPU:', gpu, '| vLLM:', vllm.__version__)
    API_KEY = secrets.token_urlsafe(32)  # memory only
    SERVER = start_server(build_vllm_command(LOCAL_MODEL, CTX, GPU_GB, mtp=USE_MTP, max_num_seqs=MAX_NUM_SEQS), API_KEY)
    if not wait_server(SERVER, API_KEY):
        stop_process(SERVER)
        if not USE_MTP:
            raise RuntimeError('vLLM failed to start')
        USE_MTP = False
        print('Retrying without MTP')
        SERVER = start_server(build_vllm_command(LOCAL_MODEL, CTX, GPU_GB, mtp=False, max_num_seqs=MAX_NUM_SEQS), API_KEY)
        if not wait_server(SERVER, API_KEY):
            stop_process(SERVER)
            raise RuntimeError('vLLM failed without MTP; stop and disconnect runtime')
    print('vLLM ready; MTP:', USE_MTP)


# %% [CELL 4] Clone pinned system; hash-checked runner venv; disposable local PostgreSQL + pgvector
if __name__ == '__main__':
    for command in clone_commands(REPO, REPO_SHA)[1 if REPO.exists() else 0:]:
        quiet(command)
    actual = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], capture_output=True,
                            text=True, check=True).stdout.strip()
    if actual != REPO_SHA:
        raise RuntimeError('Pinned repository SHA mismatch')
    # requirements-postgres hashes cover Linux CPython 3.11/3.12, not Colab's 3.13.
    # Keep vLLM on the installed 3.13 runtime; use the OS 3.12 only for the runner venv.
    quiet(['apt-get', 'update', '-qq'])
    quiet(['apt-get', 'install', '-y', '-qq', 'python3.12', 'python3.12-venv', 'postgresql',
           'postgresql-server-dev-all', 'build-essential', 'git', 'rsync'])
    if not (VENV / 'bin/python').exists():
        quiet(['python3.12', '-m', 'venv', str(VENV)])
    PYTHON = VENV / 'bin/python'
    quiet(requirements_command(PYTHON, REPO))
    VECTOR = Path('/content/pgvector-w64')
    if not VECTOR.exists():
        quiet(['git', 'clone', '--depth', '1', '--branch', 'v0.8.6', 'https://github.com/pgvector/pgvector.git', str(VECTOR)])
    quiet(['make'], cwd=VECTOR)
    quiet(['make', 'install'], cwd=VECTOR)
    DB_PASSWORD = secrets.token_hex(32)
    ENV = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    ENV.update(RETAILOPS_TEST_DATABASE_URL='postgresql://retailops_test:' + DB_PASSWORD + '@127.0.0.1:5432/retailops_test',
               RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE='1', RETAILOPS_API_KEY=API_KEY,
               RETAILOPS_API_TUNNEL_TOKEN=secrets.token_urlsafe(32), PYTHONUTF8='1')
    provision_database(PYTHON, REPO, ENV, DB_PASSWORD)
    print('Pinned repo, runner venv and disposable pgvector DB ready')


# %% [CELL 5] Deterministic shards, bounded parallel runners, direct Drive reports/traces, merge
if __name__ == '__main__':
    OUT = DRIVE_ROOT / 'runs' / REPO_SHA / RUN_TAG / STAGE
    OUT.mkdir(parents=True, exist_ok=True)
    sources = ([REPO / 'khoa_luan/eval_pack/06_vi_du.jsonl'] if STAGE == 'examples' else
               [REPO / 'evals/agent_scenarios_w3_2.jsonl'] if STAGE == 'regression-w32' else
               [REPO / 'evals/agent_scenarios_w4.jsonl'] if STAGE == 'regression-w4' else
               sorted((REPO / 'evals/suites').glob('S*.jsonl')))
    cases = [json.loads(line) for source in sources for line in source.read_text(encoding='utf-8').splitlines() if line.strip()]
    if STAGE == 'pilot':
        cases = [next(c for c in cases if c['meta']['suite'] == f'S{i:02d}' and c['meta']['split'] == 'dev') for i in range(1, 13)]
    if STAGE in ('B', 'C', 'D'):
        selected = subprocess.run([str(PYTHON), 'scripts/eval_stats.py', 'subset', '--size', '100', '--seed', '20261110',
                                   'evals/suites'], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
        cases = [c for c in cases if c['id'] in set(selected)]
        if len(cases) != 100:
            raise RuntimeError('Subset must contain exactly 100 cases')
    dataset_args = ['--dataset', str(sources[0])] if len(sources) == 1 else ['--dataset-dir', 'evals/suites']
    manifest = dict(git_sha=REPO_SHA, stage=STAGE, context_tokens=CTX, max_tokens=MAX_TOKENS, mtp=USE_MTP,
                    vllm_version=vllm.__version__, gpu=gpu, shards=N_SHARDS, parallel=P, max_num_seqs=MAX_NUM_SEQS,
                    datasets={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                    case_ids=sorted(c['id'] for c in cases),
                    sampling=dict(temperature=1.0, top_p=.95, top_k=20, presence_penalty=1.5))
    manifest_path = OUT / 'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
        raise RuntimeError('Resume settings differ; do not mix measurements. Ask owner before changing the run.')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    jobs, reports, traces = [], [], []
    for index, ids in enumerate(shard_case_ids(manifest['case_ids'], N_SHARDS)):
        case_file, report, trace = [OUT / f'shard-{index:03d}.{ext}' for ext in ('txt', 'json', 'jsonl')]
        case_file.write_text('\n'.join(ids) + '\n', encoding='utf-8')
        command = runner_command(PYTHON, case_file, report, trace, dataset_args,
                                 agent_mode='legacy' if STAGE == 'B' else 'agent', thinking='off' if STAGE == 'C' else 'on',
                                 context_tokens=CTX, repeat=REPEAT, max_tokens=MAX_TOKENS,
                                 vision=STAGE.startswith('regression-'))
        jobs.append((ids, report, trace, command, REPEAT))
        reports.append(report)
        traces.append(trace)
    result = run_shards(jobs, P, repo=REPO, env=ENV)
    quiet([str(PYTHON), 'scripts/eval_stats.py', 'merge', str(OUT / 'merged.json'), *map(str, reports)], cwd=REPO, env=ENV)
    print('Stage complete:', STAGE, '| newly finished:', result.count('done'), '| skipped:', result.count('skipped'))
    if STAGE == 'pilot':
        gate = pilot_gate(json.loads((OUT / 'merged.json').read_text(encoding='utf-8')), traces)
        print('D4 pilot gate:', gate)
        if not gate['proceed']:
            raise RuntimeError('D4 gate failed; stop and ask owner. No next stage runs automatically.')
    print('Reports and traces saved directly to Drive. Stop and inspect before selecting the next stage.')


# %% [CELL 6] Save model, compilation cache and venv only. No environment, logs, SQL or credentials.
if __name__ == '__main__':
    if not (DRIVE_MODEL / 'config.json').is_file():
        DRIVE_MODEL.mkdir(parents=True, exist_ok=True)
        quiet(['rsync', '-aL', str(LOCAL_MODEL) + '/', str(DRIVE_MODEL) + '/'])
    for name, folder, parent in [('vllm_cache.tar', 'vllm', VLLM_CACHE.parent),
                                 ('w64_rvenv312.tar', 'w64_rvenv312', Path('/content'))]:
        if (parent / folder).exists():
            quiet(['tar', '-cf', str(DRIVE_ROOT / 'cache' / name), '-C', str(parent), folder])
    print('Model and runtime caches saved')


# %% [CELL 7] STOP: always run, including after failure or interrupted cells; then disconnect runtime
if __name__ == '__main__':
    for process in CHILDREN:
        stop_process(process)
    quiet(['service', 'postgresql', 'stop'])
    for name in ('API_KEY', 'DB_PASSWORD', 'ENV'):
        globals().pop(name, None)
    print('Processes stopped. Runtime -> Disconnect and delete runtime.')
