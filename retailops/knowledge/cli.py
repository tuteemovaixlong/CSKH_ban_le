"""Explicit tenant-scoped knowledge ingestion/search commands."""
from pathlib import Path
import os

from retailops.knowledge.chunking import read_directory
from retailops.knowledge.repository import KnowledgeRepository


def add_parser(commands):
    parser = commands.add_parser("knowledge", help="Ingest or inspect tenant knowledge for RAG.")
    actions = parser.add_subparsers(dest="knowledge_action", required=True)
    ingest = actions.add_parser("ingest", help="Replace synthetic knowledge documents from a directory.")
    ingest.add_argument("--tenant", required=True)
    ingest.add_argument("--path", type=Path, default=Path("data/knowledge"))
    search = actions.add_parser("search", help="Run a read-only hybrid pgvector search.")
    search.add_argument("--tenant", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=5)


def _repository(tenant_id):
    from retailops.config import database_settings
    from retailops.storage.pg_repositories import PostgresBusinessStore, PostgresIdentityStore
    backend, dsn = database_settings(os.environ)
    if backend != "postgresql":
        raise ValueError("Knowledge commands require RETAILOPS_STORAGE_BACKEND=postgresql.")
    identity = PostgresIdentityStore(dsn)
    tenant = identity.tenant(tenant_id)
    return KnowledgeRepository(PostgresBusinessStore(dsn, tenant["storage_key"]))


def run(args):
    repository = _repository(args.tenant)
    if args.knowledge_action == "ingest":
        report = repository.ingest(read_directory(args.path))
        return {"result": "KNOWLEDGE_INGESTED", "tenant": args.tenant, **report}
    return {"result": "KNOWLEDGE_SEARCH", "tenant": args.tenant,
            "matches": repository.search(args.query, args.limit)}
