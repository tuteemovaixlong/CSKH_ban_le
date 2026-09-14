"""Unified State Schema for Multi-Agent RetailOps Workflow.
Supports LangGraph checkpointing, subagent routing, guardrails, and human-in-the-loop interrupts.
"""
from typing import Any, Literal, TypedDict

WorkerType = Literal[
    "supervisor",
    "order_agent",
    "policy_agent",
    "dispute_agent",
    "witty_agent",
    "human_escalation",
    "direct_response"
]

IntentType = Literal[
    "order_inquiry",
    "order_cancellation",
    "policy_knowledge",
    "product_consulting",
    "chitchat_general",
    "dispute_complaint",
    "forbidden_topic",
    "unknown"
]


class MultiAgentState(TypedDict):
    # Core conversation channels
    messages: list[dict[str, Any]]
    fresh: list[dict[str, Any]]
    trace: dict[str, Any]
    tool_count: int
    bound: dict[str, Any]
    complete: bool

    # Multi-Agent Routing & Triage
    intent: IntentType
    next_worker: WorkerType
    subagent_history: list[str]

    # Guardrails & Context Safety
    sentiment: str  # positive, neutral, negative
    strict_mode: bool
    consecutive_ood_count: int

    # Human-in-the-loop and Sensitive Proposals
    action_proposal: dict[str, Any] | None
    requires_human: bool
    human_reason: str | None
