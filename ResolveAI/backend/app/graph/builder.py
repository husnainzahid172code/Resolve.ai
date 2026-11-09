"""Builds and compiles the ResolveAI LangGraph with a SQLite checkpointer."""
from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agents.planner import Planner, get_planner
from app.core.config import get_settings
from app.graph.nodes import Nodes
from app.graph.state import AgentState


def _route(state: dict[str, Any]) -> str:
    return state.get("route") or "agent"


def build_graph(planner: Planner | None = None, checkpointer: BaseCheckpointSaver | None = None):
    planner = planner or get_planner()
    n = Nodes(planner)
    g = StateGraph(AgentState)
    g.add_node("understand_complaint", n.understand)
    g.add_node("completeness_check", n.completeness)
    g.add_node("ask_customer", n.ask_customer)
    g.add_node("agent", n.agent)
    g.add_node("tools", n.tools)
    g.add_node("resolution_decision", n.decide)
    g.add_node("validation", n.validate)
    g.add_node("human_approval", n.human_approval)
    g.add_node("final_response", n.finalize)
    g.add_node("send_customer_email", n.send_email)
    g.add_node("resolution_logging", n.log_resolution)
    g.add_node("system_recovery", n.system_recovery)

    g.add_edge(START, "understand_complaint")
    g.add_edge("understand_complaint", "completeness_check")
    g.add_conditional_edges("completeness_check", _route, {"ask_customer": "ask_customer", "investigate": "agent"})
    g.add_edge("ask_customer", "understand_complaint")
    g.add_conditional_edges("agent", _route, {
        "tools": "tools", "agent": "agent", "system_recovery": "system_recovery", "step_limit": "resolution_decision",
    })
    g.add_conditional_edges("tools", _route, {
        "agent": "agent", "ask_customer": "ask_customer", "decide": "resolution_decision",
        "system_recovery": "system_recovery",
    })
    g.add_edge("resolution_decision", "validation")
    g.add_conditional_edges("validation", _route, {
        "human_approval": "human_approval", "agent": "agent", "ask_customer": "ask_customer",
    })
    g.add_conditional_edges("human_approval", _route, {"finalize": "final_response", "ask_customer": "ask_customer"})
    g.add_edge("final_response", "send_customer_email")
    g.add_edge("send_customer_email", "resolution_logging")
    g.add_edge("resolution_logging", END)
    g.add_edge("system_recovery", "agent")

    if checkpointer is None:
        conn = sqlite3.connect(get_settings().checkpoint_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
    return g.compile(checkpointer=checkpointer), planner


def build_memory_graph(planner: Planner | None = None):
    return build_graph(planner, InMemorySaver())
