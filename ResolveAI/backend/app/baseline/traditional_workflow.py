"""Traditional fixed-workflow baseline (for the academic comparison).

A *reasonable* scripted support flow, of the kind many stores run:
keyword menu classification into ONE category -> require order ID -> look up
order -> follow that category's fixed branch. It uses the same data source
and the same policy thresholds as ResolveAI so the comparison is fair. It is
not deliberately broken; its limitations are structural:
  * one category per conversation (fixed priority order),
  * each branch runs a predetermined list of checks and nothing else,
  * it cannot decide that a different check or extra information is needed.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.agents.safety import extract_order_ids
from app.services import policy_engine
from app.services.data_source import DataSource, DataSourceUnavailable

# Fixed menu, checked in priority order; first match wins.
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("cancellation", [r"\bcancel"]),
    ("damaged_item", [r"damaged?", r"broken", r"cracked", r"defective"]),
    ("wrong_item", [r"wrong (item|product)", r"(product|item) was wrong", r"not what i ordered"]),
    ("delivery", [r"not (yet )?arrived", r"hasn'?t arrived", r"has not arrived", r"\blate\b", r"delayed", r"not received"]),
    ("return_request", [r"\breturn"]),
    ("refund_request", [r"\brefund"]),
]
DELIVERY_ISSUES = {"delivery"}


def classify(text: str) -> str | None:
    low = text.lower()
    for cat, pats in CATEGORY_RULES:
        if any(re.search(p, low) for p in pats):
            return cat
    return None


def run_traditional(turns: list[dict[str, Any]], ds: DataSource, today: date | None = None) -> dict[str, Any]:
    """turns: [{"message": str} | {"photo": True}]  -> transcript + outcome."""
    transcript: list[dict[str, str]] = []
    steps: list[str] = []
    category: str | None = None
    order_id: str | None = None
    photo = False
    outcome: dict[str, Any] = {"status": "open", "action": None, "categories_handled": []}

    def say(text: str) -> None:
        transcript.append({"role": "workflow", "content": text})

    for turn in turns:
        if turn.get("photo"):
            photo = True
            transcript.append({"role": "customer", "content": "[photo uploaded]"})
        else:
            transcript.append({"role": "customer", "content": turn["message"]})
            if category is None:
                category = classify(turn["message"])
                steps.append(f"classify -> {category}")
            ids = extract_order_ids(turn["message"])
            if ids and order_id is None:
                order_id = ids[0]
            elif ids and outcome.get("status") == "order_not_found":
                order_id = ids[0]

        if category is None:
            say("Please choose a category: cancellation, damaged item, wrong item, delivery, return, refund.")
            continue
        if order_id is None:
            say("Please enter your order ID.")
            continue
        try:
            order = ds.get_order(order_id)
            policies = ds.list_policies()
        except DataSourceUnavailable:
            steps.append("lookup_order -> ERROR")
            say("System error. Please try again later.")
            outcome = {"status": "error", "action": None, "categories_handled": []}
            break
        steps.append(f"lookup_order({order_id})")
        if order is None:
            say("Order not found. Please check your order ID.")
            outcome = {"status": "order_not_found", "action": None, "categories_handled": []}
            continue

        action, note = None, ""
        if category == "damaged_item":
            if not photo:
                say("Please upload a photo of the damaged item.")
                outcome = {"status": "awaiting_photo", "action": None, "categories_handled": [category]}
                continue
            action, note = "refund", f"Refund of ${order.product_price:.2f} queued for agent approval."
        elif category == "wrong_item":
            action, note = "replacement", "Replacement queued for agent approval."
        elif category == "delivery":
            steps.append("check_delivery_status")
            if order.delivery_status == "delivered":
                action, note = "no_action_needed", f"Our records show your order was delivered on {order.delivery_date}."
            else:
                action, note = "no_action_needed", f"Your order is {order.delivery_status}. Tracking: {order.tracking_number}."
        elif category in ("return_request", "refund_request"):
            if category == "refund_request":
                steps.append("check_previous_refund")
                if policy_engine.refund_block(order, policies)["duplicate"]:
                    say("This order has already been refunded.")
                    outcome = {"status": "closed", "action": "deny", "categories_handled": [category]}
                    break
            steps.append("check_return_window")
            el = policy_engine.return_eligibility(order, policies, today)
            action = "return_and_refund" if el["eligible"] else "deny"
            note = " ".join(el["reasons"])
        elif category == "cancellation":
            ok = order.delivery_status in ("processing", "pending")
            action = "cancel_order" if ok else "deny"
            note = "Order cancelled." if ok else "Order already shipped and cannot be cancelled."
        say(note)
        outcome = {"status": "proposal", "action": action, "categories_handled": [category]}
        break

    return {"category": category, "order_id": order_id, "steps": steps, "transcript": transcript, "outcome": outcome}
