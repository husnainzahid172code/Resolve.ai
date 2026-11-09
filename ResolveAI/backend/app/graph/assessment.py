"""Bridge between graph state (structured tool outputs) and the deterministic policy engine."""
from __future__ import annotations

from typing import Any

from app.schemas.domain import Order, Policy
from app.services import policy_engine


def state_policies(state: dict[str, Any]) -> list[Policy]:
    seen: dict[str, Policy] = {}
    for plist in (state.get("retrieved_policies") or {}).values():
        for p in plist:
            seen[p["policy_id"]] = Policy(**p)
    return list(seen.values())


def state_order(state: dict[str, Any], order_id: str) -> Order | None:
    rec = (state.get("order_information") or {}).get(order_id)
    if rec and rec.get("found"):
        return Order(**rec["order"])
    return None


def facts_for(state: dict[str, Any]) -> dict[str, Any]:
    claims = state.get("customer_claims") or {}
    ev = state.get("evidence_verification") or {}
    return {
        "photo_verified": bool(ev.get("verified")),
        "received_item_description": claims.get("received_item_description"),
    }


def compute_assessments(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Assess every identified issue using only evidence the agent actually retrieved.

    Policies come from the agent's retrieve_store_policies results; thresholds
    the agent did not retrieve fall back to engine defaults, and the validator
    separately fails the case if required policies were not retrieved.
    """
    out = []
    policies = state_policies(state)
    for issue in state.get("identified_issues") or []:
        oid = issue.get("order_id")
        order = state_order(state, oid) if oid else None
        if order is None:
            out.append({"issue": issue["type"], "order_id": oid, "allowed_actions": ["escalate"],
                        "recommended_action": "escalate", "max_amounts": {"escalate": 0.0},
                        "findings": ["Order record not available."], "missing_evidence": [], "policy_ids": []})
            continue
        out.append(policy_engine.assess_issue(issue["type"], order, policies, facts_for(state)))
    return out
