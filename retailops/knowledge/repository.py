"""Tenant-local pgvector repository. Model-facing access remains read-only."""
import hashlib
import json
import time

from retailops.knowledge.chunking import chunks, checksum
from retailops.knowledge.embedding import MODEL_ID, embedding, vector_literal

SCHEMA_VERSION = 3


class KnowledgeRepository:
    def __init__(self, business_store):
        if not hasattr(business_store, "schema"):
            raise ValueError("Knowledge retrieval requires the PostgreSQL backend.")
        self.store = business_store

    def _require_schema(self, db):
        row = db.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()
        if not row or row["version"] < SCHEMA_VERSION:
            raise ValueError("Knowledge schema is not ready. Run the attended pgvector migration first.")

    @staticmethod
    def _document_id(source_key):
        return hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:32]

    def replace_document(self, source_key, title, source_uri, content, metadata=None):
        if not isinstance(source_key, str) or not 1 <= len(source_key) <= 240:
            raise ValueError("Invalid knowledge source key.")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            raise ValueError("Invalid knowledge title.")
        if not isinstance(source_uri, str) or not 1 <= len(source_uri) <= 500:
            raise ValueError("Invalid knowledge source URI.")
        parts = chunks(content)
        document_id = self._document_id(source_key)
        digest = checksum(content)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(metadata_json) > 4000:
            raise ValueError("Knowledge metadata is too large.")
        rows = []
        for ordinal, part in enumerate(parts):
            chunk_id = hashlib.sha256(f"{document_id}\0{ordinal}\0{part}".encode("utf-8")).hexdigest()[:40]
            rows.append((chunk_id, document_id, ordinal, part, MODEL_ID, vector_literal(embedding(part))))
        with self.store.connection(write=True) as db:
            self._require_schema(db)
            previous = db.execute("SELECT checksum FROM knowledge_documents WHERE source_key=?", (source_key,)).fetchone()
            db.execute("""INSERT INTO knowledge_documents(id,source_key,title,source_uri,checksum,metadata,active,updated_at)
                VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(source_key) DO UPDATE SET
                title=excluded.title,source_uri=excluded.source_uri,checksum=excluded.checksum,
                metadata=excluded.metadata,active=1,updated_at=excluded.updated_at""",
                (document_id, source_key, title.strip(), source_uri, digest, metadata_json, time.time()))
            db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,))
            db.executemany("""INSERT INTO knowledge_chunks(id,document_id,ordinal,content,embedding_model,embedding)
                VALUES (?,?,?,?,?,?::retailops_extensions.vector)""", rows)
        return {"source_key": source_key, "document_id": document_id, "chunks": len(rows),
                "checksum": digest, "changed": previous is None or previous["checksum"] != digest,
                "embedding_model": MODEL_ID}

    def ingest(self, documents):
        reports = [self.replace_document(doc.source_key, doc.title, doc.source_uri, doc.content,
                                         {"format": doc.source_key.rsplit(".", 1)[-1].lower()})
                   for doc in documents]
        return {"documents": len(reports), "chunks": sum(item["chunks"] for item in reports),
                "changed": sum(bool(item["changed"]) for item in reports), "embedding_model": MODEL_ID,
                "sources": [item["source_key"] for item in reports]}

    def search(self, query, limit=5):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError("Knowledge query must contain 1-500 characters.")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("Knowledge search limit must be 1-10.")
        vector = vector_literal(embedding(query))
        sql = """WITH q AS (
              SELECT ?::retailops_extensions.vector AS embedding, plainto_tsquery('simple', ?) AS tsq
            ), ranked AS (
              SELECT c.id,c.ordinal,c.content,d.source_key,d.title,d.source_uri,
                (1 - (c.embedding OPERATOR(retailops_extensions.<=>) q.embedding))::double precision AS vector_score,
                ts_rank_cd(c.search_tsv,q.tsq)::double precision AS lexical_score
              FROM knowledge_chunks c JOIN knowledge_documents d ON d.id=c.document_id CROSS JOIN q
              WHERE d.active=1 AND c.embedding_model=?
            )
            SELECT id,ordinal,content,source_key,title,source_uri,vector_score,lexical_score,
              (0.75*COALESCE(vector_score,0)+0.25*LEAST(COALESCE(lexical_score,0),1.0))::double precision AS score
            FROM ranked ORDER BY score DESC,id ASC LIMIT ?"""
        with self.store.connection() as db:
            self._require_schema(db)
            rows = db.execute(sql, (vector, query.strip(), MODEL_ID, limit)).fetchall()
        results = []
        for row in rows:
            score = max(0.0, min(1.0, float(row["score"] or 0.0)))
            results.append({"citation": f"KB:{row['source_key']}#chunk-{row['ordinal']+1}",
                            "source_key": row["source_key"], "title": row["title"],
                            "source_uri": row["source_uri"], "chunk": row["content"],
                            "score": round(score, 6),
                            "vector_score": round(float(row["vector_score"] or 0.0), 6),
                            "lexical_score": round(float(row["lexical_score"] or 0.0), 6)})
        return results
