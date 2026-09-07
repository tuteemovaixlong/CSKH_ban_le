"""Small deterministic Markdown/text reader and chunker for synthetic knowledge."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import re

ALLOWED_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True)
class SourceDocument:
    source_key: str
    title: str
    source_uri: str
    content: str


def _clean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _title(path, content):
    for line in content.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)[:160]
    return path.stem.replace("-", " ").replace("_", " ").strip().title()[:160]


def read_directory(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Knowledge path must be an existing directory.")
    documents = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES):
        content = _clean(path.read_text(encoding="utf-8"))
        if not content:
            continue
        relative = path.relative_to(root).as_posix()
        documents.append(SourceDocument(relative, _title(path, content), "repo://data/knowledge/" + relative, content))
    if not documents:
        raise ValueError("Knowledge directory contains no .md or .txt documents.")
    return documents


def _split_long(block, max_chars):
    words = block.split()
    chunks, current = [], []
    for word in words:
        candidate = " ".join(current + [word])
        if current and len(candidate) > max_chars:
            chunks.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunks(content, target_chars=900, overlap_chars=140):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Knowledge document is empty.")
    if not 300 <= target_chars <= 2000 or not 0 <= overlap_chars <= 300:
        raise ValueError("Invalid chunking budget.")
    blocks = [part.strip() for part in re.split(r"\n\s*\n", _clean(content)) if part.strip()]
    expanded = []
    for block in blocks:
        expanded.extend(_split_long(block, target_chars) if len(block) > target_chars else [block])
    result, current = [], ""
    for block in expanded:
        candidate = block if not current else current + "\n\n" + block
        if current and len(candidate) > target_chars:
            result.append(current)
            overlap = current[-overlap_chars:].lstrip() if overlap_chars else ""
            current = (overlap + "\n\n" + block).strip() if overlap else block
        else:
            current = candidate
    if current:
        result.append(current)
    return [part[:4000] for part in result if part.strip()]


def checksum(content):
    return hashlib.sha256(_clean(content).encode("utf-8")).hexdigest()
