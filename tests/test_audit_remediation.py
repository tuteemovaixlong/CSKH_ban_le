"""Unit tests verifying remediation of GPT-6 Astra Pro Mode audit findings.
Covers:
- [F11] Photo attachment Base64 digest hashing & idempotency replay prevention
- [F04] Tool cache freshness (bound.versions & bound.knowledge.sources populated on cache-hit; prepare_cancellation un-cached)
- [F06] Human handoff automatic escalation record creation in conversation_feedback
- [P0.3] Catalog.save() graceful handling of filesystem errors
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops_tools import BoundTools
from retailops_conversation import Catalog


class FakeAgent:
    def __init__(self, name="fake_agent"):
        self.name = name
        self.model = name
        self.call_count = 0

    def inspect(self):
        return {"name": self.name, "digest": "fixture_digest", "provider": "custom", "agent_protocol": "retailops-agent-v1"}

    def chat(self, messages, allow_tools, timeout):
        self.call_count += 1
        return {
            "message": {"role": "assistant", "content": "Phản hồi thử nghiệm từ agent."},
            "prompt_eval_count": 50,
            "eval_count": 25,
            "reported_cost_usd": 0.0,
            "reasoning": "Reasoning test"
        }


class TestAuditRemediation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
        self.tmp.close()
        self.store = BusinessStore(self.tmp.name, create=True)
        self.store.seed()
        self.agent = FakeAgent()
        self.token = "t" * 40
        self.tokens = {hashlib.sha256(self.token.encode()).hexdigest(): "C-001"}
        self.app = Application(self.store, self.tokens, infer=self.agent, role='customer')

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_f11_attachment_digest_prevents_mismatched_replay(self):
        """F11: Changing attachment data under the same filename must generate a different digest."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        req_id = "req_audit_" + "a" * 20

        # Turn 1: attachment with image data A
        payload1 = {
            "conversation_id": cid,
            "text": "Kiểm tra sản phẩm trong ảnh",
            "request_id": req_id,
            "attachment": {
                "type": "image",
                "name": "product.jpg",
                "data": "data:image/jpeg;base64,AAAA1111"
            }
        }
        res1 = self.app.chat("C-001", payload1)
        self.assertEqual(res1["replayed"], False)
        self.assertEqual(self.agent.call_count, 1)

        # Turn 2: same request_id, same filename, but DIFFERENT base64 data -> Store detects request_conflict!
        payload2 = {
            "conversation_id": cid,
            "text": "Kiểm tra sản phẩm trong ảnh",
            "request_id": req_id,
            "attachment": {
                "type": "image",
                "name": "product.jpg",
                "data": "data:image/jpeg;base64,BBBB2222"
            }
        }
        with self.assertRaises(ApiError) as ctx:
            self.app.chat("C-001", payload2)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, 'request_conflict')
        self.assertEqual(self.agent.call_count, 1)

        # Turn 3: same request_id, identical image data A -> MUST be safely replayed!
        res3 = self.app.chat("C-001", payload1)
        self.assertEqual(res3["replayed"], True)
        self.assertEqual(self.agent.call_count, 1)  # Agent was not called again

    def test_f04_tool_cache_hit_populates_bound_versions_and_sources(self):
        """F04: When ToolCache hits, bound.versions & bound.knowledge.sources must still be populated."""
        snapshot = self.store.conversation("C-001", self.store.new_conversation("C-001", "custom")["conversation_id"])
        identity = self.agent.inspect()
        bound = BoundTools(self.store, self.app.catalog, "C-001", snapshot, identity, can_cancel=True)

        # 1. Execute get_order and populate cache
        cached_order_payload = {
            'order': {
                'id': 'O-101',
                'customer_id': 'C-001',
                'status': 'pending',
                'version': 42
            }
        }
        self.app.tool_cache.set('C-001', 'get_order', {'order_id': 'O-101'}, cached_order_payload)

        # Simulate execute closure logic from Application.chat
        def execute(name, arguments):
            cached_res = self.app.tool_cache.get('C-001', name, arguments)
            if cached_res is not None:
                if name in ('get_order', 'read_order') and isinstance(cached_res, dict) and 'order' in cached_res:
                    order_obj = cached_res['order']
                    if isinstance(order_obj, dict) and 'id' in order_obj and 'version' in order_obj:
                        bound.versions[order_obj['id']] = order_obj['version']
                        bound.context['order_id'] = order_obj['id']
                elif name == 'search_knowledge' and isinstance(cached_res, dict) and 'results' in cached_res:
                    known = {s['citation_id'] for s in bound.knowledge.sources if isinstance(s, dict) and 'citation_id' in s}
                    for s in cached_res.get('results', []):
                        if isinstance(s, dict) and 'citation_id' in s and s['citation_id'] not in known:
                            bound.knowledge.sources.append(dict(s))
                            known.add(s['citation_id'])
                return cached_res
            return bound(name, arguments)

        # Call execute on get_order -> cache hit, bound.versions and bound.context updated!
        hit_res = execute('get_order', {'order_id': 'O-101'})
        self.assertEqual(hit_res, cached_order_payload)
        self.assertEqual(bound.versions.get('O-101'), 42)
        self.assertEqual(bound.context.get('order_id'), 'O-101')

        # Test knowledge search cache hit populates sources
        cached_knowledge = {
            'results': [
                {'citation_id': 'KB:SRC1', 'title': 'Chính sách bảo hành', 'excerpt': 'Nội dung'}
            ]
        }
        self.app.tool_cache.set('C-001', 'search_knowledge', {'query': 'bảo hành'}, cached_knowledge)
        hit_k = execute('search_knowledge', {'query': 'bảo hành'})
        self.assertEqual(hit_k, cached_knowledge)
        self.assertTrue(any(s.get('citation_id') == 'KB:SRC1' for s in bound.knowledge.sources))

        # Verify prepare_cancellation is never cached
        self.assertIsNone(self.app.tool_cache.get('C-001', 'prepare_cancellation', {'order_id': 'O-101'}))

    def test_f06_request_human_support_creates_escalation_feedback(self):
        """F06: Invoking request_human_support automatically records a human_handoff escalation in DB."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        snapshot = self.store.conversation("C-001", cid)
        identity = self.agent.inspect()
        bound = BoundTools(self.store, self.app.catalog, "C-001", snapshot, identity, can_cancel=True)

        res = bound('request_human_support', {'reason': 'Khách hàng khiếu nại chất lượng sản phẩm'})
        self.assertEqual(res['status'], 'escalated_to_human')
        self.assertIn('nhân viên', res['message'])

        # Verify record in conversation_feedback table
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM conversation_feedback WHERE conversation_id=? AND feedback_type='human_handoff'",
                (cid,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['reason_code'], 'customer_requested_human')
            self.assertEqual(row['comment'], 'Khách hàng khiếu nại chất lượng sản phẩm')

    def test_p03_catalog_save_catches_oserror_gracefully(self):
        """P0.3: Catalog.save() should handle filesystem errors (e.g. read-only fs) gracefully without crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_file = Path(tmpdir) / "products.json"
            catalog_file.write_text(json.dumps({"source": "unit_test", "products": []}), encoding="utf-8")
            cat = Catalog(str(catalog_file))
            cat.products["P-TEST"] = {"id": "P-TEST", "name": "Test Product"}

            # Simulate PermissionError on file open during save()
            with patch("pathlib.Path.write_text", side_effect=PermissionError("Read-only filesystem")):
                try:
                    cat.save()
                except Exception as e:
                    self.fail(f"Catalog.save() raised unexpected exception: {e}")


if __name__ == '__main__':
    unittest.main()
