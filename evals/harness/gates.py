"""R11 Executable Gate State Machine for Phase 4 Evaluation.

Normative reference:
- docs/phase4/PHASE_4_EXECUTION_HANDOFF.md (§1, §4)
- docs/phase4/REVIEW_PHASE_4_PLAN.md (§3)

Rule:
- G5 (LANE_MEASUREMENT_READY) is the ONLY gate that can grant "READY FOR MEASUREMENT" in lane manifest.
- Prior gates (G0-G4) remain strictly "READY FOR HARNESS/PREFLIGHT".
- Gate progression must be sequential: G0 -> G1 -> G2 -> G3 -> G4 -> G5 -> G6.
"""

from typing import Any, Dict, List, Optional, Set


class GateOrderError(ValueError):
    """Raised when an invalid gate transition or out-of-order progression is attempted."""
    pass


class GatePermissionError(PermissionError):
    """Raised when a premature gate attempts to claim READY FOR MEASUREMENT."""
    pass


GATE_G0_SPEC = "G0_SPEC"
GATE_G1_BUILD_HARNESS = "G1_BUILD_HARNESS"
GATE_G2_MERGED_VERIFIED = "G2_MERGED_VERIFIED"
GATE_G3_SMOKE_AUTHORIZED = "G3_SMOKE_AUTHORIZED"
GATE_G4_LIVE_SMOKE = "G4_LIVE_SMOKE"
GATE_G5_LANE_MEASUREMENT_READY = "G5_LANE_MEASUREMENT_READY"
GATE_G6_FULL_MEASUREMENT_AUTHORIZED = "G6_FULL_MEASUREMENT_AUTHORIZED"
GATE_G7_MEASURED = "G7_MEASURED"

GATE_SEQUENCE: List[str] = [
    GATE_G0_SPEC,
    GATE_G1_BUILD_HARNESS,
    GATE_G2_MERGED_VERIFIED,
    GATE_G3_SMOKE_AUTHORIZED,
    GATE_G4_LIVE_SMOKE,
    GATE_G5_LANE_MEASUREMENT_READY,
    GATE_G6_FULL_MEASUREMENT_AUTHORIZED,
    GATE_G7_MEASURED,
]

VALID_GATES: Set[str] = set(GATE_SEQUENCE)

# B6: Strictly ONLY G5 (LANE_MEASUREMENT_READY) can grant "READY FOR MEASUREMENT".
# G6 is full-run execution authorization, not lane readiness declaration.
MEASUREMENT_READY_GATES: Set[str] = {
    GATE_G5_LANE_MEASUREMENT_READY,
}

STATUS_PREFLIGHT = "READY FOR HARNESS/PREFLIGHT"
STATUS_MEASUREMENT_READY = "READY FOR MEASUREMENT"


def assert_gate_readiness(
    current_gate: str, requested_readiness: str, manifest: Optional[Dict[str, Any]] = None
) -> None:
    """Executable assertion enforcing that ONLY G5 can declare READY FOR MEASUREMENT."""
    if current_gate not in VALID_GATES:
        raise GateOrderError(f"Unknown gate identifier: '{current_gate}'. Valid gates: {GATE_SEQUENCE}")

    if requested_readiness not in (STATUS_PREFLIGHT, STATUS_MEASUREMENT_READY):
        raise GatePermissionError(
            f"Invalid readiness status '{requested_readiness}'. Must be one of: "
            f"'{STATUS_PREFLIGHT}', '{STATUS_MEASUREMENT_READY}'."
        )

    if requested_readiness == STATUS_MEASUREMENT_READY:
        if current_gate not in MEASUREMENT_READY_GATES:
            raise GatePermissionError(
                f"R11 Violation: Only gate G5 (LANE_MEASUREMENT_READY) can grant '{STATUS_MEASUREMENT_READY}'. "
                f"Current gate is '{current_gate}', which is strictly restricted to '{STATUS_PREFLIGHT}'."
            )
        if manifest:
            if manifest.get("is_preflight") is True:
                raise GatePermissionError("Preflight bundle cannot grant READY FOR MEASUREMENT")
            h_sha = manifest.get("evaluation_harness_sha")
            if not h_sha:
                raise GatePermissionError("Missing immutable harness SHA; cannot grant READY FOR MEASUREMENT")
            p_id = manifest.get("provider_id", "")
            l_id = manifest.get("lane_id", "")
            if p_id == "mock" or l_id.startswith("mock"):
                raise GatePermissionError(f"Mock provider/lane ('{p_id}'/'{l_id}') cannot grant READY FOR MEASUREMENT")


class Phase4GateStateMachine:
    """Executable sequential state machine governing Phase 4 gate transitions."""

    def __init__(self, initial_gate: str = GATE_G1_BUILD_HARNESS):
        if initial_gate not in VALID_GATES:
            raise GateOrderError(f"Invalid initial gate: '{initial_gate}'")
        self._current_gate = initial_gate
        self._history: List[str] = [initial_gate]

    @property
    def current_gate(self) -> str:
        return self._current_gate

    @property
    def history(self) -> List[str]:
        return list(self._history)

    def transition_to(self, next_gate: str) -> str:
        """Transitions to the next gate strictly in sequential order."""
        if next_gate not in VALID_GATES:
            raise GateOrderError(f"Unknown target gate: '{next_gate}'")

        curr_idx = GATE_SEQUENCE.index(self._current_gate)
        next_idx = GATE_SEQUENCE.index(next_gate)

        if next_idx <= curr_idx:
            raise GateOrderError(
                f"Cannot transition backwards or to same gate: '{self._current_gate}' -> '{next_gate}'"
            )

        if next_idx != curr_idx + 1:
            raise GateOrderError(
                f"Gate skip forbidden: cannot jump from '{self._current_gate}' directly to '{next_gate}'. "
                f"Next required gate is '{GATE_SEQUENCE[curr_idx + 1]}'."
            )

        self._current_gate = next_gate
        self._history.append(next_gate)
        return self._current_gate

    def can_grant_measurement_readiness(self) -> bool:
        """Returns True iff current gate is G5 (LANE_MEASUREMENT_READY)."""
        return self._current_gate in MEASUREMENT_READY_GATES

    def get_readiness_status(self) -> str:
        """Returns the truthful normative readiness status for the current gate."""
        if self.can_grant_measurement_readiness():
            return STATUS_MEASUREMENT_READY
        return STATUS_PREFLIGHT

    def assert_can_set_readiness(self, status: str) -> None:
        """Throws GatePermissionError if the requested status violates current gate rules."""
        assert_gate_readiness(self._current_gate, status)
