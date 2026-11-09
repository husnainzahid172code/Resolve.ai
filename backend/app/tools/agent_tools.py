"""Agent tools.

Each tool has (a) a Pydantic schema the LLM sees through structured tool
calling and (b) a deterministic implementation that returns structured data.

Permission boundary: the executor (graph/nodes.py) injects the case's own
`case_id` and only allows order IDs the customer actually supplied in this
case. `save_resolution_log` is implemented here but is *not* offered to the
LLM - only the graph's logging node may call it.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services import evidence_store, policy_engine
from app.services.data_source import LOG_COLUMNS, get_data_source

IssueLiteral = Literal[
    "not_delivered", "late_delivery", "damaged_item", "wrong_item",
    "return_request", "refund_request", "cancellation", "other",
]
ActionLiteral = Literal[
    "refund", "replacement", "return_and_refund", "store_credit", "cancel_order",
    "carrier_investigation", "deny", "no_action_needed", "escalate",
]
PolicyCategory = Literal["returns", "damage", "wrong_item", "refund", "cancellation", "delivery"]


# --------------------------------------------------------------------------
# Schemas exposed to the LLM (class name == tool name, docstring == description)
# --------------------------------------------------------------------------
class lookup_order(BaseModel):
    """Fetch the order record (customer, product, price, dates, status, refund history) by order ID."""

    order_id: str = Field(description="Order ID such as ORD1001")


class get_delivery_status(BaseModel):
    """Get delivery/tracking facts for an order and whether delivery was late, overdue or presumed lost."""

    order_id: str


class retrieve_store_policies(BaseModel):
    """Retrieve the active store policies for a policy category."""

    issue_category: PolicyCategory = Field(description="Policy category to retrieve")
    query: str | None = Field(default=None, description="Optional keywords to rank policies")


class verify_return_eligibility(BaseModel):
    """Deterministically check return eligibility (return window, hygiene exclusion, existing returns)."""

    order_id: str


class verify_damage_evidence(BaseModel):
    """Check whether valid damage photos have been uploaded for this case."""

    case_id: str = Field(description="The current case ID")


class check_previous_refund(BaseModel):
    """Check whether the order was already refunded (duplicate refund protection)."""

    order_id: str


class request_customer_information(BaseModel):
    """Pause the investigation and ask the customer for missing information or evidence."""

    question: str = Field(description="One clear, polite question for the customer")
    missing: list[Literal["order_id", "valid_order_id", "damage_photo", "received_item_description", "issue_details"]] = (
        Field(default_factory=list, description="What information is missing")
    )


class ProposalItem(BaseModel):
    issue: IssueLiteral
    order_id: str
    action: ActionLiteral
    rationale: str = Field(description="Short factual justification citing policy IDs and tool facts")


class submit_resolution_proposal(BaseModel):
    """Submit the proposed resolution (one item per issue) for validation and human approval."""

    items: list[ProposalItem]
    summary: str = Field(description="Concise, auditable decision summary")


LLM_TOOL_SCHEMAS = [
    lookup_order, get_delivery_status, retrieve_store_policies, verify_return_eligibility,
    verify_damage_evidence, check_previous_refund, request_customer_information, submit_resolution_proposal,
]
DATA_TOOLS = {
    "lookup_order", "get_delivery_status", "retrieve_store_policies", "verify_return_eligibility",
    "verify_damage_evidence", "check_previous_refund",
}
CONTROL_TOOLS = {"request_customer_information", "submit_resolution_proposal"}


# --------------------------------------------------------------------------
# Implementations (structured dict outputs; DataSourceUnavailable propagates)
# --------------------------------------------------------------------------
def run_lookup_order(order_id: str) -> dict[str, Any]:
    order = get_data_source().get_order(order_id)
    if order is None:
        return {"order_id": order_id, "found": False, "message": f"No order with ID {order_id} exists in the records."}
    return {"order_id": order_id, "found": True, "order": order.model_dump()}


def run_get_delivery_status(order_id: str) -> dict[str, Any]:
    ds = get_data_source()
    order = ds.get_order(order_id)
    if order is None:
        return {"order_id": order_id, "found": False}
    return {"found": True, **policy_engine.delivery_facts(order, ds.list_policies())}


def _score(policy_text: str, query: str | None) -> int:
    if not query:
        return 0
    words = {w for w in query.lower().split() if len(w) > 2}
    return sum(1 for w in words if w in policy_text.lower())


def run_retrieve_store_policies(issue_category: str, query: str | None = None) -> dict[str, Any]:
    policies = policy_engine.active_policies(get_data_source().list_policies())
    matched = [p for p in policies if p.policy_category == issue_category]
    matched.sort(key=lambda p: -_score(p.policy_description + " " + p.policy_conditions, query))
    return {
        "issue_category": issue_category,
        "count": len(matched),
        "policies": [p.model_dump() for p in matched],
    }


def run_verify_return_eligibility(order_id: str) -> dict[str, Any]:
    ds = get_data_source()
    order = ds.get_order(order_id)
    if order is None:
        return {"order_id": order_id, "found": False}
    return {"found": True, **policy_engine.return_eligibility(order, ds.list_policies())}


def run_verify_damage_evidence(case_id: str) -> dict[str, Any]:
    return evidence_store.verify_case_evidence(case_id)


def run_check_previous_refund(order_id: str) -> dict[str, Any]:
    ds = get_data_source()
    order = ds.get_order(order_id)
    if order is None:
        return {"order_id": order_id, "found": False}
    return {"found": True, **policy_engine.refund_block(order, ds.list_policies())}


def save_resolution_log(case_data: dict[str, Any]) -> dict[str, Any]:
    """System-only tool: write the case to the Resolution Logs sheet/adapter."""
    row = {c: case_data.get(c, "") for c in LOG_COLUMNS}
    get_data_source().append_resolution_log(row)
    return {"saved": True, "case_id": row["case_id"], "destination": get_data_source().label}


TOOL_IMPLEMENTATIONS = {
    "lookup_order": run_lookup_order,
    "get_delivery_status": run_get_delivery_status,
    "retrieve_store_policies": run_retrieve_store_policies,
    "verify_return_eligibility": run_verify_return_eligibility,
    "verify_damage_evidence": run_verify_damage_evidence,
    "check_previous_refund": run_check_previous_refund,
}

SCHEMA_BY_NAME = {s.__name__: s for s in LLM_TOOL_SCHEMAS}

# Customer-safe descriptions shown in the chat progress indicator.
CUSTOMER_SAFE_LABELS = {
    "lookup_order": "Looked up your order",
    "get_delivery_status": "Checked delivery and tracking information",
    "retrieve_store_policies": "Reviewed the relevant store policies",
    "verify_return_eligibility": "Checked return eligibility",
    "verify_damage_evidence": "Checked the photos you provided",
    "check_previous_refund": "Checked previous refunds on the order",
}
