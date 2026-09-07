"""RAG foundation: deterministic chunks/embeddings and real pgvector isolation."""
import hashlib
import math
import os
import unittest

from retailops.knowledge.chunking import SourceDocument, chunks
from retailops.knowledge.embedding import DIMENSION, embedding, vector_literal

DSN = os.environ.get("RETAILOPS_TEST_DATABASE_URL", "")


def cosine(left, right):
    return sum(a*b for a,b in zip(left,right))


class EmbeddingTests(unittest.TestCase):
    def test_embedding_is_deterministic_normalized_and_fixed_dimension(self):
        first = embedding("Chính sách hủy đơn chờ xử lý")
        second = embedding("Chính sách hủy đơn chờ xử lý")
        self.assertEqual(first, second)
        self.assertEqual(len(first), DIMENSION)
        self.assertAlmostEqual(math.sqrt(sum(x*x for x in first)), 1.0, places=7)
        self.assertTrue(vector_literal(first).startswith("["))

    def test_feature_hash_prefers_related_lexical_context(self):
        query = embedding("hủy đơn pending")
        related = embedding("chính sách hủy đơn ở trạng thái pending")
        unrelated = embedding("hướng dẫn kích thước áo và chất liệu")
        self.assertGreater(cosine(query, related), cosine(query, unrelated))

    def test_chunker_is_bounded_and_deterministic(self):
        text = "# Tài liệu\n\n" + "đổi trả sản phẩm " * 180
        first = chunks(text, target_chars=500, overlap_chars=80)
        self.assertEqual(first, chunks(text, target_chars=500, overlap_chars=80))
        self.assertGreater(len(first), 1)
        self.assertTrue(all(0 < len(part) <= 4000 for part in first))


@unittest.skipUnless(DSN, "PostgreSQL pgvector integration runs in CI.")
class KnowledgePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        if not psycopg.conninfo.conninfo_to_dict(DSN).get("dbname", "").startswith("retailops_test"):
            raise ValueError("Refusing to modify a database not named retailops_test*.")

    def setUp(self):
        from retailops.storage.pg_repositories import PostgresBusinessStore
        self.keys = [hashlib.md5((self.id()+str(i)).encode()).hexdigest() for i in range(2)]
        self.stores = [PostgresBusinessStore(DSN, key, create=True) for key in self.keys]
        self.addCleanup(self.cleanup_schemas)

    def cleanup_schemas(self):
        import psycopg
        from psycopg import sql
        from retailops.storage.postgres import tenant_schema
        with psycopg.connect(DSN, autocommit=True) as connection:
            for key in self.keys:
                connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(tenant_schema(key))))

    def test_ingest_search_and_tenant_isolation(self):
        from retailops.knowledge.repository import KnowledgeRepository
        left = KnowledgeRepository(self.stores[0])
        right = KnowledgeRepository(self.stores[1])
        left.ingest([SourceDocument("cancel.md", "Hủy đơn", "repo://cancel.md",
                    "Đơn pending có thể yêu cầu hủy. Người dùng phải bấm nút xác nhận riêng."),
                     SourceDocument("ship.md", "Vận chuyển", "repo://ship.md",
                    "Chính sách vận chuyển mẫu từ hai đến năm ngày làm việc.")])
        right.ingest([SourceDocument("secret.md", "Tenant khác", "repo://secret.md",
                     "Tài liệu riêng của tenant khác về hủy đơn VIP.")])
        matches = left.search("hủy đơn pending xác nhận", 3)
        self.assertEqual(matches[0]["source_key"], "cancel.md")
        self.assertTrue(all(item["source_key"] != "secret.md" for item in matches))
        self.assertTrue(matches[0]["citation"].startswith("KB:cancel.md#chunk-"))
        self.assertNotIn("secret.md", {m["source_key"] for m in left.search("VIP hủy đơn", 3)})

    def test_v2_store_stays_readable_until_explicit_v3_migration(self):
        from retailops.knowledge.repository import KnowledgeRepository
        from retailops.storage.pg_schema import initialize
        store = self.stores[0]
        with store.connection(write=True) as db:
            db.execute("DROP TABLE knowledge_chunks")
            db.execute("DROP TABLE knowledge_documents")
            db.execute("UPDATE retailops_schema SET version=2 WHERE component='business'")
        from retailops.storage.pg_repositories import PostgresBusinessStore
        compatible = PostgresBusinessStore(DSN, self.keys[0])
        with self.assertRaises(ValueError):
            KnowledgeRepository(compatible).search("hủy đơn")
        with compatible.connection(write=True) as db:
            initialize(db, compatible.schema, "business")
        with compatible.connection() as db:
            self.assertEqual(db.execute("SELECT version FROM retailops_schema").fetchone()["version"], 3)
        self.assertEqual(KnowledgeRepository(compatible).search("hủy đơn"), [])
