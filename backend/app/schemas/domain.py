"""Core domain models shared by tools, policy engine, validator and API."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class IssueType(str, Enum):
    NOT_DELIVERED = "not_delivered"
    LATE_DELIVERY = "late_delivery"
    DAMAGED_ITEM = "damaged_item"
    WRONG_ITEM = "wrong_item"
    RETURN_REQUEST = "return_request"
    REFUND_REQUEST = "refund_request"
    CANCELLATION = "cancellation"
    OTHER = "other"


ISSUE_LABELS = {
    "not_delivered": "Order not arrived",
    "late_delivery": "Late delivery",
    "damaged_item": "Damaged product",
    "wrong_item": "Wrong product delivered",
    "return_request": "Return request",
    "refund_request": "Refund request",
    "cancellation": "Order cancellation",
    "other": "Other",
}

# Maps an issue to the store-policy category that governs it.
ISSUE_POLICY_CATEGORIES: dict[str, list[str]] = {
    "not_delivered": ["delivery"],
    "late_delivery": ["delivery"],
    "damaged_item": ["damage", "refund"],
    "wrong_item": ["wrong_item", "refund"],
    "return_request": ["returns"],
    "refund_request": ["refund", "returns"],
    "cancellation": ["cancellation"],
    "other": [],
}


class ResolutionAction(str, Enum):
    REFUND = "refund"
    REPLACEMENT = "replacement"
    RETURN_AND_REFUND = "return_and_refund"
    STORE_CREDIT = "store_credit"
    CANCEL_ORDER = "cancel_order"
    CARRIER_INVESTIGATION = "carrier_investigation"
    DENY = "deny"
    NO_ACTION_NEEDED = "no_action_needed"
    ESCALATE = "escalate"


REFUND_TYPE_ACTIONS = {"refund", "return_and_refund", "cancel_order", "store_credit"}


class Order(BaseModel):
    order_id: str
    customer_name: str
    customer_email: str
    product_name: str
    product_price: float
    order_date: str
    delivery_status: str  # processing | shipped | in_transit | delivered | lost
    delivery_date: str | None = None
    payment_method: str
    return_status: str = "none"
    previous_refund_status: str = "none"  # none | refunded | refund_pending
    tracking_number: str | None = None
    product_condition: str = "new"  # new | sealed | opened


class Policy(BaseModel):
    policy_id: str
    policy_category: str
    policy_description: str
    policy_conditions: str
    policy_action: str
    active_status: str = "active"

    def params(self) -> dict[str, str]:
        """Parse machine-readable `key=value; key=value` parameters from conditions."""
        out: dict[str, str] = {}
        for part in self.policy_conditions.replace("\n", ";").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out


class Issue(BaseModel):
    type: IssueType
    order_id: str | None = None
    description: str = ""


class ResolutionItem(BaseModel):
    issue: IssueType
    order_id: str
    action: ResolutionAction
    amount: float = 0.0
    policy_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class ProposedResolution(BaseModel):
    items: list[ResolutionItem]
    summary: str


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class ValidationResult(BaseModel):
    status: Literal["valid", "needs_revision", "needs_evidence", "needs_customer_info", "escalate"]
    checks: list[ValidationCheck]
    feedback: str = ""
    requires_admin_approval: bool = True
    customer_question: str | None = None
