"""Operator-only publication; no public upload, crawler or embedding endpoint."""
import json
import os
from pathlib import Path


def add_parser(commands):
    parser = commands.add_parser('knowledge', help='Prepare CPU embeddings and publish an approved tenant collection.')
    actions = parser.add_subparsers(dest='knowledge_action', required=True)
    prepare = actions.add_parser('prepare-model')
    prepare.add_argument('--directory', type=Path, required=True)
    for name in ('publish', 'search', 'check'):
        action = actions.add_parser(name)
        action.add_argument('--tenant', required=True)
        if name == 'publish':
            action.add_argument('--file', type=Path, required=True)
        if name == 'search':
            action.add_argument('--query', required=True)


def run(args):
    from retailops.knowledge.embedding import CpuEmbedding, prepare
    if args.knowledge_action == 'prepare-model':
        return prepare(args.directory)
    from retailops.config import database_settings
    from retailops.identity.postgres import PostgresSessions
    from retailops.knowledge.store import Knowledge
    backend, dsn = database_settings(os.environ)
    if backend != 'postgresql':
        raise ValueError('Knowledge publication requires PostgreSQL.')
    store = PostgresSessions(dsn).business_store(args.tenant)
    knowledge = Knowledge(store, CpuEmbedding(os.environ.get('RETAILOPS_EMBEDDING_DIR','/data/embedding-model')))
    if args.knowledge_action == 'publish':
        if args.file.stat().st_size > 1_500_000:
            raise ValueError('Collection file is too large.')
        return knowledge.publish(json.loads(args.file.read_text()))
    if args.knowledge_action == 'search':
        return {'results': knowledge.search(args.query)}
    return knowledge.status()
