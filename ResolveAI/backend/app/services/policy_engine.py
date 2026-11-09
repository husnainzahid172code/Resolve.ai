"""Deterministic policy engine.

The LLM chooses *what to investigate* and *what to propose*; this module
decides *what is allowed* and *how much money is involved*. Thresholds are
read from the `policy_conditions` column of the Store Policies sheet
(`key=value; ...`), so editing the sheet changes behaviour without code.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.schemas.domain import ISSUE_POLICY_CATEGORIES, Order, Policy

DEFAULTS = {
    "return_window_days": "7",
    "late_threshold_days": "7",
    "late_credit_percent": "10",
    "lost_after_days": "14",
    "report_window_days": "14",
    "hygiene_keywords": "toothbrush|razor|earbuds|cosmetic",
    "excluded_condition": "opened",
    "blocked_previous_refund_status": "refunded|refund_pending",
    "cancellable_statuses": "processing|pending",
}


def _parse_date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def active_policies(policies: list[Policy]) -> list[Policy]:
    return [p for p in policies if p.active_status.strip().lower() == "active"]


def merged_params(policies: list[Policy]) -> dict[str, str]:
    params = dict(DEFAULTS)
    for p in active_policies(policies):
        params.update(p.params())
    return params


def policies_for_issue(issue: str, policies: list[Policy]) -> list[Policy]:
    cats = ISSUE_POLICY_CATEGORIES.get(issue, [])
    return [p for p in active_policies(policies) if p.policy_category in cats]


def delivery_facts(order: Order, policies: list[Policy], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    prm = merged_params(policies)
    ordered = _parse_date(order.order_date)
    delivered = _parse_date(order.delivery_date)
    late_threshold = int(prm["late_threshold_days"])
    lost_after = int(prm["lost_after_days"])
    facts: dict[str, Any] = {
        "order_id": order.order_id,
        "delivery_status": order.delivery_status,
        "tracking_number": order.tracking_number or None,
        "order_date": order.order_date,
        "delivery_date": order.delivery_date,
        "late_threshold_days": late_threshold,
        "lost_after_days": lost_after,
    }
    if delivered and ordered:
        facts["delivery_days"] = (delivered - ordered).days
        facts["days_since_delivery"] = (today - delivered).days
        facts["was_late"] = facts["delivery_days"] > late_threshold
    elif ordered:
        facts["days_since_order"] = (today - ordered).days
        facts["delivery_days"] = None
        facts["is_overdue"] = facts["days_since_order"] > late_threshold
        facts["presumed_lost"] = facts["days_since_order"] > lost_after
    return facts


def return_eligibility(order: Order, policies: list[Policy], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    prm = merged_params(policies)
    window = int(prm["return_window_days"])
    reasons: list[str] = []
    eligible = True
    delivered = _parse_date(order.delivery_date)
    days = (today - delivered).days if delivered else None
    if order.delivery_status != "delivered" or delivered is None:
        eligible = False
        reasons.append("Order has not been delivered yet, so a return cannot start (P001).")
    elif days is not None and days > window:
        eligible = False
        reasons.append(f"Delivered {days} days ago; the configured return window is {window} days (P001).")
    hygiene_words = [w.strip().lower() for w in prm["hygiene_keywords"].split("|") if w.strip()]
    is_hygiene = any(w in order.product_name.lower() for w in hygiene_words)
    if is_hygiene and order.product_condition.lower() == prm["excluded_condition"].lower():
        eligible = False
        reasons.append("Opened hygiene product; not eligible for return (P002).")
    if order.return_status not in ("", "none"):
        eligible = False
        reasons.append(f"A return is already recorded for this order (status: {order.return_status}).")
    if eligible:
        reasons.append(f"Delivered {days} days ago, within the {window}-day window (P001).")
    return {
        "order_id": order.order_id,
        "eligible": eligible,
        "days_since_delivery": days,
        "return_window_days": window,
        "is_hygiene_product": is_hygiene,
        "product_condition": order.product_condition,
        "reasons": reasons,
        "policy_ids": ["P001", "P002"],
    }


def refund_block(order: Order, policies: list[Policy]) -> dict[str, Any]:
    prm = merged_params(policies)
    blocked = [s.strip() for s in prm["blocked_previous_refund_status"].split("|")]
    status = (order.previous_refund_status or "none").strip().lower()
    return {
        "order_id": order.order_id,
        "previous_refund_status": status,
        "duplicate": status in blocked,
        "policy_ids": ["P006"],
    }


def assess_issue(
    issue: str,
    order: Order,
    policies: list[Policy],
    facts: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return the deterministic set of allowed actions and amounts for one issue.

    facts: {"photo_verified": bool, "received_item_description": str | None}
    """
    facts = facts or {}
    today = today or date.today()
    prm = merged_params(policies)
    price = round(float(order.product_price), 2)
    out: dict[str, Any] = {
        "issue": issue,
        "order_id": order.order_id,
        "allowed_actions": [],
        "recommended_action": None,
        "max_amounts": {},
        "findings": [],
        "missing_evidence": [],
        "policy_ids": [p.policy_id for p in policies_for_issue(issue, policies)],
    }
    dup = refund_block(order, policies)

    def allow(action: str, amount: float = 0.0) -> None:
        if action not in out["allowed_actions"]:
            out["allowed_actions"].append(action)
        out["max_amounts"][action] = round(amount, 2)

    if issue == "damaged_item":
        if order.delivery_status != "delivered":
            out["findings"].append("Order is not marked delivered; damage claim cannot be confirmed.")
            allow("escalate")
        elif not facts.get("photo_verified"):
            out["missing_evidence"].append("damage_photo")
            out["findings"].append("Photo evidence of the damage is required (P003).")
        else:
            out["findings"].append("Photo evidence received and passed file checks (P003).")
            allow("replacement", 0.0)
            allow("refund", price)
        out["recommended_action"] = "replacement" if "replacement" in out["allowed_actions"] else None

    elif issue == "wrong_item":
        if order.delivery_status != "delivered":
            out["findings"].append("Order not delivered yet; a wrong-item claim cannot be checked.")
            allow("escalate")
        elif not (facts.get("received_item_description") or facts.get("photo_verified")):
            out["missing_evidence"].append("received_item_description")
            out["findings"].append(
                f"Ordered item is '{order.product_name}'. Need a description or photo of the item received (P004)."
            )
        else:
            out["findings"].append(
                f"Ordered '{order.product_name}'; customer reports receiving "
                f"'{facts.get('received_item_description') or 'item shown in photo'}' (P004)."
            )
            allow("replacement", 0.0)
            allow("refund", price)
            out["recommended_action"] = "replacement"

    elif issue in ("late_delivery", "not_delivered"):
        df = delivery_facts(order, policies, today)
        pct = float(prm["late_credit_percent"])
        if order.delivery_status == "delivered":
            if issue == "not_delivered":
                out["findings"].append(
                    f"Carrier record shows delivered on {order.delivery_date}, conflicting with the customer's report."
                )
                allow("carrier_investigation")
                out["recommended_action"] = "carrier_investigation"
            if df.get("was_late"):
                out["findings"].append(
                    f"Delivered in {df['delivery_days']} days; threshold is {df['late_threshold_days']} days -> late (P008)."
                )
                allow("store_credit", price * pct / 100)
                out["recommended_action"] = out["recommended_action"] or "store_credit"
            elif issue == "late_delivery":
                out["findings"].append(
                    f"Delivered in {df['delivery_days']} days, within the {df['late_threshold_days']}-day threshold (P008)."
                )
                allow("no_action_needed")
                out["recommended_action"] = "no_action_needed"
        elif order.delivery_status in ("shipped", "in_transit"):
            days = df.get("days_since_order", 0)
            if df.get("presumed_lost"):
                out["findings"].append(f"In transit for {days} days, beyond {df['lost_after_days']} days -> presumed lost (P008).")
                allow("replacement", 0.0)
                allow("refund", price)
                out["recommended_action"] = "replacement"
            elif df.get("is_overdue"):
                out["findings"].append(
                    f"In transit for {days} days, beyond the {df['late_threshold_days']}-day threshold (P008)."
                )
                allow("carrier_investigation")
                allow("store_credit", price * pct / 100)
                out["recommended_action"] = "carrier_investigation"
            else:
                out["findings"].append(f"In transit for {days} days; still within the expected window (P008).")
                allow("no_action_needed")
                out["recommended_action"] = "no_action_needed"
        elif order.delivery_status == "lost":
            allow("replacement", 0.0)
            allow("refund", price)
            out["recommended_action"] = "replacement"
        else:  # processing
            out["findings"].append("Order is still being processed and has not shipped.")
            allow("no_action_needed")
            allow("cancel_order", price)
            out["recommended_action"] = "no_action_needed"

    elif issue in ("return_request", "refund_request"):
        el = return_eligibility(order, policies, today)
        out["findings"].extend(el["reasons"])
        if el["eligible"]:
            allow("return_and_refund", price)
            out["recommended_action"] = "return_and_refund"
        else:
            allow("deny")
            allow("escalate")  # admin may grant an exception
            out["recommended_action"] = "deny"
        out["policy_ids"] = sorted(set(out["policy_ids"]) | {"P001", "P002", "P005"})

    elif issue == "cancellation":
        cancellable = [s.strip() for s in prm["cancellable_statuses"].split("|")]
        if order.delivery_status in cancellable:
            out["findings"].append(f"Fulfillment status '{order.delivery_status}' allows cancellation (P007).")
            allow("cancel_order", price)
            out["recommended_action"] = "cancel_order"
        else:
            out["findings"].append(
                f"Fulfillment status '{order.delivery_status}' does not allow cancellation; a return may apply (P007)."
            )
            allow("deny")
            out["recommended_action"] = "deny"

    else:
        allow("escalate")
        out["recommended_action"] = "escalate"

    # Duplicate refund guard (P006) overrides money-moving actions.
    if dup["duplicate"]:
        out["findings"].append(
            f"Order already has refund status '{dup['previous_refund_status']}'. A second refund is not allowed (P006)."
        )
        for a in ("refund", "return_and_refund", "store_credit", "cancel_order"):
            if a in out["allowed_actions"]:
                out["allowed_actions"].remove(a)
                out["max_amounts"].pop(a, None)
        for a in ("deny", "escalate"):
            allow(a)
        if out["recommended_action"] not in out["allowed_actions"]:
            out["recommended_action"] = "deny"
        if "P006" not in out["policy_ids"]:
            out["policy_ids"].append("P006")
        out["duplicate_refund"] = True

    # escalate to a human is always permitted
    if "escalate" not in out["allowed_actions"]:
        out["allowed_actions"].append("escalate")
        out["max_amounts"]["escalate"] = 0.0
    return out
