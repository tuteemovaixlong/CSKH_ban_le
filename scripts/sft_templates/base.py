"""Base classes and types for SFT case templates.

W6.7.0 Part A.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass
class Brief:
    brief_id: str
    case_id: str
    turn: int
    suite: str
    template: str
    style: str
    persona: str
    intent: str
    must_include: list[str] = field(default_factory=list)
    may_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    earlier_turns: list[dict[str, Any]] = field(default_factory=list)
    length: str = "vừa"  # "ngắn", "vừa", "dài"
    notes: str = ""
    injection: str | None = None
    setup_msg_index: int = 0
    rail_pass: bool = False

    def to_dict(self) -> dict[str, Any]:
        must = list(self.must_include)
        may = list(self.may_include)
        notes = self.notes
        if self.style == "khong_dau":
            from scripts.sft_utterances import strip_vietnamese_accents
            must = [strip_vietnamese_accents(x) for x in must]
            may = [strip_vietnamese_accents(x) for x in may]
            if "viết không dấu" not in notes.lower():
                notes = (notes + " (Lưu ý: Tên sản phẩm và các từ khóa được viết không dấu)").strip()
        elif self.style in ("teencode", "sai_chinh_ta"):
            new_must = []
            pid = next((x for x in may if x.startswith("P-")), None)
            for item in must:
                words = item.split()
                has_code = any(c.isdigit() or c == '-' for c in item)
                if len(words) >= 3 and not has_code:
                    if pid:
                        new_must.append(pid)
                    else:
                        new_must.append(" ".join(words[:2]))
                else:
                    new_must.append(item)
            must = new_must

        data: dict[str, Any] = {
            "brief_id": self.brief_id,
            "case_id": self.case_id,
            "turn": self.turn,
            "suite": self.suite,
            "template": self.template,
            "style": self.style,
            "persona": self.persona,
            "intent": self.intent,
            "must_include": must,
            "may_include": may,
            "must_not_include": self.must_not_include,
            "earlier_turns": self.earlier_turns,
            "length": self.length,
            "notes": notes,
        }
        if self.injection is not None:
            data["injection"] = self.injection
        if self.setup_msg_index != 0:
            data["setup_msg_index"] = self.setup_msg_index
        if self.rail_pass:
            data["rail_pass"] = True
        return data


class BaseTemplate:
    """Base class for all SFT case generation templates."""

    def __init__(
        self,
        template_id: str,
        suite: str,
        target: int,
        allowed_styles: Sequence[str] | None = None,
        description: str = "",
    ):
        assert target <= 15, f"Template {template_id} target {target} exceeds maximum allowed (15)"
        self.template_id = template_id
        self.suite = suite.upper()
        self.target = target
        self.allowed_styles = list(allowed_styles or ["chuan", "teencode", "khong_dau", "sai_chinh_ta", "dai"])
        self.description = description

    def select(self, view: Any) -> list[Any]:
        """Select available data slots matching this template."""
        raise NotImplementedError

    def build(
        self,
        slot: Any,
        rng: random.Random,
        case_index: int,
        style: str,
        view: Any = None,
    ) -> tuple[dict[str, Any], list[Brief]]:
        """Build one concrete case and its customer utterance brief(s)."""
        raise NotImplementedError
