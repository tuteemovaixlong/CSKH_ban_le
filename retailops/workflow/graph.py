"""Multi-Agent StateGraph Builder for RetailOps.
Orchestrates Supervisor and specialized workers with LangGraph checkpointing and state persistence.
"""
import copy
import time
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph
from retailops.workflow.state import MultiAgentState
from retailops.workflow.subagents.dispute_agent import run_dispute_agent
from retailops.workflow.subagents.order_agent import run_order_agent
from retailops.workflow.subagents.policy_agent import run_policy_agent
from retailops.workflow.subagents.witty_agent import run_witty_agent
from retailops.workflow.supervisor import run_supervisor


def build_multiagent_graph(gateway: Any, execute: Any, saver: Any = None):
    """Construct and compile the hierarchical multi-agent state graph."""
    builder = StateGraph(MultiAgentState)

    # 1. Supervisor Node
    builder.add_node("supervisor", run_supervisor)

    # 2. Worker Nodes
    def order_worker(state: MultiAgentState) -> MultiAgentState:
        return run_order_agent(state, execute, gateway)

    def policy_worker(state: MultiAgentState) -> MultiAgentState:
        return run_policy_agent(state, execute, gateway)

    def dispute_worker(state: MultiAgentState) -> MultiAgentState:
        return run_dispute_agent(state, execute, gateway)

    def witty_worker(state: MultiAgentState) -> MultiAgentState:
        return run_witty_agent(state, gateway)

    builder.add_node("order_agent", order_worker)
    builder.add_node("policy_agent", policy_worker)
    builder.add_node("dispute_agent", dispute_worker)
    builder.add_node("witty_agent", witty_worker)

    # 3. Wiring Edges
    builder.add_edge(START, "supervisor")

    def route_supervisor(state: MultiAgentState) -> str:
        if state.get("complete") or state.get("next_worker") in ("direct_response", "human_escalation"):
            return END
        worker = state.get("next_worker", "witty_agent")
        return worker if worker in ("order_agent", "policy_agent", "dispute_agent", "witty_agent") else "witty_agent"

    builder.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "order_agent": "order_agent",
            "policy_agent": "policy_agent",
            "dispute_agent": "dispute_agent",
            "witty_agent": "witty_agent",
            END: END
        }
    )

    builder.add_edge("order_agent", END)
    builder.add_edge("policy_agent", END)
    builder.add_edge("dispute_agent", END)
    builder.add_edge("witty_agent", END)

    return builder.compile(checkpointer=saver)


def run_multiagent(gateway: Any, text: str, history: list, execute: Any, identity: dict,
                   timeout: int = 110, *, saver: Any = None, capture: Any = lambda: {},
                   restore: Any = lambda state: None) -> dict[str, Any]:
    """Top-level invocation interface for the multi-agent system."""
    started = time.monotonic()
    graph = build_multiagent_graph(gateway, execute, saver=saver)
    config = saver.config() if saver else {"recursion_limit": 32, "callbacks": []}

    user_msg = {"role": "user", "content": text}
    initial_state: MultiAgentState = {
        "messages": list(history) + [user_msg],
        "fresh": [user_msg],
        "trace": {
            "turn_id": str(uuid.uuid4()),
            "model": identity.get("name", "slm"),
            "provider": identity.get("provider", "custom"),
            "orchestrator": "multiagent_langgraph",
            "latency_ms": 0.0
        },
        "tool_count": 0,
        "bound": capture(),
        "complete": False,
        "intent": "unknown",
        "next_worker": "supervisor",
        "subagent_history": [],
        "sentiment": "neutral",
        "strict_mode": False,
        "consecutive_ood_count": 0,
        "action_proposal": None,
        "requires_human": False,
        "human_reason": None
    }

    final_state = graph.invoke(initial_state, config)
    final_state["trace"]["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
    restore(final_state.get("bound", {}))

    return {
        "message": final_state["fresh"][-1]["content"],
        "messages": final_state["fresh"],
        "trace": final_state["trace"],
        "intent": final_state.get("intent"),
        "subagent_history": final_state.get("subagent_history"),
        "sentiment": final_state.get("sentiment"),
        "action_proposal": final_state.get("action_proposal"),
        "requires_human": final_state.get("requires_human")
    }
