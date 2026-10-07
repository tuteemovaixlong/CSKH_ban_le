"""Sidecar resolver for 250 benchmark cases.

Maps case_id -> tenant_id, principal_id, customer_id, role, focus, prior turns,
answerability status, and claim references idempotently.

Normative reference:
- docs/phase4/REVIEW_PHASE_4_PLAN.md (§4)
- docs/phase4/PLAN_PHASE_4_EVALUATION.md (§3)
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import re

ORDER_PATTERN = re.compile(r"\b(O(?:RD)?[-_]?[0-9]{3,6})\b", re.IGNORECASE)
PRODUCT_PATTERN = re.compile(r"\b(P[-_]?[0-9]{3,6})\b", re.IGNORECASE)


@dataclass
class CaseSidecar:
    case_id: str
    scenario_family: str
    split: str
    tenant_id: str = "shop_retailops_eval"
    principal_id: str = ""
    customer_id: str = ""
    role: str = "customer"
    focus_order_id: Optional[str] = None
    focus_product_id: Optional[str] = None
    prior_turns: List[Dict[str, str]] = field(default_factory=list)
    answerability_status: str = "answerable"
    claim_refs: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.principal_id:
            self.principal_id = f"p_{self.case_id}"
        if not self.customer_id:
            self.customer_id = f"c_{self.case_id}"


def build_sidecar_for_case(case: Dict[str, Any]) -> CaseSidecar:
    cid = case["id"]
    category = case.get("category", "general")
    split = case.get("split", "dev")
    user_text = case.get("user_text", "")
    expected_tools = case.get("expected_tools", [])

    # Extract explicit entities if present
    order_match = ORDER_PATTERN.search(user_text)
    prod_match = PRODUCT_PATTERN.search(user_text)
    focus_oid = order_match.group(1).upper() if order_match else None
    focus_pid = prod_match.group(1).upper() if prod_match else None

    # If expected tool is get_order and no order in user_text, assign a synthetic order fixture
    if not focus_oid and "get_order" in expected_tools:
        focus_oid = f"O-EVAL-{cid}"

    # Determine answerability
    if category == "general":
        answerability = "not-applicable"
    elif "request_human_support" in expected_tools:
        answerability = "labeled-unanswerable"
    else:
        answerability = "answerable"

    claim_refs = [f"claim_{category}_{cid}"]

    return CaseSidecar(
        case_id=cid,
        scenario_family=category,
        split=split,
        tenant_id="shop_retailops_eval",
        principal_id=f"p_{cid}",
        customer_id=f"c_{cid}",
        role="customer",
        focus_order_id=focus_oid,
        focus_product_id=focus_pid,
        prior_turns=[],
        answerability_status=answerability,
        claim_refs=claim_refs,
    )


def generate_benchmark_sidecar(
    dataset_path: Path, output_path: Optional[Path] = None
) -> Tuple[Dict[str, Dict[str, Any]], str]:
    """Reads benchmark JSONL and outputs deterministic sidecar dictionary and SHA-256."""
    text = Path(dataset_path).read_text(encoding="utf-8")
    sidecar_dict: Dict[str, Dict[str, Any]] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        sc = build_sidecar_for_case(case)
        sidecar_dict[sc.case_id] = asdict(sc)

    serialized = json.dumps(sidecar_dict, indent=2, sort_keys=True, ensure_ascii=False)
    sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")

    return sidecar_dict, sha256
