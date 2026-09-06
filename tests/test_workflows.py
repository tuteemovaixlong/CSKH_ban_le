"""Real graph/SQL restart tests; model I/O is a scripted fixture, never a paid call."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.http.routes import api_result
from retailops.workflow import approval
from retailops.workflow.checkpoints import workflow

CUSTOMER = 'C-001'
BODY = {'order_id': 'O-101', 'order_version': 1, 'cancel_reason': 'ordered_by_mistake'}
KEY = 'stable-confirm-request'


class Gateway:
    def __init__(self, fail=False):
        self.fail, self.inputs = fail, []

    def inspect(self):
        return {'name': 'fixture-model', 'digest': 'fixture-digest'}

    def chat(self, messages, allow_tools, timeout):
        self.inputs.append(copy.deepcopy(messages))
        if messages[-1]['role'] == 'user':
            return {'message': {'role': 'assistant', 'content': '', 'tool_calls': [
                {'function': {'name': 'get_order', 'arguments': {'order_id': 'O-101'}}}]}}
        if self.fail:
            raise RuntimeError('Do not leak upstream secret fixture-token')
        return {'message': {'role': 'assistant', 'content': 'Đơn đang chờ xử lý.'}}


class WorkflowCases:
    """Shared SQLite / PostgreSQL assertions; subclasses provide fresh_store()."""
    def application(self, gateway=None, role='customer'):
        return Application(self.fresh_store(), {}, infer=gateway or Gateway(), role=role)

    def create_chat(self, app):
        cid = app.new_conversation(CUSTOMER, {})['conversation_id']
        return {'conversation_id': cid, 'request_id': 'restart-chat-request', 'text': 'Kiểm tra O-101'}

    def create_proposal(self, app):
        return api_result(app, CUSTOMER, 'POST', '/api/cancellation-proposals', BODY)[1]

    def test_chat_resumes_after_tools_without_repeating_saved_model_call(self):
        old_gateway = Gateway(fail=True)
        first = self.application(old_gateway)
        body = self.create_chat(first)
        with self.assertRaises(ApiError) as exc:
            first.chat(CUSTOMER, body)
        self.assertEqual(exc.exception.code, 'agent_response_failed')
        self.assertNotIn('fixture-token', str(exc.exception))
        self.assertEqual(len(old_gateway.inputs), 2)
        gateway = Gateway()
        restarted = self.application(gateway)
        result = restarted.chat(CUSTOMER, body)
        self.assertEqual(len(gateway.inputs), 1)
        self.assertEqual(gateway.inputs[0][-1]['role'], 'tool')
        self.assertEqual(result['context'], {'order_id': 'O-101', 'product_id': 'P-101'})
        self.assertEqual(result['trace']['orchestrator'], 'langgraph')
        self.assertEqual(result['trace']['model_calls'], 2)
        self.assertTrue(restarted.chat(CUSTOMER, body)['replayed'])
        self.assertEqual(len(gateway.inputs), 1)

    def test_completed_graph_survives_crash_before_business_history_commit(self):
        app = self.application()
        body = self.create_chat(app)
        with patch.object(app.store, 'finish_turn', side_effect=OSError('simulated restart')), self.assertRaises(ApiError):
            app.chat(CUSTOMER, body)
        restarted = self.application()
        with patch.object(restarted.infer, 'inspect', side_effect=AssertionError('must not inspect model')):
            result = restarted.chat(CUSTOMER, body)
        self.assertEqual(result['context']['order_id'], 'O-101')
        self.assertEqual(restarted.infer.inputs, [])
        self.assertEqual(sum(e['kind'] == 'agent_replied' for e in restarted.store.events(CUSTOMER)), 1)

    def test_resumed_turn_rejects_stale_order_and_changed_input(self):
        app = self.application(Gateway(fail=True))
        body = self.create_chat(app)
        with self.assertRaises(ApiError):
            app.chat(CUSTOMER, body)
        restarted = self.application()
        with self.assertRaises(ApiError) as exc:
            restarted.chat(CUSTOMER, {**body, 'text': 'Different text'})
        self.assertEqual(exc.exception.code, 'request_conflict')
        p = restarted.store.propose(CUSTOMER, BODY)
        restarted.store.confirm(CUSTOMER, p['proposal_id'], {'confirmed': True}, KEY)
        with self.assertRaises(ApiError) as exc:
            restarted.chat(CUSTOMER, body)
        self.assertEqual(exc.exception.code, 'order_changed_during_chat')
        self.assertEqual(restarted.store.history(CUSTOMER, body['conversation_id']), [])

    def test_confirmation_interrupt_survives_restart_and_requires_explicit_click(self):
        first = self.application()
        p = self.create_proposal(first)
        self.assertEqual(p['workflow_status'], 'awaiting_confirmation')
        self.assertEqual(first.store.orders(CUSTOMER)[0]['status'], 'pending')
        restarted = self.application()
        pending = api_result(restarted, CUSTOMER, 'GET', '/api/cancellation-proposals')[1]['proposals']
        self.assertEqual(pending[0]['proposal_id'], p['proposal_id'])
        with self.assertRaises(ApiError):
            approval.confirm(restarted, CUSTOMER, p['proposal_id'], {'confirmed': False}, KEY)
        result = approval.confirm(restarted, CUSTOMER, p['proposal_id'], {'confirmed': True}, KEY)
        self.assertEqual(result['order']['version'], 2)
        self.assertTrue(approval.confirm(self.application(), CUSTOMER, p['proposal_id'], {'confirmed': True}, KEY)['replayed'])
        self.assertEqual(sum(e['kind'] == 'order_cancelled' for e in restarted.store.events(CUSTOMER)), 1)

    def test_crash_after_cancellation_commit_replays_without_second_transaction(self):
        app = self.application()
        p = self.create_proposal(app)
        original = app.store.confirm
        def crash(*args):
            original(*args)
            raise OSError('process lost response')
        with patch.object(app.store, 'confirm', side_effect=crash), self.assertRaises(OSError):
            approval.confirm(app, CUSTOMER, p['proposal_id'], {'confirmed': True}, KEY)
        restarted = self.application()
        self.assertTrue(approval.confirm(restarted, CUSTOMER, p['proposal_id'], {'confirmed': True}, KEY)['replayed'])
        self.assertEqual(sum(e['kind'] == 'order_cancelled' for e in restarted.store.events(CUSTOMER)), 1)

    def test_approval_resume_rechecks_role_owner_expiry_and_order_version(self):
        app = self.application()
        pid = self.create_proposal(app)['proposal_id']
        for role, customer, expected in [('viewer', CUSTOMER, 'permission_denied'), ('customer', 'C-002', 'proposal_not_found')]:
            with self.subTest(role=role, customer=customer), self.assertRaises(ApiError) as exc:
                approval.confirm(self.application(role=role), customer, pid, {'confirmed': True}, KEY)
            self.assertEqual(exc.exception.code, expected)
        with app.store.connection(write=True) as db:
            db.execute('UPDATE proposals SET expires_at=0 WHERE id=?', (pid,))
        with self.assertRaises(ApiError) as exc:
            approval.confirm(self.application(), CUSTOMER, pid, {'confirmed': True}, KEY)
        self.assertEqual(exc.exception.code, 'inactive_proposal')
        pid = self.create_proposal(app)['proposal_id']
        with app.store.connection(write=True) as db:
            db.execute("UPDATE orders SET version=version+1 WHERE id='O-101'")
        with self.assertRaises(ApiError) as exc:
            approval.confirm(self.application(), CUSTOMER, pid, {'confirmed': True}, KEY)
        self.assertEqual(exc.exception.code, 'stale_order')

    def test_dismissed_interrupt_cannot_be_approved_later(self):
        app = self.application()
        pid = self.create_proposal(app)['proposal_id']
        approval.dismiss(self.application(), CUSTOMER, pid)
        with self.assertRaises(ApiError):
            approval.confirm(self.application(), CUSTOMER, pid, {'confirmed': True}, KEY)
        self.assertEqual(app.store.orders(CUSTOMER)[0]['status'], 'pending')

    def test_database_lease_excludes_other_process_and_fences_stale_writer(self):
        store = self.fresh_store()
        with workflow(store, CUSTOMER, 'test', 'same-key', 'hash', {}) as (first, _):
            with self.assertRaises(ApiError) as exc:
                with workflow(self.fresh_store(), CUSTOMER, 'test', 'same-key', 'hash', {}):
                    self.fail('Two processes acquired the same workflow')
            self.assertEqual(exc.exception.code, 'workflow_busy')
            with store.connection(write=True) as db:
                db.execute('UPDATE graph_runs SET lease_until=0 WHERE id=?', (first.run_id,))
            with workflow(self.fresh_store(), CUSTOMER, 'test', 'same-key', 'hash', {}) as (second, _):
                with self.assertRaises(ApiError) as exc:
                    first.get_tuple(first.config())
                self.assertEqual(exc.exception.code, 'workflow_lease_lost')
                self.assertIsNone(second.get_tuple(second.config()))

    def test_checkpoint_retention_deletes_only_expired_unleased_runs(self):
        store = self.fresh_store()
        with workflow(store, CUSTOMER, 'test', 'old', 'hash', {}, expires_at=time.time()-1) as (old, _):
            with workflow(store, CUSTOMER, 'test', 'new', 'hash', {}):
                with store.connection() as db:
                    self.assertIsNotNone(db.execute('SELECT id FROM graph_runs WHERE id=?', (old.run_id,)).fetchone())
        with workflow(store, CUSTOMER, 'test', 'new', 'hash', {}):
            with store.connection() as db:
                self.assertIsNone(db.execute('SELECT id FROM graph_runs WHERE id=?', (old.run_id,)).fetchone())


class WorkflowTests(WorkflowCases, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'business.sqlite3'
        self.fresh_store().seed()

    def fresh_store(self):
        return BusinessStore(self.path)


if __name__ == '__main__':
    unittest.main()
