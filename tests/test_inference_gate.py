"""Unit tests for InferenceGate and GatedGateway concurrency control."""
import threading
import time
import unittest

from retailops.core import ApiError
from retailops.inference_gate import GatedGateway, InferenceGate


class FakeGateway:
    def __init__(self, reply="ok", delay=0.0):
        self.reply = reply
        self.delay = delay
        self.calls = 0

    def chat(self, messages, allow_tools, timeout):
        self.calls += 1
        if self.delay > 0:
            time.sleep(self.delay)
        return {"content": self.reply}

    def chat_scoped(self, messages, allow_tools, timeout, allowed_tools):
        return self.chat(messages, allow_tools, timeout)

    def inspect(self):
        return {"model": "fake"}


class InferenceGateTests(unittest.TestCase):
    def test_immediate_entry_under_concurrency(self):
        gate = InferenceGate(concurrency=2, max_queue=4, queue_timeout=1.0)
        wait1 = gate.enter()
        self.assertEqual(wait1, 0.0)
        self.assertEqual(gate.in_flight, 1)

        wait2 = gate.enter()
        self.assertEqual(wait2, 0.0)
        self.assertEqual(gate.in_flight, 2)

        gate.exit()
        self.assertEqual(gate.in_flight, 1)
        gate.exit()
        self.assertEqual(gate.in_flight, 0)

    def test_queue_overflow_raises_429_model_busy(self):
        gate = InferenceGate(concurrency=1, max_queue=2, queue_timeout=2.0)
        gate.enter()  # Takes the 1 concurrency slot

        # Queue 2 waiters in background
        threads = []
        for _ in range(2):
            t = threading.Thread(target=lambda: gate.enter())
            t.daemon = True
            t.start()
            threads.append(t)

        time.sleep(0.05)
        self.assertEqual(gate.queue_size, 2)

        # 3rd waiter should exceed max_queue=2 and fail immediately with 429 model_busy
        with self.assertRaises(ApiError) as ctx:
            gate.enter()
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "model_busy")

        # Cleanup
        gate.exit()
        gate.exit()
        gate.exit()

    def test_queue_timeout_raises_429_queue_timeout(self):
        gate = InferenceGate(concurrency=1, max_queue=2, queue_timeout=0.05)
        gate.enter()  # Occupies slot

        start = time.monotonic()
        with self.assertRaises(ApiError) as ctx:
            gate.enter()  # Waits up to 0.05s then times out
        elapsed = time.monotonic() - start

        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "queue_timeout")
        self.assertGreaterEqual(elapsed, 0.04)
        gate.exit()

    def test_fifo_ordering_of_waiters(self):
        gate = InferenceGate(concurrency=1, max_queue=5, queue_timeout=2.0)
        gate.enter()

        order_completed = []

        def worker(idx):
            gate.enter()
            order_completed.append(idx)
            gate.exit()

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t3 = threading.Thread(target=worker, args=(3,))

        t1.start()
        time.sleep(0.02)
        t2.start()
        time.sleep(0.02)
        t3.start()
        time.sleep(0.02)

        self.assertEqual(gate.queue_size, 3)

        gate.exit()  # Let t1 in
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)
        t3.join(timeout=1.0)

        self.assertEqual(order_completed, [1, 2, 3])

    def test_conversation_lock_serializes_same_conversation(self):
        gate = InferenceGate()
        order = []

        def worker(tag, delay):
            with gate.conversation("C-001:conv-1"):
                order.append(f"start_{tag}")
                time.sleep(delay)
                order.append(f"end_{tag}")

        t1 = threading.Thread(target=worker, args=("A", 0.05))
        t2 = threading.Thread(target=worker, args=("B", 0.01))

        t1.start()
        time.sleep(0.01)
        t2.start()

        t1.join(timeout=1.0)
        t2.join(timeout=1.0)

        self.assertEqual(order, ["start_A", "end_A", "start_B", "end_B"])

    def test_gated_gateway_tracks_telemetry(self):
        gate = InferenceGate(concurrency=1, max_queue=2, queue_timeout=1.0)
        target = FakeGateway(reply="hello", delay=0.01)
        trace = {}
        gated = GatedGateway(target, gate, trace=trace)

        resp = gated.chat([{"role": "user", "content": "hi"}], False, 10.0)
        self.assertEqual(resp["content"], "hello")
        self.assertIn("queue_wait_ms", trace)
        self.assertIn("in_flight_inferences", trace)
        self.assertEqual(target.calls, 1)

    def test_timeout_handoff_race_relinquishes_permit(self):
        """Race where waiter timeout occurs simultaneously with exit() handoff."""
        gate = InferenceGate(concurrency=1, max_queue=2, queue_timeout=0.05)
        gate.enter()
        self.assertEqual(gate.in_flight, 1)

        event_b = threading.Event()
        with gate._lock:
            gate._queue.append(event_b)
        acquired = event_b.wait(timeout=0.01)
        self.assertFalse(acquired)

        # A calls exit() -> pops event_b and sets it
        gate.exit()

        # B resolves timeout
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

        self.assertEqual(gate.in_flight, 0)
        self.assertEqual(gate.queue_size, 0)

        # Slot must be immediately acquirable by next caller
        wait_ms = gate.enter()
        self.assertEqual(wait_ms, 0.0)
        self.assertEqual(gate.in_flight, 1)
        gate.exit()
        self.assertEqual(gate.in_flight, 0)

    def test_gated_gateway_deducts_queue_wait_from_deadline(self):
        gate = InferenceGate(concurrency=1, max_queue=2, queue_timeout=1.0)
        target = FakeGateway(reply="hello")
        gated = GatedGateway(target, gate)

        # With 10s timeout, target called with valid remaining timeout
        gated.chat([{"role": "user", "content": "hi"}], False, 10.0)
        self.assertEqual(target.calls, 1)

        # With expired remaining timeout after queue wait
        from unittest.mock import patch
        with patch.object(gate, "enter", return_value=5000.0):
            with self.assertRaises(ApiError) as ctx:
                gated.chat([{"role": "user", "content": "hi"}], False, 2.0)
            self.assertEqual(ctx.exception.status, 504)
            self.assertEqual(ctx.exception.code, "deadline_exceeded")


if __name__ == "__main__":
    unittest.main()
