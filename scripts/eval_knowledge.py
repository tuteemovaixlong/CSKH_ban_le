"""An evaluation run's isolated, disposable pgvector knowledge schema."""
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RealKnowledge:
    def __enter__(self):
        self.dsn = os.environ.get('RETAILOPS_TEST_DATABASE_URL', '')
        if not self.dsn:
            raise ValueError('--knowledge real requires RETAILOPS_TEST_DATABASE_URL (disposable PostgreSQL)')
        import psycopg
        from scripts.postgres_test_guard import require_disposable_postgres_test_target
        from retailops.storage.pg_repositories import PostgresBusinessStore
        from retailops.knowledge.repository import KnowledgeRepository
        from retailops.knowledge.chunking import read_directory
        require_disposable_postgres_test_target(self.dsn, psycopg.conninfo.conninfo_to_dict)
        self.store = PostgresBusinessStore(self.dsn, uuid.uuid4().hex, create=True)
        try:
            self.repository = KnowledgeRepository(self.store)
            self.ingest_report = self.repository.ingest(read_directory(ROOT / 'data/knowledge'))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        import psycopg
        from psycopg import sql
        with psycopg.connect(self.dsn, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.store.schema)))
