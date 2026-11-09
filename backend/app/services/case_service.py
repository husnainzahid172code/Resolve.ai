"""Case orchestration: runs/resumes the LangGraph thread for each case and
maintains the dashboard projection, transcript and audit trail.

One LangGraph thread per case (thread_id == case_id). The checkpointer makes
cases survive restarts: a customer can come back with their case ID and the
graph resumes exactly where it paused.
"""
from __future__ import annotations

import secrets
import threading
from typing import Any

from langgraph.types import Command

from app.graph.builder import build_graph
from app.services import case_repository as repo
from app.services.data_source import DataSourceUnavailable
from app.tools.agent_tools import CUSTOMER_SAFE_LABELS


class CaseError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


AWAITING_REPLY = {
    "admin_review": ("I've finished investigating and prepared a proposed resolution. A member of our team "
                     "now needs to review and approve it - you'll see the outcome here. Your case ID is {case_id}."),
    "system_recovery": ("I'm having trouble reaching our order records right now, so I can't complete the "
                        "investigation yet. Your case {case_id} is saved; I'll retry as soon as the system is "
                        "available (you can also send a message here to retry)."),
}


class CaseService:
    def __init__(self, graph=None, planner=None) -> None:
        if graph is None:
            graph, planner = build_graph()
        self.graph = graph
        self.planner = planner
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def _lock(self, case_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(case_id, threading.Lock())

    @staticmethod
    def _cfg(case_id: str) -> dict:
        return {"configurable": {"thread_id": case_id}, "recursion_limit": 80}

    def pending_interrupt(self, case_id: str) -> dict | None:
        st = self.graph.get_state(self._cfg(case_id))
        for task in st.tasks or []:
            if task.interrupts:
                return task.interrupts[0].value
        return None

    def state(self, case_id: str) -> dict:
        return dict(self.graph.get_state(self._cfg(case_id)).values or {})

    def _run(self, case_id: str, payload: Any) -> None:
        before = len(self.state(case_id).get("investigation_history") or []) if not isinstance(payload, dict) else 0
        try:
            self.graph.invoke(payload, self._cfg(case_id))
        except DataSourceUnavailable as exc:  # defensive: tools catch this themselves
            repo.audit(case_id, "system", "data_source_error", {"error": str(exc)})
        self._sync(case_id, before)

    def _sync(self, case_id: str, history_offset: int = 0) -> None:
        values = self.state(case_id)
        intr = self.pending_interrupt(case_id)
        status = values.get("status", "investigating")
        reply = None
        if intr:
            kind = intr["type"]
            if kind == "customer_input":
                status = "info_requested" if intr.get("requested_by") == "admin_request" else "awaiting_customer"
                reply = intr["question"]
            elif kind == "admin_review":
                status = "pending_approval"
                reply = AWAITING_REPLY["admin_review"].format(case_id=case_id)
            elif kind == "system_recovery":
                status = "awaiting_system_recovery"
                reply = AWAITING_REPLY["system_recovery"].format(case_id=case_id)
                repo.audit(case_id, "system", "awaiting_system_recovery", {"error": intr.get("error")})
        elif values.get("final_response"):
            status = values.get("status")
            reply = values["final_response"]

        history = (values.get("investigation_history") or [])[history_offset:]
        progress = []
        for h in history:
            if h.get("step") == "tool" and h.get("ok") and h.get("tool") in CUSTOMER_SAFE_LABELS:
                label = CUSTOMER_SAFE_LABELS[h["tool"]]
                if label not in progress:
                    progress.append(label)
        if reply:
            repo.add_message(case_id, "agent", reply, {"status": status, "progress": progress})

        prop = values.get("proposed_resolution") or {}
        repo.update_projection(
            case_id,
            status=status,
            order_ids=values.get("order_ids") or [],
            issues=[i["type"] for i in values.get("identified_issues") or []],
            proposed_actions=[i["action"] for i in prop.get("items", [])],
            validation_status=(values.get("validation_result") or {}).get("status", ""),
            risk_flags=values.get("risk_flags") or [],
            approval_status=values.get("approval_status", "not_requested"),
        )

    # ------------------------------------------------------------------ customer API
    def start_case(self, message: str) -> str:
        case_id = "RAI-" + secrets.token_hex(5).upper()
        repo.create_case(case_id, message)
        repo.add_message(case_id, "customer", message)
        repo.audit(case_id, "customer", "case_created", {})
        with self._lock(case_id):
            self._run(case_id, {
                "case_id": case_id,
                "customer_message": message,
                "conversation_history": [{"role": "customer", "content": message}],
                "status": "received",
                "approval_status": "not_requested",
                "revision_count": 0,
                "step_count": 0,
                "evidence_count": 0,
            })
        return case_id

    def _ensure(self, case_id: str) -> None:
        if not repo.case_exists(case_id):
            raise CaseError(404, "Case not found")

    def customer_message(self, case_id: str, message: str) -> dict:
        self._ensure(case_id)
        with self._lock(case_id):
            repo.add_message(case_id, "customer", message)
            intr = self.pending_interrupt(case_id)
            if intr and intr["type"] == "customer_input":
                self._run(case_id, Command(resume={"message": message}))
                return {"resumed": True}
            if intr and intr["type"] == "system_recovery":
                repo.audit(case_id, "customer", "retry_requested", {})
                self._run(case_id, Command(resume={"by": "customer"}))
                return {"resumed": True}
            note = ("Thanks - your message has been added to your case. It is currently with our team for review."
                    if intr and intr["type"] == "admin_review"
                    else "Thanks - your message has been added to your case. This case is already closed; "
                         "please start a new conversation for a new issue.")
            repo.add_message(case_id, "agent", note, {"status": repo.get_case_row(case_id)["status"]})
            return {"resumed": False}

    def add_evidence(self, case_id: str, stored: dict) -> dict:
        self._ensure(case_id)
        with self._lock(case_id):
            msg = f"[Uploaded photo: {stored['filename']}]"
            repo.add_message(case_id, "customer", msg, {"evidence_id": stored["evidence_id"]})
            repo.audit(case_id, "customer", "evidence_uploaded", stored)
            intr = self.pending_interrupt(case_id)
            if intr and intr["type"] == "customer_input":
                count = len(repo.list_evidence(case_id))
                self._run(case_id, Command(resume={"message": msg, "evidence_uploaded": True, "evidence_count": count}))
                return {"resumed": True}
            return {"resumed": False}

    # ------------------------------------------------------------------ admin API
    def admin_decision(self, case_id: str, decision: str, admin: str, body: dict, idem_key: str | None) -> dict:
        self._ensure(case_id)
        key = f"{case_id}:{idem_key}" if idem_key else None
        if key and (cached := repo.get_idempotent(key)):
            return {**cached, "idempotent_replay": True}
        with self._lock(case_id):
            if key and (cached := repo.get_idempotent(key)):
                return {**cached, "idempotent_replay": True}
            intr = self.pending_interrupt(case_id)
            if not intr or intr["type"] != "admin_review":
                raise CaseError(409, f"Case is not awaiting approval (status: {repo.get_case_row(case_id)['status']}).")
            from app.database.db import now_iso

            payload = {"decision": decision, "admin": admin, "at": now_iso(), **body}
            repo.audit(case_id, admin, f"admin_{decision}", body)
            if body.get("note"):
                repo.add_message(case_id, "admin", body["note"], {"internal": True})
            self._run(case_id, Command(resume=payload))
            row = repo.get_case_row(case_id)
            result = {"case_id": case_id, "decision": decision, "status": row["status"]}
            if key:
                repo.save_idempotent(key, case_id, decision, result)
            return result

    def retry(self, case_id: str, admin: str) -> dict:
        self._ensure(case_id)
        with self._lock(case_id):
            intr = self.pending_interrupt(case_id)
            if not intr or intr["type"] != "system_recovery":
                raise CaseError(409, "Case is not awaiting system recovery.")
            repo.audit(case_id, admin, "retry_requested", {})
            self._run(case_id, Command(resume={"by": admin}))
            return {"case_id": case_id, "status": repo.get_case_row(case_id)["status"]}


_service: CaseService | None = None


def get_case_service() -> CaseService:
    global _service
    if _service is None:
        _service = CaseService()
    return _service


def set_case_service(svc: CaseService | None) -> None:
    global _service
    _service = svc
