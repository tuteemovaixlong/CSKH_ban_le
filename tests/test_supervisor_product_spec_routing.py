"""Acceptance tests F01-F15 for product spec routing, warranty precedence, and InferenceGate race hardening."""
import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from agent_protocol import SYSTEM
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.business.warranty import (
    check_warranty_eligibility,
    resolve_warranty_period,
)
from retailops.core import ApiError
from retailops.inference_gate import GatedGateway, InferenceGate
from retailops.workflow.subagents.order_agent import _synthesize_order_response
from retailops.workflow.subagents.policy_agent import _synthesize_policy_response
from retailops.workflow.subagents.read_worker import run_read_worker
from retailops.workflow.supervisor import run_supervisor
from retailops_providers import filter_system_prompt_for_tools


class SupervisorProductSpecRoutingTests(unittest.TestCase):
    def test_f01_focus_o819125_routes_to_order_agent_product_spec(self):
        """F01: Selected order O-819125 + 'Món này chất liệu gì và bảo hành bao lâu?' routes to order_agent."""
        state = {
            "messages": [{"role": "user", "content": "Món này chất liệu gì và bảo hành bao lâu?"}],
            "bound": {"context": {"order_id": "O-819125"}},
            "subagent_history": [],
            "trace": {},
        }
        res = run_supervisor(state)
        self.assertEqual(res.get("next_worker"), "order_agent")
        self.assertEqual(res.get("intent"), "order_inquiry")
        self.assertEqual(res.get("trace", {}).get("routing_reason"), "product_spec_inquiry")

    def test_f02_no_focus_asks_to_identify_item_no_crash(self):
        """F02: No focus + same query routes to order_agent with product_spec_no_context and asks to identify."""
        state = {
            "messages": [{"role": "user", "content": "Món này chất liệu gì và bảo hành bao lâu?"}],
            "bound": {"context": {}},
            "subagent_history": [],
            "trace": {},
        }
        res = run_supervisor(state)
        self.assertEqual(res.get("next_worker"), "order_agent")
        self.assertEqual(res.get("trace", {}).get("routing_reason"), "product_spec_no_context")

        # When get_context returns empty records, synthesizer asks customer to select item
        synth = _synthesize_order_response([{"name": "get_context", "args": {}, "result": {"order": None, "product": None}}])
        self.assertIsNotNone(synth)
        self.assertIn("Chưa có đơn hoặc sản phẩm được chọn", synth)

    def test_f03_product_id_focus_and_explicit_id_override(self):
        """F03: product_id-only focus and explicit product ID in query route correctly to order_agent."""
        state_pid = {
            "messages": [{"role": "user", "content": "Chất liệu và bảo hành thế nào?"}],
            "bound": {"context": {"product_id": "P-601"}},
            "subagent_history": [],
            "trace": {},
        }
        res_pid = run_supervisor(state_pid)
        self.assertEqual(res_pid.get("next_worker"), "order_agent")
        self.assertEqual(res_pid.get("trace", {}).get("routing_reason"), "product_spec_inquiry")

        state_override = {
            "messages": [{"role": "user", "content": "P-603 chất liệu và bảo hành ra sao?"}],
            "bound": {"context": {"order_id": "O-819125"}},
            "subagent_history": [],
            "trace": {},
        }
        res_override = run_supervisor(state_override)
        self.assertEqual(res_override.get("next_worker"), "order_agent")

    def test_f04_query_variations_route_reliably(self):
        """F04: Variations including unaccented text route stably to order_agent."""
        variations = [
            "Món này bảo hành bao lâu?",
            "Chất liệu gì?",
            "Còn bảo hành thì sao?",
            "mon nay chat lieu gi va bao hanh bao lau?",
            "mon nay bao hanh bao lau",
            "chat lieu vai gi",
        ]
        for query in variations:
            state = {
                "messages": [{"role": "user", "content": query}],
                "bound": {"context": {"order_id": "O-819125"}},
                "subagent_history": [],
                "trace": {},
            }
            res = run_supervisor(state)
            self.assertEqual(
                res.get("next_worker"),
                "order_agent",
                f"Failed for query '{query}': routed to {res.get('next_worker')}",
            )

    def test_f05_store_policy_faq_routes_to_policy_agent_even_when_focused(self):
        """F05: General FAQ about shop warranty policy routes to policy_agent even when order is focused."""
        policy_faqs = [
            "Chính sách bảo hành của shop là gì?",
            "Quy trình bảo hành của shop như thế nào?",
            "Bảo hành có mất phí không?",
            "Điều kiện bảo hành của shop",
        ]
        for faq in policy_faqs:
            state = {
                "messages": [{"role": "user", "content": faq}],
                "bound": {"context": {"order_id": "O-819125"}},
                "subagent_history": [],
                "trace": {},
            }
            res = run_supervisor(state)
            self.assertEqual(
                res.get("next_worker"),
                "policy_agent",
                f"Failed for FAQ '{faq}': routed to {res.get('next_worker')}",
            )
            self.assertEqual(res.get("trace", {}).get("routing_reason"), "policy_conditions_faq")

    def test_f06_missing_delivered_at_distinguishes_catalog_vs_eligibility(self):
        """F06: Pending order without delivered_at cannot determine eligibility."""
        order = {"id": "O-819125", "status": "pending", "delivered_at": None}
        product = {"id": "P-601", "warranty_days": 90}
        check = check_warranty_eligibility(order, product, current_time=1700000000.0)
        self.assertEqual(check["status"], "cannot_determine")
        self.assertEqual(check["warranty_days"], 90)
        self.assertEqual(check["reason"], "missing_delivered_at")

    def test_f07_catalog_override_precedence(self):
        """F07: P-603 with 180 days overrides general policy 90 days."""
        product_shoes = {"id": "P-603", "warranty_days": 180}
        resolved = resolve_warranty_period(product_shoes, general_policy_days=90)
        self.assertEqual(resolved["warranty_days"], 180)
        self.assertEqual(resolved["source"], "product_override")

        product_default = {"id": "P-101", "warranty_days": None}
        resolved_default = resolve_warranty_period(product_default, general_policy_days=90)
        self.assertEqual(resolved_default["warranty_days"], 90)
        self.assertEqual(resolved_default["source"], "general_policy")

    def test_f08_model_attempting_get_context_in_policy_agent_safe_boundary(self):
        """F08: Disallowed tool call in policy_agent does not crash with 503 and states boundary."""
        tool_results = [{"name": "get_context", "status": "error", "result": {"error": "tool_not_allowed"}}]
        synth = _synthesize_policy_response(tool_results)
        self.assertIsNotNone(synth)
        self.assertIn("ngoài phạm vi của chuyên viên chính sách", synth)

    def test_f09_prompt_filtering_prevents_unallowed_tool_directives(self):
        """F09: Scoped prompt filtering removes conflicting directives for policy_agent."""
        policy_allowed = frozenset(("search_knowledge",))
        filtered = filter_system_prompt_for_tools(SYSTEM, policy_allowed)
        self.assertNotIn("Call get_order or get_context again", filtered)
        self.assertNotIn("Call get_product/search_products/get_context", filtered)
        self.assertNotIn("The only cancellation-related tool is prepare_cancellation", filtered)
        self.assertIn("search_knowledge", filtered)

    def test_f13_inference_gate_timeout_handoff_race_no_permit_leak(self):
        """F13: Deterministic simulation of waiter timeout coinciding with exit hand-off."""
        gate = InferenceGate(concurrency=1, max_queue=2, queue_timeout=0.05)
        # Caller A enters
        gate.enter()
        self.assertEqual(gate.in_flight, 1)

        # Waiter B waits and times out
        event_b = threading.Event()
        with gate._lock:
            gate._queue.append(event_b)
        acquired = event_b.wait(timeout=0.01)
        self.assertFalse(acquired)

        # Caller A exits right as B times out -> pops event_b and sets it
        gate.exit()

        # B executes timeout resolution
        with gate._lock:
            if event_b in gate._queue:
                gate._queue.remove(event_b)
            else:
                if gate._queue:
                    next_event = gate._queue.popleft()
                    next_event.set()
                else:
                    gate._active_count = max(0, gate._active_count - 1)
            gate.total_timeout_requests += 1

        # Assert no permit leak
        self.assertEqual(gate.in_flight, 0)
        self.assertEqual(gate.queue_size, 0)

        # Next caller C must be able to acquire immediately
        wait_ms = gate.enter()
        self.assertEqual(wait_ms, 0.0)
        self.assertEqual(gate.in_flight, 1)
        gate.exit()
        self.assertEqual(gate.in_flight, 0)

    def test_f14_gated_gateway_deadline_deduction(self):
        """F14: GatedGateway deducts queue wait from deadline and raises if budget exceeded."""
        gate = InferenceGate(concurrency=1, max_queue=2, queue_timeout=1.0)
        target = MagicMock()
        target.chat.return_value = {"message": {"content": "ok"}}
        gateway = GatedGateway(target, gate)

        # Calling chat with adequate timeout calls target with remaining timeout
        gateway.chat([{"role": "user", "content": "hi"}], allow_tools=False, timeout=10.0)
        self.assertTrue(target.chat.called)
        call_timeout = target.chat.call_args[0][2]
        self.assertLessEqual(call_timeout, 10.0)

        # If timeout is already expired by queue wait
        with patch.object(gate, "enter", return_value=5000.0):
            with self.assertRaises(ApiError) as ctx:
                gateway.chat([{"role": "user", "content": "hi"}], allow_tools=False, timeout=2.0)
            self.assertEqual(ctx.exception.status, 504)
            self.assertEqual(ctx.exception.code, "deadline_exceeded")

    def test_f15_cancellation_priority_preserved(self):
        """F15: Cancellation keywords strictly maintain dispute_agent priority."""
        queries = [
            "Tôi muốn hủy đơn này",
            "hủy đơn O-819125",
            "muốn hủy luôn đơn hàng",
            "hoàn tiền đơn này",
        ]
        for q in queries:
            state = {
                "messages": [{"role": "user", "content": q}],
                "bound": {"context": {"order_id": "O-819125"}},
                "subagent_history": [],
                "trace": {},
            }
            res = run_supervisor(state)
            self.assertEqual(res.get("next_worker"), "dispute_agent")
            self.assertEqual(res.get("trace", {}).get("routing_reason"), "dispute_cancellation_refund")

    def test_f10_application_chat_end_to_end_selected_order(self):
        """F10: End-to-end Application.chat routes focused order to order_agent without 503."""
        import tempfile
        from pathlib import Path
        from retailops_providers import API_MODEL, OpenRouterAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            store = BusinessStore(Path(tmpdir) / 'business.sqlite3')
            store.add_customer('C-001', 'Test Customer')
            with store.connection(write=True) as db:
                db.execute(
                    'INSERT INTO orders(id, customer_id, name, variant, amount, status) VALUES (?,?,?,?,?,?)',
                    ('O-819125', 'C-001', 'Áo sơ mi lụa công sở', 'Trắng / M', 450000, 'pending')
                )
            key = 'test_key_' + 'x' * 40
            adapter = OpenRouterAgent(key, API_MODEL)
            app = Application(store, {}, api_infer=adapter, orchestrator='multi_agent')
            conv = app.new_conversation('C-001', {'provider_id': 'api'})
            cid = conv['conversation_id']

            # Mock model responses: call1 -> get_context, call2 -> get_product, call3 -> final answer
            call1 = {'model': API_MODEL, 'choices': [{
                'message': {
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{
                        'id': 'call_1',
                        'type': 'function',
                        'function': {'name': 'get_context', 'arguments': '{}'}
                    }]
                },
                'finish_reason': 'tool_calls'
            }], 'usage': {'prompt_tokens': 100, 'completion_tokens': 30}}

            call2 = {'model': API_MODEL, 'choices': [{
                'message': {
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{
                        'id': 'call_2',
                        'type': 'function',
                        'function': {'name': 'get_product', 'arguments': '{"product_id": "P-601"}'}
                    }]
                },
                'finish_reason': 'tool_calls'
            }], 'usage': {'prompt_tokens': 150, 'completion_tokens': 30}}

            call3 = {'model': API_MODEL, 'choices': [{
                'message': {
                    'role': 'assistant',
                    'content': 'Sản phẩm Áo sơ mi lụa công sở có chất liệu Lụa tơ tằm nhân tạo và bảo hành 90 ngày tính từ ngày nhận hàng.',
                    'tool_calls': None
                },
                'finish_reason': 'stop'
            }], 'usage': {'prompt_tokens': 200, 'completion_tokens': 50}}

            snapshot = store.conversation('C-001', cid)
            store.remember('C-001', snapshot, 'O-819125', None)

            with patch.object(OpenRouterAgent, 'request', side_effect=[call1, call2, call3]):
                result = app.chat('C-001', {
                    'conversation_id': cid,
                    'text': 'Món này chất liệu gì và bảo hành bao lâu?',
                    'request_id': 'test_request_12345678'
                })

            self.assertEqual(result.get('error'), None)
            self.assertEqual(result['trace']['routing_reason'], 'product_spec_inquiry')
            self.assertEqual(result['trace']['selected_worker'], 'order_agent')
            self.assertIn('Lụa tơ tằm nhân tạo', result['message'])
            self.assertIn('90 ngày', result['message'])
            # Verify no tool_not_allowed error occurred
            tool_errors = [t for t in result['trace'].get('tools', []) if t.get('status') == 'error']
            self.assertEqual(tool_errors, [])

            # Verify ReAct reasoning steps and evaluations are recorded
            steps = result['trace'].get('steps', [])
            self.assertEqual(len(steps), 3)
            self.assertEqual(steps[0]['step'], 1)
            self.assertEqual(steps[0]['action'], 'tool_call')
            self.assertEqual(steps[0]['tools'][0]['name'], 'get_context')
            self.assertEqual(steps[1]['step'], 2)
            self.assertEqual(steps[1]['action'], 'tool_call')
            self.assertEqual(steps[1]['tools'][0]['name'], 'get_product')
            self.assertEqual(steps[2]['step'], 3)
            self.assertEqual(steps[2]['action'], 'final_answer')
            self.assertIn('Đầy đủ dữ kiện', steps[2]['evaluation'])


if __name__ == "__main__":
    unittest.main()
