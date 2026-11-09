"""LangGraph node implementations.

Each node returns a partial state update plus a `route` key that the
conditional edges in builder.py read. Nodes that pause (ask_customer,
human_approval, system_recovery) call LangGraph's `interrupt()`; the case is
checkpointed and resumes in the same thread when the customer/admin responds.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import interrupt
from pydantic import ValidationError

from app.agents import validator as validator_mod
from app.agents.planner import Planner
from app.agents.safety import detect_prompt_injection, extract_order_ids, wrap_untrusted
from app.core.config import get_settings
from app.graph.assessment import compute_assessments
from app.schemas.domain import ISSUE_LABELS
from app.services.data_source import DataSourceUnavailable
from app.services.responses import build_customer_response
from app.tools import agent_tools as T

log = logging.getLogger("resolveai.graph")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hist(step: str, **kw: Any) -> dict[str, Any]:
    return {"at": _now(), "step": step, **kw}


# ---------------------------------------------------------------------------
class Nodes:
    def __init__(self, planner: Planner) -> None:
        self.planner = planner

    # ------------------------------------------------------------------ understand
    def understand(self, state: dict) -> dict:
        text = state.get("customer_message") or ""
        analysis = self.planner.analyze(text)
        fallback = analysis.__dict__.get("_fallback_reason")
        literal_ids = extract_order_ids(text)

        order_ids = list(state.get("order_ids") or [])
        new_ids = [o for o in literal_ids if o not in order_ids]
        order_ids.extend(new_ids)

        issues = [dict(i) for i in (state.get("identified_issues") or [])]
        missing_prev = set(state.get("missing_information") or [])
        orders = state.get("order_information") or {}

        # Customer corrected an order ID that was not found -> re-point those issues.
        if new_ids and "valid_order_id" in missing_prev:
            bad = {oid for oid, rec in orders.items() if not rec.get("found")}
            for i in issues:
                if i.get("order_id") in bad:
                    i["order_id"] = new_ids[0]
            order_ids = [o for o in order_ids if o not in bad]

        known_types = {i["type"] for i in issues}
        for ai in analysis.issues:
            if ai.type == "other" and issues:
                continue
            if ai.type not in known_types:
                oid = ai.order_id if ai.order_id in order_ids else None
                issues.append({"type": ai.type, "order_id": oid, "description": (ai.description or text)[:300]})
                known_types.add(ai.type)
            else:
                for i in issues:
                    if i["type"] == ai.type and not i.get("order_id") and ai.order_id in order_ids:
                        i["order_id"] = ai.order_id

        # Fill unassigned issues: one known order -> it applies to all; otherwise use new IDs in order.
        unassigned = [i for i in issues if not i.get("order_id")]
        if unassigned:
            pool = new_ids or (order_ids if len(order_ids) == 1 else [])
            if len(pool) == 1:
                for i in unassigned:
                    i["order_id"] = pool[0]
            else:
                for i, oid in zip(unassigned, pool):
                    i["order_id"] = oid

        claims = dict(state.get("customer_claims") or {})
        if analysis.received_item_description:
            claims["received_item_description"] = analysis.received_item_description
        elif "received_item_description" in missing_prev and len(text.strip()) > 3 and not literal_ids:
            claims["received_item_description"] = text.strip()[:200]
        if analysis.preferred_resolution:
            claims["preferred_resolution"] = analysis.preferred_resolution

        flags: list[str] = []
        if detect_prompt_injection(text) or analysis.suspected_prompt_injection:
            flags.append("prompt_injection_attempt")
        if fallback:
            flags.append("llm_analysis_fallback")

        update: dict[str, Any] = {
            "order_ids": order_ids,
            "order_id": state.get("order_id") or (order_ids[0] if order_ids else None),
            "identified_issues": issues,
            "customer_claims": claims,
            "risk_flags": flags,
            "status": "investigating",
            "investigation_history": [
                _hist("understand", summary=f"Issues: {[i['type'] for i in issues]}; orders: {order_ids}",
                      planner=self.planner.name, injection_detected="prompt_injection_attempt" in flags)
            ],
        }
        if state.get("agent_messages"):
            update["agent_messages"] = [HumanMessage(f"New customer message:\n{wrap_untrusted(text)}")]
        return update

    # ------------------------------------------------------------------ completeness
    def completeness(self, state: dict) -> dict:
        issues = state.get("identified_issues") or []
        missing: list[str] = []
        if not issues:
            missing.append("issue_details")
        if any(not i.get("order_id") for i in issues) or not state.get("order_ids"):
            missing.append("order_id")
        if not missing:
            return {"missing_information": [], "route": "investigate"}

        labels = [ISSUE_LABELS[i["type"]].lower() for i in issues]
        if "issue_details" in missing and "order_id" in missing:
            q = "I'm here to help. Could you tell me what went wrong with your order, and share your order ID (for example ORD1001)?"
        elif "issue_details" in missing:
            q = f"Thanks - I have order {', '.join(state.get('order_ids'))}. Could you describe what went wrong?"
        elif len(issues) > 1:
            unassigned = [ISSUE_LABELS[i["type"]].lower() for i in issues if not i.get("order_id")]
            q = (f"I can investigate all of these: {', '.join(labels)}. Could you provide your order ID"
                 f"{' for: ' + ', '.join(unassigned) if len(unassigned) < len(issues) else ''}? "
                 "If the problems relate to different orders, please share each order ID.")
        else:
            q = f"I can help with the {labels[0]}. Could you provide your order ID (for example ORD1001)?"
        return {"missing_information": missing, "pending_question": q, "pending_question_type": "agent_question",
                "route": "ask_customer",
                "investigation_history": [_hist("completeness_check", summary=f"Missing: {missing}")]}

    # ------------------------------------------------------------------ ask customer (interrupt)
    def ask_customer(self, state: dict) -> dict:
        question = state.get("pending_question") or "Could you share more details?"
        payload = interrupt({
            "type": "customer_input",
            "question": question,
            "missing": state.get("missing_information") or [],
            "requested_by": state.get("pending_question_type") or "agent_question",
        })
        payload = payload or {}
        message = str(payload.get("message") or "").strip()
        update: dict[str, Any] = {
            "conversation_history": [{"role": "agent", "content": question}, {"role": "customer", "content": message}],
            "customer_message": message,
            "pending_question": None,
            "status": "investigating",
            "proposed_resolution": None,
            "validation_result": None,
            "proposal_request": None,
            "investigation_history": [_hist("customer_response", summary="Customer replied"
                                            + (" with new photo evidence" if payload.get("evidence_uploaded") else ""))],
        }
        if payload.get("evidence_uploaded"):
            update["evidence_count"] = int(payload.get("evidence_count") or (state.get("evidence_count", 0) + 1))
            update["evidence_verification"] = None
            update["tools_done"] = [t for t in (state.get("tools_done") or []) if not t.startswith("verify_damage_evidence:")]
        return update

    # ------------------------------------------------------------------ agent (LLM decides next step)
    def agent(self, state: dict) -> dict:
        steps = int(state.get("step_count", 0)) + 1
        if steps > get_settings().max_agent_steps:
            return {"step_count": steps, "route": "step_limit",
                    "risk_flags": ["agent_step_limit_reached"],
                    "investigation_history": [_hist("agent", summary="Step limit reached; escalating to administrator")]}
        try:
            ai = self.planner.next_action(state, list(state.get("agent_messages") or []))
        except Exception as exc:  # LLM timeout / provider outage
            log.exception("planner failure")
            return {"step_count": steps, "system_error": f"Agent model unavailable: {type(exc).__name__}: {exc}",
                    "route": "system_recovery", "status": "awaiting_system_recovery",
                    "investigation_history": [_hist("agent_error", ok=False, summary=str(exc)[:300])]}
        calls = ai.tool_calls or []
        if not calls:
            return {"step_count": steps, "route": "agent",
                    "agent_messages": [ai, HumanMessage(
                        "System: respond only by calling a tool - gather evidence, call request_customer_information, "
                        "or call submit_resolution_proposal.")],
                    "investigation_history": [_hist("agent", summary="Model answered without a tool call; nudged")]}
        return {"step_count": steps, "agent_messages": [ai], "route": "tools",
                "investigation_history": [_hist("agent_decision", planner=getattr(self.planner, "last_model", self.planner.name),
                                                summary="Selected: " + ", ".join(c["name"] for c in calls),
                                                tool_calls=[{"name": c["name"], "args": c["args"]} for c in calls])]}

    # ------------------------------------------------------------------ tool executor
    def tools(self, state: dict) -> dict:
        last = next((m for m in reversed(state.get("agent_messages") or []) if isinstance(m, AIMessage)), None)
        calls = (last.tool_calls if last else None) or []
        case_id = state["case_id"]
        allowed_orders = set(state.get("order_ids") or [])

        upd: dict[str, Any] = {
            "order_information": dict(state.get("order_information") or {}),
            "delivery_information": dict(state.get("delivery_information") or {}),
            "retrieved_policies": dict(state.get("retrieved_policies") or {}),
            "return_eligibility": dict(state.get("return_eligibility") or {}),
            "refund_checks": dict(state.get("refund_checks") or {}),
            "tools_done": list(state.get("tools_done") or []),
        }
        msgs: list[ToolMessage] = []
        history: list[dict] = []
        route = "agent"
        failed = False

        for call in calls:
            name, args, cid = call["name"], dict(call.get("args") or {}), call["id"]
            if failed:
                msgs.append(ToolMessage("Not executed: data source unavailable.", tool_call_id=cid, name=name))
                continue
            schema = T.SCHEMA_BY_NAME.get(name)
            if schema is None:
                msgs.append(ToolMessage(f"Error: unknown tool '{name}'.", tool_call_id=cid, name=name))
                history.append(_hist("tool", tool=name, ok=False, summary="Unknown tool rejected"))
                continue
            try:
                parsed = schema(**args)
            except ValidationError as exc:
                msgs.append(ToolMessage(f"Error: invalid arguments: {exc.errors()[:3]}", tool_call_id=cid, name=name))
                history.append(_hist("tool", tool=name, ok=False, summary="Invalid arguments rejected"))
                continue

            if name == "request_customer_information":
                upd.update(pending_question=parsed.question, pending_question_type="agent_question",
                           missing_information=list(parsed.missing))
                msgs.append(ToolMessage("Question queued for the customer; investigation paused.", tool_call_id=cid, name=name))
                history.append(_hist("tool", tool=name, ok=True, summary=f"Asked customer: {parsed.question}"))
                route = "ask_customer"
                continue
            if name == "submit_resolution_proposal":
                upd["proposal_request"] = parsed.model_dump()
                msgs.append(ToolMessage("Proposal received and sent to independent validation.", tool_call_id=cid, name=name))
                history.append(_hist("tool", tool=name, ok=True, summary=parsed.summary[:300]))
                if route == "agent":
                    route = "decide"
                continue

            # ---- data tools: enforce permission boundary ----
            arg_key: str
            if name == "verify_damage_evidence":
                arg_key = case_id  # always the current case, whatever the model passed
                kwargs = {"case_id": case_id}
            elif name == "retrieve_store_policies":
                arg_key = parsed.issue_category
                kwargs = {"issue_category": parsed.issue_category, "query": parsed.query}
            else:
                oid = parsed.order_id.strip().upper()
                if oid not in allowed_orders:
                    msgs.append(ToolMessage(
                        f"Permission denied: order {oid} was not supplied by the customer in this case.",
                        tool_call_id=cid, name=name))
                    history.append(_hist("tool", tool=name, ok=False, args={"order_id": oid},
                                         summary="Blocked: order not part of this case"))
                    upd.setdefault("risk_flags", []).append("agent_requested_foreign_order")
                    continue
                arg_key, kwargs = oid, {"order_id": oid}
            try:
                result = T.TOOL_IMPLEMENTATIONS[name](**kwargs)
            except DataSourceUnavailable as exc:
                failed = True
                upd["system_error"] = str(exc)
                msgs.append(ToolMessage(f"Error: data source unavailable ({exc}). Do not guess.", tool_call_id=cid, name=name))
                history.append(_hist("tool", tool=name, args=kwargs, ok=False, summary=f"FAILED: {exc}"))
                route = "system_recovery"
                continue

            key = f"{name}:{arg_key}"
            if key not in upd["tools_done"]:
                upd["tools_done"].append(key)
            if name == "lookup_order":
                upd["order_information"][arg_key] = result
            elif name == "get_delivery_status":
                upd["delivery_information"][arg_key] = result
            elif name == "retrieve_store_policies":
                upd["retrieved_policies"][arg_key] = result["policies"]
            elif name == "verify_return_eligibility":
                upd["return_eligibility"][arg_key] = result
            elif name == "check_previous_refund":
                upd["refund_checks"][arg_key] = result
            elif name == "verify_damage_evidence":
                upd["evidence_verification"] = result
            msgs.append(ToolMessage(_compact(result), tool_call_id=cid, name=name))
            history.append(_hist("tool", tool=name, args=kwargs, ok=True, summary=_summarise(name, result), result=result))

        if route == "system_recovery":
            upd["status"] = "awaiting_system_recovery"
        upd.update(agent_messages=msgs, investigation_history=history, route=route)
        return upd

    # ------------------------------------------------------------------ resolution decision
    def decide(self, state: dict) -> dict:
        req = state.get("proposal_request") or {}
        if state.get("route") == "step_limit" or not req:
            req = {"items": [{"issue": i["type"], "order_id": i.get("order_id") or "UNKNOWN", "action": "escalate",
                              "rationale": "Investigation step limit reached."} for i in state.get("identified_issues") or []],
                   "summary": "Escalated: the agent could not complete the investigation within its step budget."}
        assessments = {f"{a['issue']}:{a['order_id']}": a for a in compute_assessments(state)}
        retrieved_ids = {p["policy_id"] for pl in (state.get("retrieved_policies") or {}).values() for p in pl}
        items = []
        for it in req["items"]:
            a = assessments.get(f"{it['issue']}:{it['order_id']}") or {}
            allowed = it["action"] in a.get("allowed_actions", [])
            amount = float((a.get("max_amounts") or {}).get(it["action"], 0.0)) if allowed else 0.0
            customer_reason = ""
            if it["action"] == "deny":
                customer_reason = " ".join(re.sub(r"\s*\(P\d{3}\)", "", f) for f in a.get("findings", [])[:2])
            items.append({**it, "amount": round(amount, 2),
                          "policy_ids": [p for p in a.get("policy_ids", []) if p in retrieved_ids],
                          "customer_reason": customer_reason})
        proposal = {"items": items, "summary": req.get("summary", "")[:600]}
        return {"proposed_resolution": proposal, "policy_assessments": list(assessments.values()),
                "investigation_history": [_hist("resolution_decision",
                                                summary="; ".join(f"{i['issue']}->{i['action']} ${i['amount']:.2f}" for i in items))]}

    # ------------------------------------------------------------------ independent validation
    def validate(self, state: dict) -> dict:
        result, flags, assessments = validator_mod.validate(state)
        upd: dict[str, Any] = {
            "validation_result": result.model_dump(),
            "risk_flags": flags,
            "policy_assessments": assessments,
            "investigation_history": [_hist("validation", ok=result.status == "valid",
                                            summary=f"{result.status}: {result.feedback}"[:400])],
        }
        if result.status in ("valid", "escalate"):
            upd.update(route="human_approval", status="pending_approval", approval_status="pending",
                       draft_customer_response=build_customer_response(state.get("proposed_resolution"),
                                                                        state.get("order_information") or {}))
        elif result.status == "needs_revision":
            upd.update(route="agent", revision_count=int(state.get("revision_count", 0)) + 1,
                       agent_messages=[HumanMessage(f"Independent validator feedback - revise your investigation or proposal:\n{result.feedback}")])
        else:  # needs_evidence | needs_customer_info
            missing = ["damage_photo"] if "photo" in (result.customer_question or "") else []
            if "received" in (result.customer_question or ""):
                missing.append("received_item_description")
            if result.status == "needs_customer_info":
                missing = ["valid_order_id"]
            upd.update(route="ask_customer", pending_question=result.customer_question,
                       pending_question_type="agent_question", missing_information=missing,
                       agent_messages=[HumanMessage(f"Validator: {result.feedback} The customer has been asked: {result.customer_question}")])
        return upd

    # ------------------------------------------------------------------ human approval (interrupt)
    def human_approval(self, state: dict) -> dict:
        decision = interrupt({"type": "admin_review", "case_id": state["case_id"],
                              "validation_status": (state.get("validation_result") or {}).get("status")}) or {}
        kind = decision.get("decision")
        rec = {k: decision.get(k) for k in ("decision", "admin", "note", "reason", "question", "customer_response", "at")}
        hist = [_hist("human_approval", summary=f"Administrator decision: {kind}", admin=decision.get("admin"))]
        if kind == "request_information":
            q = decision.get("question") or "Could you share more details about your issue?"
            return {"administrator_decision": rec, "approval_status": "info_requested", "status": "info_requested",
                    "pending_question": q, "pending_question_type": "admin_request", "missing_information": ["issue_details"],
                    "route": "ask_customer", "investigation_history": hist,
                    "agent_messages": [HumanMessage(f"An administrator requested more information from the customer: {q}")]}
        if kind == "reject":
            return {"administrator_decision": rec, "approval_status": "rejected", "route": "finalize", "investigation_history": hist}
        return {"administrator_decision": rec, "approval_status": "approved", "route": "finalize", "investigation_history": hist}

    # ------------------------------------------------------------------ final response
    def finalize(self, state: dict) -> dict:
        dec = state.get("administrator_decision") or {}
        approved = state.get("approval_status") == "approved"
        if dec.get("customer_response"):
            text = str(dec["customer_response"]).strip()
        elif approved:
            text = state.get("draft_customer_response") or build_customer_response(
                state.get("proposed_resolution"), state.get("order_information") or {})
        else:
            text = build_customer_response(None, {}, "reject", dec.get("reason"))
        return {"final_response": text, "status": "approved" if approved else "rejected",
                "conversation_history": [{"role": "agent", "content": text}],
                "investigation_history": [_hist("final_response", summary="Customer response generated")]}

    # ------------------------------------------------------------------ send email (irreversible, post-approval)
    def send_email(self, state: dict) -> dict:
        """Runs only after the human_approval interrupt has returned a decision."""
        from app.services.email_service import send_case_email

        if state.get("approval_status") not in ("approved", "rejected"):
            return {"investigation_history": [_hist("send_customer_email", ok=False,
                                                    summary="Blocked: no administrator decision recorded")]}
        orders = state.get("order_information") or {}
        primary = next((r["order"] for oid in (state.get("order_ids") or [])
                        if (r := orders.get(oid)) and r.get("found")), None)
        if not primary:
            return {"email_delivery": {"status": "skipped", "error": "No verified customer email on file"},
                    "investigation_history": [_hist("send_customer_email", ok=False, summary="Skipped: no verified order/email")]}
        body = (f"Dear {primary['customer_name']},\n\n{state.get('final_response', '')}\n\n"
                f"Case reference: {state['case_id']}\n\nResolveAI Customer Support\n"
                "(This message was approved by a member of our team.)")
        res = send_case_email(state["case_id"], primary["customer_email"],
                              f"Update on your support case {state['case_id']}", body)
        upd: dict[str, Any] = {"email_delivery": res, "investigation_history": [
            _hist("send_customer_email", ok=res["status"] != "failed", tool="gmail_send",
                  summary=f"Email {res['status']} via {res['mode']} to {res['to_address']}"
                          + (f" ({res['error']})" if res.get("error") else ""))]}
        if res["status"] == "failed":
            upd["risk_flags"] = ["email_send_failed"]
        return upd

    # ------------------------------------------------------------------ logging
    def log_resolution(self, state: dict) -> dict:
        prop = state.get("proposed_resolution") or {}
        row = {
            "case_id": state["case_id"],
            "timestamp": _now(),
            "order_id": ", ".join(state.get("order_ids") or []),
            "customer_message": " | ".join(t["content"] for t in state.get("conversation_history") or [] if t["role"] == "customer")[:2000],
            "issue_categories": ", ".join(i["type"] for i in state.get("identified_issues") or []),
            "retrieved_order_information": _compact({k: (v.get("order") or {}).get("product_name") for k, v in (state.get("order_information") or {}).items()}),
            "retrieved_policy_evidence": ", ".join(sorted({p["policy_id"] for pl in (state.get("retrieved_policies") or {}).values() for p in pl})),
            "proposed_action": "; ".join(f"{i['issue']}:{i['action']}:{i['amount']}" for i in prop.get("items", [])),
            "decision_summary": (prop.get("summary", "") + f" | customer email: "
                                 f"{(state.get('email_delivery') or {}).get('status', 'not sent')}"),
            "risk_flags": ", ".join(state.get("risk_flags") or []),
            "validation_status": (state.get("validation_result") or {}).get("status", ""),
            "approval_status": state.get("approval_status", ""),
            "admin_decision": _compact(state.get("administrator_decision") or {}),
            "final_customer_response": state.get("final_response", ""),
        }
        try:
            T.save_resolution_log(row)
            return {"log_saved": True, "investigation_history": [_hist("resolution_logging", ok=True, summary="Saved to resolution log")]}
        except DataSourceUnavailable as exc:
            return {"log_saved": False, "risk_flags": ["log_sync_failed"],
                    "investigation_history": [_hist("resolution_logging", ok=False, summary=f"Log write failed: {exc}")]}

    # ------------------------------------------------------------------ system recovery (interrupt)
    def system_recovery(self, state: dict) -> dict:
        payload = interrupt({"type": "system_recovery", "error": state.get("system_error")}) or {}
        return {"system_error": None, "status": "investigating",
                "agent_messages": [HumanMessage("System: a retry was requested after a data-source/model failure. "
                                                "Retry the step that failed; do not assume any results.")],
                "investigation_history": [_hist("system_recovery", summary=f"Retry requested by {payload.get('by', 'system')}")]}


def _compact(obj: Any, limit: int = 1500) -> str:
    import json

    s = json.dumps(obj, default=str, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


def _summarise(name: str, r: dict) -> str:
    if name == "lookup_order":
        if not r.get("found"):
            return f"Order {r['order_id']} NOT FOUND"
        o = r["order"]
        return f"{o['order_id']}: {o['product_name']} ${o['product_price']}, status {o['delivery_status']}"
    if name == "get_delivery_status":
        if not r.get("found"):
            return "Order not found"
        bits = [f"status {r['delivery_status']}"]
        if r.get("delivery_days") is not None:
            bits.append(f"delivered in {r['delivery_days']}d (late={r.get('was_late')})")
        if r.get("days_since_order") is not None and r.get("delivery_days") is None:
            bits.append(f"{r['days_since_order']}d since order (overdue={r.get('is_overdue')})")
        return ", ".join(bits)
    if name == "retrieve_store_policies":
        return f"{r['count']} '{r['issue_category']}' policies: {', '.join(p['policy_id'] for p in r['policies'])}"
    if name == "verify_return_eligibility":
        return f"eligible={r.get('eligible')}: {' '.join(r.get('reasons', []))}"[:300]
    if name == "check_previous_refund":
        return f"previous refund status: {r.get('previous_refund_status')} (duplicate={r.get('duplicate')})"
    if name == "verify_damage_evidence":
        return f"{r['photo_count']} photo(s), verified={r['verified']}"
    return "ok"
