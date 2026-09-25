"""Bounded Concurrency Gate for Model I/O.

Guarantees FIFO queuing, bounds concurrent in-flight model calls (default K=1 for GPU L4),
prevents Waitress worker thread exhaustion via admission timeouts, and serializes
requests to the same conversation to prevent checkpoint state corruption.
"""
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Dict, Optional

from retailops.core import ApiError


class InferenceGate:
    """Manages concurrent model inferences and per-conversation execution serialization."""

    def __init__(
        self,
        concurrency: Optional[int] = None,
        max_queue: Optional[int] = None,
        queue_timeout: Optional[float] = None,
    ):
        if concurrency is None:
            concurrency = int(os.environ.get("RETAILOPS_INFERENCE_CONCURRENCY", "1"))
        if max_queue is None:
            max_queue = int(os.environ.get("RETAILOPS_INFERENCE_QUEUE_MAX", "8"))
        if queue_timeout is None:
            queue_timeout = float(os.environ.get("RETAILOPS_INFERENCE_QUEUE_TIMEOUT", "10.0"))

        if concurrency < 1:
            raise ValueError("Inference concurrency must be at least 1.")
        if max_queue < 0:
            raise ValueError("Inference max queue must be non-negative.")
        if queue_timeout <= 0:
            raise ValueError("Inference queue timeout must be positive.")

        self.concurrency = concurrency
        self.max_queue = max_queue
        self.queue_timeout = queue_timeout

        self._lock = threading.Lock()
        self._active_count = 0
        self._queue = deque()
        self._conversation_locks: Dict[str, threading.Lock] = {}
        self.total_queued_requests = 0
        self.total_rejected_requests = 0
        self.total_timeout_requests = 0

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._active_count

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def get_conversation_lock(self, conversation_key: str) -> threading.Lock:
        """Returns the mutex for a specific conversation to serialize turns."""
        with self._lock:
            if conversation_key not in self._conversation_locks:
                self._conversation_locks[conversation_key] = threading.Lock()
            return self._conversation_locks[conversation_key]

    @contextmanager
    def conversation(self, conversation_key: str):
        """Context manager serializing multiple turns within the same conversation."""
        conv_lock = self.get_conversation_lock(conversation_key)
        conv_lock.acquire()
        try:
            yield
        finally:
            conv_lock.release()

    def enter(self) -> float:
        """Requests an inference slot within queue_timeout.

        Returns:
            wait_ms: Wait duration in milliseconds.
        Raises:
            ApiError(429, 'model_busy'): If the queue is at capacity.
            ApiError(429, 'queue_timeout'): If waiting time exceeds queue_timeout.
        """
        start_wait = time.monotonic()
        event = threading.Event()

        with self._lock:
            if self._active_count < self.concurrency and not self._queue:
                self._active_count += 1
                return 0.0

            if len(self._queue) >= self.max_queue:
                self.total_rejected_requests += 1
                raise ApiError(
                    429,
                    "model_busy",
                    "Hệ thống đang phục vụ tối đa lượt yêu cầu. Vui lòng thử lại sau giây lát.",
                )

            self._queue.append(event)
            self.total_queued_requests += 1

        acquired = event.wait(timeout=self.queue_timeout)
        wait_ms = round((time.monotonic() - start_wait) * 1000.0, 2)

        if not acquired:
            with self._lock:
                try:
                    self._queue.remove(event)
                except ValueError:
                    pass
                self.total_timeout_requests += 1
            raise ApiError(
                429,
                "queue_timeout",
                "Thời gian chờ suy luận model quá hạn. Vui lòng thử lại.",
            )

        return wait_ms

    def exit(self) -> None:
        """Releases the inference slot and grants access to the next queued caller."""
        with self._lock:
            if self._queue:
                next_event = self._queue.popleft()
                next_event.set()
            else:
                self._active_count = max(0, self._active_count - 1)

    @contextmanager
    def inferencing(self):
        """Context manager for model I/O call."""
        wait_ms = self.enter()
        try:
            yield wait_ms
        finally:
            self.exit()


class GatedGateway:
    """Transparent proxy wrapping a ModelGateway with the bounded InferenceGate."""

    def __init__(self, target, gate: InferenceGate, trace: Optional[dict] = None):
        self._target = target
        self._gate = gate
        self._trace = trace
        self.total_queue_wait_ms = 0.0

    def __getattr__(self, name):
        return getattr(self._target, name)

    def chat(self, messages, allow_tools: bool, timeout: float):
        with self._gate.inferencing() as wait_ms:
            self.total_queue_wait_ms = round(self.total_queue_wait_ms + wait_ms, 2)
            if self._trace is not None and isinstance(self._trace, dict):
                self._trace["queue_wait_ms"] = round(
                    self._trace.get("queue_wait_ms", 0.0) + wait_ms, 2
                )
                self._trace["in_flight_inferences"] = self._gate.in_flight
            return self._target.chat(messages, allow_tools, timeout)

    def chat_scoped(self, messages, allow_tools: bool, timeout: float, allowed_tools):
        scoped = getattr(self._target, "chat_scoped", None)
        with self._gate.inferencing() as wait_ms:
            self.total_queue_wait_ms = round(self.total_queue_wait_ms + wait_ms, 2)
            if self._trace is not None and isinstance(self._trace, dict):
                self._trace["queue_wait_ms"] = round(
                    self._trace.get("queue_wait_ms", 0.0) + wait_ms, 2
                )
                self._trace["in_flight_inferences"] = self._gate.in_flight
            if callable(scoped):
                return scoped(messages, allow_tools, timeout, allowed_tools)
            return self._target.chat(messages, allow_tools, timeout)
