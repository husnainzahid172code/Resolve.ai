"""LangGraph agent state. Persisted by the SQLite checkpointer after every node."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def union_flags(left: list[str] | None, right: list[str] | None) -> list[str]:
    out = list(left or [])
    for f in right or []:
        if f not in out:
            out.append(f)
    return out


class AgentState(TypedDict, total=False):
    # identity & conversation
    case_id: str
    conversation_history: Annotated[list[dict[str, str]], operator.add]
    customer_message: str
    # understanding
    order_id: str | None               # primary order (first supplied)
    order_ids: list[str]
    identified_issues: list[dict[str, Any]]   # [{type, order_id, description}]
    customer_claims: dict[str, Any]           # received_item_description, preferred_resolution
    missing_information: list[str]
    # investigation evidence (structured tool outputs)
    order_information: dict[str, dict[str, Any]]      # order_id -> lookup result
    delivery_information: dict[str, dict[str, Any]]
    retrieved_policies: dict[str, list[dict[str, Any]]]  # category -> policies
    return_eligibility: dict[str, dict[str, Any]]
    refund_checks: dict[str, dict[str, Any]]
    evidence_verification: dict[str, Any] | None
    evidence_count: int
    tools_done: list[str]                     # "tool:arg" keys, used to bound repetition
    investigation_history: Annotated[list[dict[str, Any]], operator.add]
    agent_messages: Annotated[list[BaseMessage], add_messages]
    step_count: int
    # decision & validation
    proposal_request: dict[str, Any] | None   # raw LLM submit_resolution_proposal args
    proposed_resolution: dict[str, Any] | None
    policy_assessments: list[dict[str, Any]]
    validation_result: dict[str, Any] | None
    revision_count: int
    risk_flags: Annotated[list[str], union_flags]
    draft_customer_response: str | None
    # human in the loop
    pending_question: str | None
    pending_question_type: str | None         # agent_question | admin_request
    approval_status: str                      # not_requested | pending | approved | rejected | info_requested
    administrator_decision: dict[str, Any] | None
    final_response: str | None
    email_delivery: dict[str, Any] | None
    # control
    status: str
    system_error: str | None
    route: str | None
    log_saved: bool
