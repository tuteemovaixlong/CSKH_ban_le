"""Dependency-free deterministic baseline embeddings.

This is intentionally a feature-hashing baseline, not a claim of neural semantic
quality. It keeps ingestion/retrieval deterministic and offline while the storage
contract is established. A neural embedder can replace it later without changing
the pgvector schema or repository API.
"""
import hashlib
import math
import re
import unicodedata

DIMENSION = 384
MODEL_ID = "feature-hash-v1"
_TOKEN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)


def tokens(text):
    if not isinstance(text, str):
        raise ValueError("Embedding input must be text.")
    normalized = unicodedata.normalize("NFKC", text).lower()
    return _TOKEN.findall(normalized)


def embedding(text):
    words = tokens(text)
    if not words:
        raise ValueError("Embedding input has no searchable text.")
    values = [0.0] * DIMENSION
    features = [("u:" + word, 1.0) for word in words]
    features += [("b:" + left + "\x1f" + right, 1.35) for left, right in zip(words, words[1:])]
    for word in words:
        if len(word) >= 5:
            features.extend(("c:" + word[i:i+3], 0.30) for i in range(len(word)-2))
    for feature, weight in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSION
        sign = 1.0 if digest[4] & 1 else -1.0
        values[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ValueError("Embedding input produced an empty vector.")
    return [value / norm for value in values]


def vector_literal(values):
    if not isinstance(values, (list, tuple)) or len(values) != DIMENSION:
        raise ValueError("Embedding dimension mismatch.")
    cleaned = []
    for value in values:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Embedding contains a non-finite value.")
        cleaned.append(f"{value:.8f}")
    return "[" + ",".join(cleaned) + "]"
