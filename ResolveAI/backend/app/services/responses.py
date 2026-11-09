"""Customer-facing response templates.

Deterministic on purpose: the final message reflects exactly what the
administrator approved, never discloses risk flags or internal notes, and
never claims money has moved (this system only records authorisations).
"""
from __future__ import annotations

from typing import Any

from app.schemas.domain import ISSUE_LABELS


def _money(x: float) -> str:
    return f"${x:,.2f}"


def item_sentence(item: dict[str, Any], product: str) -> str:
    a, amt, oid = item["action"], float(item.get("amount") or 0), item["order_id"]
    return {
        "refund": f"A refund of {_money(amt)} for your {product} ({oid}) has been authorised. Our payments team will process it to your original payment method.",
        "return_and_refund": f"Your return for {product} ({oid}) is approved. Once we receive the item, a refund of {_money(amt)} will be processed to your original payment method. Return instructions will follow by email.",
        "replacement": f"We will send you a replacement {product} ({oid}). If you received an incorrect or damaged item, return instructions will follow by email.",
        "store_credit": f"As an apology, a store credit of {_money(amt)} has been authorised for order {oid}.",
        "cancel_order": f"Order {oid} has been cancelled before shipping. A refund of {_money(amt)} will be processed to your original payment method.",
        "carrier_investigation": f"We have opened an investigation with the carrier for order {oid} and will update you as soon as we hear back.",
        "no_action_needed": f"We checked order {oid}: {ISSUE_LABELS.get(item['issue'], item['issue']).lower()} - everything is within our normal timelines, so no further action is required right now.",
        "deny": f"After reviewing order {oid} against our store policy, we are unable to offer a {ISSUE_LABELS.get(item['issue'], item['issue']).lower()} resolution. {item.get('customer_reason', '')}".strip(),
        "escalate": f"Your request about order {oid} has been passed to a specialist who will contact you directly.",
    }.get(a, f"Your request about order {oid} has been reviewed.")


def build_customer_response(
    proposal: dict[str, Any] | None,
    order_info: dict[str, dict[str, Any]],
    decision: str = "approve",
    customer_reason: str | None = None,
) -> str:
    if decision == "reject":
        reason = customer_reason or "it does not meet our store policy requirements"
        return (
            "Thank you for your patience. A member of our team reviewed your case and we are unable to "
            f"approve the proposed resolution because {reason.rstrip('.')}. "
            "If you have additional information, reply here and we will take another look."
        )
    if not proposal:
        return "Your case has been reviewed by our team."
    parts = ["Thank you for your patience - a member of our team has reviewed your case."]
    for item in proposal.get("items", []):
        rec = order_info.get(item["order_id"], {})
        product = (rec.get("order") or {}).get("product_name", "item")
        parts.append(item_sentence(item, product))
    return " ".join(parts)
