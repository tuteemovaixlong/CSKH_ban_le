"""Rows 2/4 must run against disposable PostgreSQL with pgvector on PR CI."""
import os
import unittest
from unittest.mock import patch
from scripts import run_agent_scenarios as runner
from scripts.eval_knowledge import RealKnowledge
from scripts.eval_retrieval import evaluate


@unittest.skipUnless(os.environ.get('RETAILOPS_TEST_DATABASE_URL'), 'PostgreSQL integration runs on PR CI')
class EvaluationPostgresTests(unittest.TestCase):
    def test_real_knowledge_ignores_scripted_documents_and_cleans_schema(self):
        from retailops.knowledge.tool import KnowledgeTool
        from retailops.knowledge.repository import KnowledgeRepository
        with RealKnowledge() as real:
            schema = real.store.schema
            self.assertEqual(real.ingest_report['documents'], len(list((runner.ROOT / 'data/knowledge').glob('*.md'))))
            case = runner.load_dataset()[0]
            case['knowledge'] = [{'source_key': 'injected.md', 'title': 'Fake', 'chunk': 'untrusted'}]
            world = runner.World(case, runner.ScriptedGateway())
            try:
                with patch.object(runner, '_REAL_KNOWLEDGE', real), world.knowledge_base():
                    results = KnowledgeTool(world.store).search('đổi trả hàng 7 ngày')['results']
                    self.assertIn('returns.md', {r['source_key'] for r in results})
                    self.assertNotIn('injected.md', {r['source_key'] for r in results})
                case['meta'] = {'knowledge_mode': 'scripted'}
                world.knowledge_mode = 'scripted'
                with patch.object(runner, '_REAL_KNOWLEDGE', real), world.knowledge_base():
                    self.assertEqual(KnowledgeRepository(world.store).search('query')[0]['source_key'], 'injected.md')
            finally:
                world.close()
            case['meta'] = {}
            case['turns'] = [dict(user='Chính sách đổi trả hàng trong 7 ngày thế nào?',
                fake_model=[{'call': [{'name': 'search_knowledge', 'arguments': {'query': 'đổi trả hàng trong 7 ngày'}}]},
                            {'say': 'Chính sách trả hàng của shop [{{last_tool.results.0.citation_id}}].'}],
                expect={'tools_called': ['search_knowledge'], 'sources': ['returns.md']})]
            with patch.object(runner, '_REAL_KNOWLEDGE', real):
                report = runner.run_suite([case], runner.ScriptedGateway, 'fake', knowledge='real')
            self.assertEqual(report['summary']['pass_at_1'], 1., report['scenarios'])
        import psycopg
        with psycopg.connect(os.environ['RETAILOPS_TEST_DATABASE_URL']) as db:
            self.assertIsNone(db.execute('SELECT schema_name FROM information_schema.schemata WHERE schema_name=%s', (schema,)).fetchone())

    def test_real_retrieval_two_known_cases(self):
        with RealKnowledge() as real:
            cases = [dict(id='retrieval_1', turns=[dict(user='đổi trả hàng trong 7 ngày', expect={'sources': ['returns.md']})]),
                     dict(id='retrieval_2', turns=[dict(user='giờ làm việc nhân viên chăm sóc khách hàng trực 8:00 21:00', expect={'sources': ['store_hours_contact.md']})])]
            report = evaluate(cases, real.store)
            self.assertEqual(report['cases'], 2)
            self.assertEqual(report['recall_at_3'], 1.)
            self.assertEqual(report['mrr'], 1.)
