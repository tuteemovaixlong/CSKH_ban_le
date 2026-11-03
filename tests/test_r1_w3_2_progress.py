"""W3.2 item 6 (W3.2-D10): the progress line of the customer chat. Fake gateway only; no model, no network.

While a turn runs, the page can ask which tools the agent has used so far. The answer holds tool names and
statuses only, belongs to the customer and conversation that asked, and is gone when the turn ends.
"""
import unittest
import uuid

from retailops.business.progress import TurnProgress
from test_r1_w3_2_agent_loop import AgentFixture, ScriptedModel, call, say
from retailops.business.application import Application


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TurnProgressTests(unittest.TestCase):
    KEY = ('C-001', 'conversation-1')

    def test_a_turn_reports_how_far_it_got_and_vanishes_when_it_ends(self):
        progress = TurnProgress()
        self.assertEqual(progress.read(self.KEY), {'active': False})
        progress.start(self.KEY, 'req-1')
        self.assertEqual(progress.read(self.KEY), {'active': True, 'phase': 'start', 'model_calls': 0, 'tools': []})
        progress.update(self.KEY, 'req-1', {'phase': 'tool', 'model_calls': 1,
                                            'tools': [{'name': 'get_order', 'status': 'ok'}, {'name': 'check_inventory', 'status': 'error'}]})
        self.assertEqual(progress.read(self.KEY), {'active': True, 'phase': 'tool', 'model_calls': 1, 'tools': [
            {'name': 'get_order', 'status': 'ok'}, {'name': 'check_inventory', 'status': 'error'}]})
        progress.finish(self.KEY, 'req-1')
        self.assertEqual(progress.read(self.KEY), {'active': False})

    def test_only_the_running_turn_can_change_or_end_its_record(self):
        progress = TurnProgress()
        progress.start(self.KEY, 'req-2')
        progress.update(self.KEY, 'req-1', {'phase': 'done', 'model_calls': 5, 'tools': []})   # an older request
        progress.finish(self.KEY, 'req-1')
        progress.update(('C-002', 'conversation-1'), 'req-2', {'phase': 'done', 'model_calls': 5, 'tools': []})  # another customer
        self.assertEqual(progress.read(self.KEY), {'active': True, 'phase': 'start', 'model_calls': 0, 'tools': []})
        self.assertEqual(progress.read(('C-002', 'conversation-1')), {'active': False})

    def test_only_safe_tool_names_phases_and_counts_are_kept(self):
        progress = TurnProgress()
        progress.start(self.KEY, 'req-1')
        progress.update(self.KEY, 'req-1', {'phase': 'whatever', 'model_calls': 'many', 'tools': [
            {'name': 'get_order<script>', 'status': 'ok'}, {'name': 5}, 'x', {'name': 'get_product', 'status': 'weird'}]})
        self.assertEqual(progress.read(self.KEY), {'active': True, 'phase': 'start', 'model_calls': 0,
                                                   'tools': [{'name': 'get_product', 'status': 'ok'}]})
        progress.update(self.KEY, 'req-1', 'not a dict')  # ignored
        progress.update(self.KEY, 'req-1', {'tools': [{'name': 'get_order', 'status': 'ok'}] * 40})
        self.assertEqual(len(progress.read(self.KEY)['tools']), 12)

    def test_a_record_that_nobody_finished_expires(self):
        clock = Clock()
        progress = TurnProgress(ttl=300.0, clock=clock)
        progress.start(self.KEY, 'req-1')
        clock.now = 299.0
        self.assertTrue(progress.read(self.KEY)['active'])
        clock.now = 301.0
        self.assertEqual(progress.read(self.KEY), {'active': False})


