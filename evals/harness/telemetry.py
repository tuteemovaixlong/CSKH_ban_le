"""Telemetry collector and A0 cache controller for Phase 4 Evaluation.

Normative reference:
- docs/phase4/REVIEW_PHASE_4_PLAN.md (§4)
- docs/phase4/PHASE_4_RESULTS_SCHEMA.md (§3, §4.2)
- docs/phase4/PHASE_4_METRICS_DEFINITION.md (§5, §6)
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from evals.harness.constants import VALID_ZERO_REASONS


class EvaluationOverlayError(RuntimeError):
    """Raised when evaluation invariants (such as A0 Cache OFF) are violated."""
    pass


class TelemetryCollector:
    """Collects per-attempt telemetry with strict R10 measured-zero proof."""

    def __init__(self, run_id: str, case_id: str, logical_request_id: str, attempt_id: str, retry_index: int = 0):
        self.run_id = run_id
        self.case_id = case_id
        self.logical_request_id = logical_request_id
        self.attempt_id = attempt_id
        self.retry_index = retry_index

        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self.finished_at_utc: Optional[str] = None
        self._start_monotonic = time.monotonic()

        self.actual_mode: Optional[str] = None
        self.model_calls: Optional[int] = None
        self.tool_count: Optional[int] = None
        self.tools_called: List[str] = []
        self.cache_hit: Optional[bool] = None
        self.provider_inference_ms: Optional[float] = None
        self.latency_ms: Optional[float] = None
        self.queue_wait_ms: Optional[float] = None
        self.ttfb_ms: Optional[float] = None

        # R10 measured-zero fields
        self.model_invocation_observed: bool = False
        self.zero_reason: Optional[str] = None
        self.unavailable_reason: Optional[str] = None

    def record_no_model_path(self, reason: str, actual_mode: str = "retail") -> None:
        """Records an observed no-model path according to R10 contract."""
        if reason not in VALID_ZERO_REASONS:
            raise ValueError(f"Invalid zero_reason: {reason}, must be in {VALID_ZERO_REASONS}")
        self.actual_mode = actual_mode
        self.model_calls = 0
        self.provider_inference_ms = 0.0
        self.model_invocation_observed = True
        self.zero_reason = reason

    def record_model_invocation(
        self,
        actual_mode: str,
        calls: int,
        provider_ms: float,
        tools_called: Optional[List[str]] = None,
        cache_hit: bool = False,
    ) -> None:
        """Records an observed model invocation."""
        self.actual_mode = actual_mode
        self.model_calls = calls
        self.provider_inference_ms = round(provider_ms, 2)
        self.tools_called = tools_called or []
        self.tool_count = len(self.tools_called)
        self.cache_hit = cache_hit
        self.model_invocation_observed = True
        self.zero_reason = None

    def record_unobserved_invocation(self, reason: str = "telemetry_missing") -> None:
        """Records an unobserved attempt where telemetry is missing or unavailable."""
        self.model_calls = None
        self.provider_inference_ms = None
        self.model_invocation_observed = False
        self.zero_reason = None
        self.unavailable_reason = reason

    def finish(self) -> Dict[str, Any]:
        self.finished_at_utc = datetime.now(timezone.utc).isoformat()
        elapsed_ms = (time.monotonic() - self._start_monotonic) * 1000.0
        self.latency_ms = round(elapsed_ms, 2)

        trace: Dict[str, Any] = {
            "actual_mode": self.actual_mode,
            "model_calls": self.model_calls,
            "tool_count": self.tool_count,
            "tools_called": self.tools_called,
            "cache_hit": self.cache_hit,
            "provider_inference_ms": self.provider_inference_ms,
            "latency_ms": self.latency_ms,
            "queue_wait_ms": self.queue_wait_ms,
            "ttfb_ms": self.ttfb_ms,
            "model_invocation_observed": self.model_invocation_observed,
            "zero_reason": self.zero_reason,
        }
        if self.unavailable_reason:
            trace["unavailable_reason"] = self.unavailable_reason

        return trace


def assert_a0_cache_off(cache_mode: str) -> None:
    """Asserts that the A0 evaluation protocol has semantic answer cache disabled."""
    if cache_mode != "answer_cache_off":
        raise EvaluationOverlayError(
            f"A0 protocol violation: cache_mode must be 'answer_cache_off', got '{cache_mode}'"
        )
