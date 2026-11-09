"""Planners decide (1) what the complaint is about and (2) the next investigation step.

* LLMPlanner     -- the real agent: an OpenAI/Gemini chat model with structured
                    output for analysis and structured tool calling for the
                    investigation loop.
* OfflinePlanner -- a clearly labelled deterministic stand-in used when no LLM
                    key is configured. It emits the *same* tool-call messages
                    through the *same* graph, so the system can be run and
                    tested offline. It is NOT the agentic reasoning the project
                    claims; demos should use an LLM provider.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents import prompts
from app.agents.safety import extract_order_ids, wrap_untrusted
from app.core.config import get_settings
from app.schemas.domain import ISSUE_POLICY_CATEGORIES
from app.services import policy_engine
from app.tools.agent_tools import LLM_TOOL_SCHEMAS

log = logging.getLogger("resolveai.planner")

IssueLiteral = Literal[
    "not_delivered", "late_delivery", "damaged_item", "wrong_item",
    "return_request", "refund_request", "cancellation", "other",
]


class AnalyzedIssue(BaseModel):
    type: IssueLiteral
    order_id: str | None = Field(default=None, description="Order ID for this issue if stated, else null")
    description: str = Field(default="", description="Short paraphrase of the problem")


class ComplaintAnalysis(BaseModel):
    """Structured understanding of one customer message."""

    issues: list[AnalyzedIssue] = Field(default_factory=list)
    received_item_description: str | None = None
    preferred_resolution: Literal["refund", "replacement", "return", "cancel"] | None = None
    suspected_prompt_injection: bool = False


# ---------------------------------------------------------------------------
# Offline keyword analysis (also the fallback if the LLM call fails)
# ---------------------------------------------------------------------------
_KEYWORDS: dict[str, list[str]] = {
    "not_delivered": [r"(not|never|hasn'?t|has not|haven'?t|have not|didn'?t|did not)\s+(yet\s+)?(arrived?|received?|been delivered|come|got)",
                      r"where('?s| is) my (order|parcel|package)", r"not (been )?delivered", r"still (hasn'?t|has not) (arrived|come)"],
    "late_delivery": [r"\blate\b", r"\bdelay(ed)?\b", r"took (too|so) long", r"taking (too|so) long", r"still waiting"],
    "damaged_item": [r"damaged?", r"broken", r"cracked", r"smashed", r"defective", r"shattered", r"dented", r"torn"],
    "wrong_item": [r"wrong (item|product|size|colou?r|model|order)", r"(item|product|it) (was|is) wrong",
                   r"not what i ordered", r"different (item|product)", r"received the wrong", r"sent (me )?the wrong"],
    "return_request": [r"\breturn(ing)?\b(?! label)", r"send (it )?back"],
    "refund_request": [r"\brefund", r"money back", r"reimburse"],
    "cancellation": [r"\bcancel"],
}
_SUBSTANTIVE = {"not_delivered", "late_delivery", "damaged_item", "wrong_item"}
_RECEIVED_RE = re.compile(
    r"(?:received|got|sent me|came with|instead i got|it was)\s+(?:a|an|the|some)?\s*"
    r"(?:pair of\s+)?([a-z0-9][a-z0-9 \-]{2,60}?)(?:\s+instead|\s+rather|[.,!;]|$)",
    re.IGNORECASE,
)


def offline_analyze(text: str) -> ComplaintAnalysis:
    low = (text or "").lower()
    found = [t for t, pats in _KEYWORDS.items() if any(re.search(p, low) for p in pats)]
    if "not_delivered" in found and "late_delivery" in found:
        found.remove("late_delivery")
    if re.search(r"\b(arrived|received|delivered)\b", low) and "late_delivery" in found and re.search(
        r"when it arrived|finally arrived|arrived late|was late", low
    ):
        found = [f for f in found if f != "not_delivered"]
    preferred = None
    if "refund_request" in found and _SUBSTANTIVE & set(found):
        found.remove("refund_request")
        preferred = "refund"
    if "return_request" in found and _SUBSTANTIVE & set(found):
        found.remove("return_request")
        preferred = preferred or "return"
    if re.search(r"replace(ment)?|exchange|send (me )?(a|the) (new|correct)", low):
        preferred = "replacement"
    ids = extract_order_ids(text)
    issues = [AnalyzedIssue(type=t, order_id=ids[0] if len(ids) == 1 else None, description=text[:200]) for t in found]
    received = None
    for m in _RECEIVED_RE.finditer(text or ""):
        cand = m.group(1).strip()
        if not re.search(r"wrong|order|\d+ days?|late|damaged|broken|ago", cand, re.I) and len(cand) > 2:
            received = cand
            break
    return ComplaintAnalysis(issues=issues, received_item_description=received, preferred_resolution=preferred)


class Planner:
    name = "base"

    def analyze(self, text: str) -> ComplaintAnalysis:  # pragma: no cover - interface
        raise NotImplementedError

    def next_action(self, state: dict[str, Any], messages: list[BaseMessage]) -> AIMessage:  # pragma: no cover
        raise NotImplementedError


def _call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}"}])


class OfflinePlanner(Planner):
    """Deterministic, state-driven planner (demo/testing stand-in for the LLM)."""

    name = "offline"

    def analyze(self, text: str) -> ComplaintAnalysis:
        return offline_analyze(text)

    def next_action(self, state: dict[str, Any], messages: list[BaseMessage]) -> AIMessage:
        done: set[str] = set(state.get("tools_done") or [])
        issues = state.get("identified_issues") or []
        orders = state.get("order_information") or {}
        claims = state.get("customer_claims") or {}
        case_id = state["case_id"]

        order_ids = sorted({i["order_id"] for i in issues if i.get("order_id")})
        for oid in order_ids:
            if f"lookup_order:{oid}" not in done:
                return _call("lookup_order", order_id=oid)
        missing = [oid for oid in order_ids if not orders.get(oid, {}).get("found")]
        if missing:
            return _call(
                "request_customer_information",
                question=(
                    f"I couldn't find an order with the ID {', '.join(missing)} in our records. "
                    "Could you double-check the order ID (it looks like ORD followed by 4 digits)?"
                ),
                missing=["valid_order_id"],
            )

        for issue in issues:
            for cat in ISSUE_POLICY_CATEGORIES.get(issue["type"], []):
                if f"retrieve_store_policies:{cat}" not in done:
                    return _call("retrieve_store_policies", issue_category=cat)

        asks: list[str] = []
        missing_kinds: list[str] = []
        for issue in issues:
            oid, t = issue["order_id"], issue["type"]
            if t in ("late_delivery", "not_delivered") and f"get_delivery_status:{oid}" not in done:
                return _call("get_delivery_status", order_id=oid)
            if t in ("return_request", "refund_request") and f"verify_return_eligibility:{oid}" not in done:
                return _call("verify_return_eligibility", order_id=oid)
            if t in ("damaged_item", "wrong_item", "return_request", "refund_request", "late_delivery",
                     "not_delivered", "cancellation") and f"check_previous_refund:{oid}" not in done:
                return _call("check_previous_refund", order_id=oid)
            already_refunded = (state.get("refund_checks") or {}).get(oid, {}).get("duplicate")
            if already_refunded:
                continue  # money outcome is blocked by P006; more evidence would not change the result
            if t == "damaged_item":
                if f"verify_damage_evidence:{case_id}" not in done:
                    return _call("verify_damage_evidence", case_id=case_id)
                if not (state.get("evidence_verification") or {}).get("verified"):
                    asks.append("a clear photo showing the damage")
                    missing_kinds.append("damage_photo")
            if t == "wrong_item" and not claims.get("received_item_description"):
                if not (state.get("evidence_verification") or {}).get("verified"):
                    asks.append("a short description (or photo) of the item you actually received")
                    missing_kinds.append("received_item_description")
        if asks:
            return _call(
                "request_customer_information",
                question="To continue the investigation, could you please send " + " and ".join(asks) + "?",
                missing=missing_kinds,
            )

        # Evidence complete -> propose what the deterministic policy assessment recommends.
        from app.graph.assessment import compute_assessments

        previews = {f"{a['issue']}:{a['order_id']}": a for a in compute_assessments(state)}
        items = []
        for issue in issues:
            a = previews.get(f"{issue['type']}:{issue['order_id']}")
            action = (a or {}).get("recommended_action") or "escalate"
            findings = "; ".join((a or {}).get("findings", []))[:300]
            items.append({"issue": issue["type"], "order_id": issue["order_id"], "action": action,
                          "rationale": findings or "Escalated for human review."})
        summary = "; ".join(f"{i['issue']} on {i['order_id']} -> {i['action']}" for i in items)
        return _call("submit_resolution_proposal", items=items, summary=summary)


class LLMPlanner(Planner):
    name = "llm"

    def __init__(self, model: BaseChatModel, label: str = "llm") -> None:
        self.model = model
        self.name = label
        self._with_tools = model.bind_tools(LLM_TOOL_SCHEMAS)

    def analyze(self, text: str) -> ComplaintAnalysis:
        try:
            structured = self.model.with_structured_output(ComplaintAnalysis)
            result = structured.invoke(
                [SystemMessage(prompts.ANALYSIS_SYSTEM_PROMPT), HumanMessage(wrap_untrusted(text))]
            )
            if isinstance(result, dict):
                result = ComplaintAnalysis(**result)
            # Deterministic guard: only keep order IDs that literally appear in the text.
            literal_ids = set(extract_order_ids(text))
            for issue in result.issues:
                if issue.order_id and issue.order_id.upper() not in literal_ids:
                    issue.order_id = None
            return result
        except Exception as exc:  # noqa: BLE001 - fall back, recorded by the node
            log.warning("LLM analysis failed, using keyword fallback: %s", exc)
            fallback = offline_analyze(text)
            fallback.__dict__["_fallback_reason"] = str(exc)
            return fallback

    def next_action(self, state: dict[str, Any], messages: list[BaseMessage]) -> AIMessage:
        convo = [SystemMessage(prompts.INVESTIGATION_SYSTEM_PROMPT), HumanMessage(prompts.case_brief(state)), *messages]
        result = self._with_tools.invoke(convo)
        if not isinstance(result, AIMessage):
            result = AIMessage(content=str(getattr(result, "content", result)))
        return result


def build_chat_model() -> tuple[BaseChatModel | None, str]:
    s = get_settings()
    provider = s.resolved_llm_provider
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=s.llm_temperature,
                          timeout=s.llm_timeout_seconds, max_retries=s.llm_max_retries), f"openai:{s.openai_model}"
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=s.gemini_model, google_api_key=s.google_api_key,
                                      temperature=s.llm_temperature, timeout=s.llm_timeout_seconds,
                                      max_retries=s.llm_max_retries), f"gemini:{s.gemini_model}"
    return None, "offline"


def get_planner() -> Planner:
    model, label = build_chat_model()
    return LLMPlanner(model, label) if model is not None else OfflinePlanner()


# re-exported for the offline planner's preview of deterministic assessments
assess_issue = policy_engine.assess_issue
