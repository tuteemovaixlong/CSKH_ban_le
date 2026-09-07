"""Quantized multilingual CPU embeddings. Downloads only in the explicit prepare command."""
import hashlib
import json
import math
from pathlib import Path
import threading

MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
REPOSITORY = 'qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q'
REVISION = 'faf4aa4225822f3bc6376869cb1164e8e3feedd0'
DIMENSION = 384
FILES = ('model_optimized.onnx', 'tokenizer.json', 'tokenizer_config.json',
         'special_tokens_map.json', 'config.json')


def vector(value):
    values = [float(v) for v in value]
    if len(values) != DIMENSION or not all(math.isfinite(v) for v in values):
        raise ValueError('Invalid embedding dimension or nonfinite vector.')
    norm = math.sqrt(sum(v*v for v in values))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError('Embedding must not be a zero vector.')
    return [v/norm for v in values]


def hashes(path):
    return {name: hashlib.sha256((path/name).read_bytes()).hexdigest() for name in FILES}


def prepare(directory):
    from huggingface_hub import snapshot_download
    directory = Path(directory)
    if directory.exists():
        raise ValueError('Use a new model directory; never overwrite weights used by an index.')
    revision = REVISION
    directory.mkdir(parents=True)
    snapshot_download(REPOSITORY, revision=revision, token=False, local_dir=directory, allow_patterns=list(FILES))
    manifest = {'model': MODEL, 'repository': REPOSITORY, 'revision': revision,
                'dimension': DIMENSION, 'pooling': 'mean', 'files': hashes(directory)}
    (directory/'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2))
    return {'result': 'EMBEDDING_PREPARED', 'revision': revision, 'directory': str(directory)}


class CpuEmbedding:
    def __init__(self, directory):
        directory = Path(directory)
        manifest = json.loads((directory/'manifest.json').read_text())
        if (manifest.get('model') != MODEL or manifest.get('repository') != REPOSITORY
                or manifest.get('pooling') != 'mean' or manifest.get('revision') != REVISION
                or manifest.get('dimension') != DIMENSION
                or manifest.get('files') != hashes(directory)):
            raise ValueError('Embedding files do not match the prepared manifest.')
        self.fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        from fastembed import TextEmbedding
        self.model = TextEmbedding(MODEL, specific_model_path=str(directory), local_files_only=True,
                                   threads=1, providers=['CPUExecutionProvider'])
        self.lock = threading.Lock()

    def encode(self, texts):
        # Bound batch size at callers; no process pool, GPU, provider API or network fallback.
        with self.lock:
            return [vector(v.tolist()) for v in self.model.embed(texts, batch_size=8)]
