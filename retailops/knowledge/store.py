"""Exact pgvector retrieval over a small approved collection in one tenant schema."""
import hashlib
import json
import re
from retailops.core import require
from retailops.knowledge.embedding import DIMENSION, vector

MIN_SCORE = 0.4

DDL = (
    '''CREATE TABLE IF NOT EXISTS knowledge_meta (
        id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
        embedding_fingerprint TEXT NOT NULL, generation TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS knowledge_documents (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, version TEXT NOT NULL,
        content_hash TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS knowledge_chunks (
        document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL, text TEXT NOT NULL, embedding retailops_extensions.vector(384) NOT NULL,
        PRIMARY KEY(document_id,ordinal))''',
)


def documents(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('A collection must contain 1–100 explicitly approved documents.')
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'id','title','version','content','source','approved'}:
            raise ValueError('Invalid knowledge document fields.')
        if item['approved'] is not True:
            raise ValueError('Only explicitly approved documents can be published.')
        if not isinstance(item['id'], str) or not re.fullmatch(r'[A-Z0-9_-]{1,48}', item['id']) or item['id'] in seen:
            raise ValueError('Invalid or duplicate knowledge document ID.')
        for key, limit in [('title',160),('version',48),('source',200),('content',12000)]:
            if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > limit:
                raise ValueError('Invalid knowledge document '+key+'.')
        seen.add(item['id'])
        result.append({**item, 'content_hash': hashlib.sha256(item['content'].encode()).hexdigest()})
    return result


def chunks(text):
    # Small overlapping Unicode chunks for the bounded demo collection.
    # This is character-based splitting, not a semantic boundary detector.
    for start in range(0, len(text), 200):
        part = text[start:start+240].strip()
        if part:
            yield part



class Knowledge:
    def __init__(self, business, embedder):
        if not hasattr(business, 'schema'):
            raise ValueError('RAG requires the PostgreSQL business repository.')
        self.business, self.embedder = business, embedder

    def status(self):
        with self.business.connection() as db:
            exists = db.execute("SELECT to_regclass('knowledge_meta') AS table_name").fetchone()['table_name']
            if not exists:
                return {'ready': False}
            row = db.execute('SELECT * FROM knowledge_meta WHERE id=1').fetchone()
        return {'ready': row is not None and row['version'] == 1
                and row['embedding_fingerprint'] == self.embedder.fingerprint,
                'generation': row['generation'] if row else None}

    def publish(self, items):
        approved = documents(items)
        parts = [(d['id'], i, part) for d in approved for i, part in enumerate(chunks(d['content']))]
        if len(parts) > 500:
            raise ValueError('Collection exceeds 500 chunks.')
        embeddings = self.embedder.encode([part[2] for part in parts])
        if len(embeddings) != len(parts):
            raise ValueError('Embedding batch size mismatch.')
        encoded = [json.dumps(vector(v)) for v in embeddings]
        generation = hashlib.sha256(json.dumps([self.embedder.fingerprint, approved], sort_keys=True).encode()).hexdigest()
        # Whole collection is replaced atomically AFTER all validation and embedding succeed.
        with self.business.connection(write=True) as db:
            for statement in DDL:
                db.execute(statement)
            row = db.execute('SELECT * FROM knowledge_meta WHERE id=1').fetchone()
            if row and row['version'] != 1:
                raise ValueError('Unsupported knowledge schema version.')
            if row and row['generation'] == generation:
                return {'result': 'KNOWLEDGE_UNCHANGED', 'generation': generation}
            db.execute('DELETE FROM knowledge_documents')
            db.executemany('INSERT INTO knowledge_documents VALUES (?,?,?,?,?,?)',
                [(d['id'],d['title'],d['version'],d['content_hash'],d['content'],d['source']) for d in approved])
            db.executemany('INSERT INTO knowledge_chunks VALUES (?,?,?,?::retailops_extensions.vector)',
                          [(*part, emb) for part, emb in zip(parts, encoded)])
            db.execute('''INSERT INTO knowledge_meta VALUES (1,1,?,?) ON CONFLICT(id)
                DO UPDATE SET embedding_fingerprint=excluded.embedding_fingerprint,generation=excluded.generation''',
                (self.embedder.fingerprint, generation))
        return {'result': 'KNOWLEDGE_PUBLISHED', 'documents': len(approved), 'chunks': len(parts), 'generation': generation}

    def search(self, query):
        require(isinstance(query, str) and 0 < len(query.strip()) <= 200, 400, 'invalid_query', 'Câu tra cứu tối đa 200 ký tự.')
        require(self.status()['ready'], 503, 'knowledge_not_ready', 'Kho tài liệu chưa được chuẩn bị cho model embedding hiện tại.')
        encoded = json.dumps(vector(self.embedder.encode([query])[0]))
        with self.business.connection() as db:
            meta = db.execute('SELECT * FROM knowledge_meta WHERE id=1').fetchone()
            require(meta['embedding_fingerprint'] == self.embedder.fingerprint, 409, 'knowledge_changed', 'Kho tài liệu vừa thay đổi. Hãy thử lại.')
            rows = db.execute('''SELECT d.id,d.title,d.version,d.content_hash,d.source,c.ordinal,c.text,
                1-(c.embedding OPERATOR(retailops_extensions.<=>) ?::retailops_extensions.vector) AS score
                FROM knowledge_chunks c JOIN knowledge_documents d ON d.id=c.document_id
                ORDER BY c.embedding OPERATOR(retailops_extensions.<=>) ?::retailops_extensions.vector,d.id,c.ordinal LIMIT 3''',
                (encoded, encoded)).fetchall()
        # Conservative starting threshold, not a calibrated accuracy guarantee.
        return [{**dict(row), 'score': round(row['score'], 5), 'generation': meta['generation']}
                for row in rows if row['score'] >= MIN_SCORE]

    def validate(self, citations):
        if not citations:
            return
        with self.business.connection() as db:
            meta = db.execute('SELECT * FROM knowledge_meta WHERE id=1').fetchone()
            require(meta is not None and all(c['generation'] == meta['generation'] for c in citations),
                    409, 'knowledge_changed', 'Tài liệu đã thay đổi trong lúc trả lời. Hãy gửi yêu cầu mới.')
