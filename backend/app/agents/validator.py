"""Independent, deterministic validation of a proposed resolution.

The validator never trusts the agent's narrative. It recomputes eligibility
from the raw tool outputs stored in state using the policy engine, and checks
that the agent actually performed the investigation steps each issue needs.
"""
from __future__ import annotations

from typing import Any

from app.graph.assessment import compute_assessments
from app.schemas.domain import ISSUE_POLICY_CATEGORIES, REFUND_TYPE_ACTIONS, ValidationCheck, ValidationResult

REQUIRED_STEPS: dict[str, list[str]] = {
    "late_delivery": ["get_delivery_status"],
    "not_delivered": ["get_delivery_status"],
    "return_request": ["verify_return_eligibility"],
    "refund_request": ["verify_return_eligibility"],
    "damaged_item": ["verify_damage_evidence"],
}
MONEY_ISSUES = {"damaged_item", "wrong_item", "return_request", "refund_request", "late_delivery", "not_delivered", "cancellation"}


def validate(state: dict[str, Any]) -> tuple[ValidationResult, list[str], list[dict]]:
    checks: list[ValidationCheck] = []
    flags: list[str] = []
    proposal = state.get("proposed_resolution") or {"items": []}
    items = proposal.get("items", [])
    issues = state.get("identified_issues") or []
    orders = state.get("order_information") or {}
    retrieved = state.get("retrieved_policies") or {}
    done = set(state.get("tools_done") or [])
    case_order_ids = set(state.get("order_ids") or [])
    assessments = {f"{a['issue']}:{a['order_id']}": a for a in compute_assessments(state)}

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append(ValidationCheck(name=name, passed=ok, detail=detail))

    # 1. order exists
    missing_orders = sorted({i["order_id"] for i in items if not orders.get(i["order_id"], {}).get("found")})
    add("order_exists", not missing_orders and bool(items),
        "All referenced orders exist in the records." if not missing_orders and items
        else f"Order(s) not found or not looked up: {', '.join(missing_orders) or 'no items proposed'}.")

    # 2. complaint coverage + order supports complaint
    issue_keys = {f"{i['type']}:{i.get('order_id')}" for i in issues}
    item_keys = {f"{i['issue']}:{i['order_id']}" for i in items}
    uncovered, extra = issue_keys - item_keys, item_keys - issue_keys
    add("all_issues_addressed", not uncovered and not extra,
        "Every identified issue has exactly one proposed action." if not uncovered and not extra
        else f"Unaddressed: {sorted(uncovered)}; not raised by customer: {sorted(extra)}.")
    support_problems = []
    for i in items:
        rec = orders.get(i["order_id"], {}).get("order") or {}
        if i["issue"] in ("damaged_item", "wrong_item", "return_request") and rec and rec.get("delivery_status") != "delivered":
            support_problems.append(f"{i['issue']} on {i['order_id']} but order status is {rec.get('delivery_status')}")
        if i["issue"] == "not_delivered" and rec.get("delivery_status") == "delivered":
            flags.append("delivery_record_conflict")
    add("order_supports_complaint", not support_problems,
        "Order records are consistent with the complaint." if not support_problems else "; ".join(support_problems))

    # 3. policies retrieved by the agent
    missing_cats = sorted({c for i in issues for c in ISSUE_POLICY_CATEGORIES.get(i["type"], []) if not retrieved.get(c)})
    add("policies_retrieved", not missing_cats,
        "Relevant store policies were retrieved." if not missing_cats else f"Policies not retrieved for: {', '.join(missing_cats)}.")

    # 4. required investigation steps were actually executed
    missing_steps = []
    for i in items:
        steps_needed = REQUIRED_STEPS.get(i["issue"], [])
        if i["issue"] == "damaged_item" and i["action"] in ("deny", "escalate", "no_action_needed"):
            steps_needed = []  # evidence only matters when something is being granted
        for tool in steps_needed:
            arg = state["case_id"] if tool == "verify_damage_evidence" else i["order_id"]
            if f"{tool}:{arg}" not in done:
                missing_steps.append(f"{tool}({arg})")
        if i["action"] in REFUND_TYPE_ACTIONS | {"refund"} and f"check_previous_refund:{i['order_id']}" not in done:
            missing_steps.append(f"check_previous_refund({i['order_id']})")
    add("required_investigation_done", not missing_steps,
        "Required investigation tools were executed." if not missing_steps else f"Missing steps: {', '.join(sorted(set(missing_steps)))}.")

    # 5. policy consistency
    inconsistent = []
    for i in items:
        a = assessments.get(f"{i['issue']}:{i['order_id']}")
        if a and i["action"] not in a["allowed_actions"]:
            inconsistent.append(f"{i['action']} not allowed for {i['issue']} on {i['order_id']} (allowed: {', '.join(a['allowed_actions'])})")
    add("policy_consistent", not inconsistent,
        "Proposed actions are permitted by the configured policies." if not inconsistent else "; ".join(inconsistent))

    # 6. required evidence
    needed_evidence: list[str] = []
    for i in items:
        a = assessments.get(f"{i['issue']}:{i['order_id']}") or {}
        if a.get("missing_evidence") and i["action"] not in ("escalate", "deny", "no_action_needed"):
            needed_evidence.extend(a["missing_evidence"])
    add("required_evidence_present", not needed_evidence,
        "Required evidence is available." if not needed_evidence else f"Missing evidence: {', '.join(sorted(set(needed_evidence)))}.")

    # 7. duplicate refund
    dup_orders = [a["order_id"] for a in assessments.values() if a.get("duplicate_refund")]
    dup_violation = [i for i in items if i["order_id"] in dup_orders and i["action"] in REFUND_TYPE_ACTIONS | {"refund"}]
    if dup_orders:
        flags.append("duplicate_refund_request")
    add("no_duplicate_refund", not dup_violation,
        ("Previous refund found and no second refund proposed." if dup_orders else "No previous refund on record.")
        if not dup_violation else f"Second refund proposed for already-refunded order(s) {', '.join(dup_orders)}.")

    # 8. admin approval (always required, P005)
    money = sum(float(i.get("amount") or 0) for i in items)
    add("admin_approval_required", True,
        f"Administrator approval required before any action (P005). Total value: ${money:,.2f}.")

    # 9. unsupported assumptions
    unsupported = []
    retrieved_ids = {p["policy_id"] for plist in retrieved.values() for p in plist}
    for i in items:
        if i["order_id"] not in case_order_ids:
            unsupported.append(f"order {i['order_id']} was not supplied by the customer")
        bad = [pid for pid in i.get("policy_ids", []) if pid not in retrieved_ids]
        if bad:
            unsupported.append(f"cites unretrieved policies {bad}")
        a = assessments.get(f"{i['issue']}:{i['order_id']}") or {}
        cap = (a.get("max_amounts") or {}).get(i["action"])
        if cap is not None and float(i.get("amount") or 0) > cap + 0.001:
            unsupported.append(f"amount {i['amount']} exceeds policy amount {cap}")
    add("no_unsupported_assumptions", not unsupported,
        "Proposal uses only retrieved evidence." if not unsupported else "; ".join(unsupported))

    failed = [c for c in checks if not c.passed]
    revision_count = state.get("revision_count", 0)
    from app.core.config import get_settings

    max_rev = get_settings().max_revisions
    question = None
    if not failed:
        status = "valid"
        feedback = "All checks passed."
    elif items and [o for o in missing_orders if o in orders and not orders[o].get("found")]:
        status = "needs_customer_info"
        feedback = "Order could not be verified."
        not_found = [o for o in missing_orders if o in orders]
        question = (f"I couldn't find order {', '.join(not_found)} in our records. "
                    "Could you double-check the order ID?")
    elif needed_evidence:
        status = "needs_evidence"
        feedback = "Required evidence missing."
        asks = []
        if "damage_photo" in needed_evidence:
            asks.append("a clear photo showing the damage")
        if "received_item_description" in needed_evidence:
            asks.append("a description or photo of the item you received")
        question = "To continue, could you please send " + " and ".join(asks) + "?"
    elif revision_count < max_rev:
        status = "needs_revision"
        feedback = "Validator rejected the proposal: " + " | ".join(f"{c.name}: {c.detail}" for c in failed)
    else:
        status = "escalate"
        feedback = "Validation still failing after revisions; escalated to administrator with failures shown."
        flags.append("validation_failed_escalated")

    if any(i["action"] == "escalate" for i in items):
        flags.append("agent_escalated")
    total = round(money, 2)
    if total >= 100:
        flags.append("high_value_resolution")
    result = ValidationResult(status=status, checks=checks, feedback=feedback, customer_question=question)
    return result, flags, list(assessments.values())