class ProgressDuringATurnTests(AgentFixture):
    def test_a_running_turn_shows_its_tools_and_ends_clean(self):
        seen = []

        def look(messages):
            seen.append(app.turn_progress('C-001', cid))
            return say('Đơn O-701 đã giao.')
        model = ScriptedModel(call(('get_order', {'order_id': 'O-701'}), ('get_product', {'product_id': 'P-102'})), look)
        app = Application(self.store_a, {}, infer=model)
        cid = self.store_a.new_conversation('C-001')['conversation_id']
        self.assertEqual(app.turn_progress('C-001', cid), {'active': False})
        self.say(app, 'Cho em xem đơn O-701', cid)
        self.assertEqual(seen, [{'active': True, 'phase': 'model', 'model_calls': 1, 'tools': [
            {'name': 'get_order', 'status': 'ok'}, {'name': 'get_product', 'status': 'ok'}]}])
        self.assertEqual(app.turn_progress('C-001', cid), {'active': False})   # finished

    def test_a_failed_turn_leaves_no_record_behind(self):
        model = ScriptedModel(lambda m: call(('get_order', {'order_id': f'O-{len(m)}'})), repeat_last=True)
        app = Application(self.store_a, {}, infer=model)
        cid = self.store_a.new_conversation('C-001')['conversation_id']
        with self.assertRaises(Exception):
            self.say(app, 'tra cứu giúp em', cid)
        self.assertEqual(app.turn_progress('C-001', cid), {'active': False})

    def test_another_customer_sees_nothing_of_the_turn(self):
        seen = []

        def look(messages):
            seen.append((app.turn_progress('C-002', cid), app.turn_progress('C-001', 'other-conversation')))
            return say('Xong')
        model = ScriptedModel(call(('get_order', {'order_id': 'O-701'})), look)
        app = Application(self.store_a, {}, infer=model)
        cid = self.store_a.new_conversation('C-001')['conversation_id']
        self.say(app, 'Cho em xem đơn O-701', cid)
        self.assertEqual(seen, [({'active': False}, {'active': False})])


class ProgressRouteTests(AgentFixture):
    def path(self, cid):
        return f'/api/conversations/{cid}/progress'

    def test_the_route_answers_idle_for_the_owner_and_for_a_stranger(self):
        cid = self.request('POST', '/api/conversations', {}, cookie=self.cust1)[1]['conversation_id']
        self.assertEqual(self.request('GET', self.path(cid), cookie=self.cust1), (200, {'active': False}))
        self.assertEqual(self.request('GET', self.path(cid), cookie=self.cust2), (200, {'active': False}))
        self.assertEqual(self.request('GET', self.path(str(uuid.uuid4())), cookie=self.cust1), (200, {'active': False}))

    def test_it_requires_a_session_and_ignores_the_wrong_shape_of_id(self):
        self.assertIn(self.request('GET', self.path(str(uuid.uuid4())))[0], (401, 403))
        status, _ = self.request('GET', '/api/conversations/not-a-uuid/progress', cookie=self.cust1)
        self.assertEqual(status, 404)

    def test_a_chat_in_flight_is_visible_through_the_route_to_its_owner_only(self):
        seen = {}
        holder = {}

        def look(messages):
            seen['owner'] = self.request('GET', self.path(holder['cid']), cookie=self.cust1)
            seen['stranger'] = self.request('GET', self.path(holder['cid']), cookie=self.cust2)
            return say('Đơn O-701 đã giao.')
        self.sessions.infer = ScriptedModel(call(('get_order', {'order_id': 'O-701'})), look)
        holder['cid'] = self.request('POST', '/api/conversations', {'provider_id': 'custom'}, cookie=self.cust1)[1]['conversation_id']
        status, result = self.request('POST', '/api/chat', {'conversation_id': holder['cid'], 'text': 'Cho em xem đơn O-701',
                                                            'request_id': 'req-' + uuid.uuid4().hex}, cookie=self.cust1)
        self.assertEqual(status, 200, result)
        self.assertEqual(seen['owner'], (200, {'active': True, 'phase': 'model', 'model_calls': 1,
                                              'tools': [{'name': 'get_order', 'status': 'ok'}]}))
        self.assertEqual(seen['stranger'], (200, {'active': False}))
        self.assertEqual(self.request('GET', self.path(holder['cid']), cookie=self.cust1), (200, {'active': False}))


if __name__ == '__main__':
    unittest.main()
