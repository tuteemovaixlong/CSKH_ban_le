"""Qrels (Query Relevance) and Grounding evaluation module for Phase 4.

Normative reference:
- docs/phase4/REVIEW_PHASE_4_PLAN.md (§5)
- docs/phase4/PHASE_4_RESULTS_SCHEMA.md (§4.4)
- docs/phase4/PHASE_4_METRICS_DEFINITION.md (§4)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import hashlib
import json
import math

QRELS_VERSION = "qrels-v1"
QRELS_SOURCE = "evals/qrels/policy_qrels_v1.json"


@dataclass
class QrelEntry:
    query_id: str
    case_id: str
    topic: str
    relevant_sources: Dict[str, int]  # source_id -> relevance grade (1 or 2)
    no_evidence: bool = False
    answerability_status: str = "answerable"


def compute_ndcg_at_k(relevance_map: Dict[str, int], retrieved: List[str], k: int = 5) -> float:
    """Computes Normalized Discounted Cumulative Gain at k (nDCG@k)."""
    if not relevance_map:
        return 0.0

    retrieved_k = retrieved[:k]
    dcg = 0.0
    for idx, item in enumerate(retrieved_k):
        rel = relevance_map.get(item, 0)
        dcg += (2**rel - 1) / math.log2(idx + 2)

    # Ideal DCG
    ideal_rels = sorted(relevance_map.values(), reverse=True)[:k]
    idcg = sum((2**rel - 1) / math.log2(idx + 2) for idx, rel in enumerate(ideal_rels))

    if idcg <= 0.0:
        return 0.0
    return round(dcg / idcg, 4)


def compute_mrr(relevant_ids: Set[str], retrieved: List[str]) -> float:
    """Computes Mean Reciprocal Rank (MRR)."""
    if not relevant_ids:
        return 0.0
    for idx, item in enumerate(retrieved, start=1):
        if item in relevant_ids:
            return round(1.0 / idx, 4)
    return 0.0


def compute_recall_at_k(relevant_ids: Set[str], retrieved: List[str], k: int = 5) -> float:
    """Computes Recall@k."""
    if not relevant_ids:
        return 0.0
    retrieved_k = set(retrieved[:k])
    return round(len(relevant_ids & retrieved_k) / len(relevant_ids), 4)


def compute_precision_at_k(relevant_ids: Set[str], retrieved: List[str], k: int = 5) -> float:
    """Computes Precision@k."""
    if k <= 0:
        return 0.0
    retrieved_k = set(retrieved[:k])
    return round(len(relevant_ids & retrieved_k) / k, 4)


class QrelsManager:
    """Loads and checks versioned Qrels for retrieval and grounding grading."""

    def __init__(self, qrels_path: Optional[Path] = None):
        if qrels_path is None:
            qrels_path = Path(__file__).resolve().parents[1] / "qrels" / "policy_qrels_v1.json"
        self.qrels_path = Path(qrels_path)
        self.version = QRELS_VERSION
        self.source = QRELS_SOURCE
        self.entries: Dict[str, QrelEntry] = {}
        self.sha256 = ""
        if self.qrels_path.is_file():
            self._load()

    def _load(self) -> None:
        raw_text = self.qrels_path.read_text(encoding="utf-8")
        self.sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        data = json.loads(raw_text)
        for item in data.get("queries", []):
            entry = QrelEntry(
                query_id=item["query_id"],
                case_id=item["case_id"],
                topic=item.get("topic", "policy"),
                relevant_sources=item.get("relevant_sources", {}),
                no_evidence=item.get("no_evidence", False),
                answerability_status=item.get("answerability_status", "answerable"),
            )
            self.entries[entry.case_id] = entry
            self.entries[entry.query_id] = entry

    def get_entry(self, case_or_query_id: str) -> Optional[QrelEntry]:
        return self.entries.get(case_or_query_id)
