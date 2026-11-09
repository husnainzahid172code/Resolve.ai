"""HTTP API: customer, admin and comparison endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.security import check_credentials, create_token, optional_admin, require_admin
from app.schemas import api as S
from app.services import case_repository as repo
from app.services.case_service import CaseError, get_case_service
from app.services.data_source import get_data_source
from app.services import email_service
from app.services.evidence_store import EvidenceRejected, store_evidence

router = APIRouter(prefix="/api")


def _svc():
    return get_case_service()


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except CaseError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


# ---------------------------------------------------------------- meta / auth
@router.get("/health")
def health() -> dict:
    return {"ok": True, **get_settings().public_runtime_info()}


@router.post("/auth/login")
def login(body: S.LoginRequest) -> dict:
    if not check_credentials(body.username, body.password):
        repo.audit(None, body.username[:50], "admin_login_failed", {})
        raise HTTPException(401, "Invalid username or password")
    repo.audit(None, body.username, "admin_login", {})
    return {"token": create_token(body.username), "username": body.username}


# ---------------------------------------------------------------- customer views
def customer_view(case_id: str) -> dict[str, Any]:
    row = repo.get_case_row(case_id)
    if not row:
        raise HTTPException(404, "Case not found")
    svc = _svc()
    intr = svc.pending_interrupt(case_id)
    values = svc.state(case_id)
    msgs = [
        {"role": m["role"], "content": m["content"], "created_at": m["created_at"],
         "progress": m["meta"].get("progress", []), "status": m["meta"].get("status")}
        for m in repo.get_messages(case_id)
        if not m["meta"].get("internal") and m["role"] in ("customer", "agent")
    ]
    return {
        "case_id": case_id,
        "status": row["status"],
        "messages": msgs,
        "awaiting": (intr or {}).get("type"),
        "final_response": values.get("final_response"),
        "evidence_count": len(repo.list_evidence(case_id)),
        "runtime": get_settings().public_runtime_info(),
    }


def admin_view(case_id: str) -> dict[str, Any]:
    row = repo.get_case_row(case_id)
    if not row:
        raise HTTPException(404, "Case not found")
    svc = _svc()
    v = svc.state(case_id)
    intr = svc.pending_interrupt(case_id)
    return {
        **row,
        "awaiting": (intr or {}).get("type"),
        "messages": repo.get_messages(case_id),
        "identified_issues": v.get("identified_issues") or [],
        "customer_claims": v.get("customer_claims") or {},
        "order_information": v.get("order_information") or {},
        "delivery_information": v.get("delivery_information") or {},
        "retrieved_policies": v.get("retrieved_policies") or {},
        "return_eligibility": v.get("return_eligibility") or {},
        "refund_checks": v.get("refund_checks") or {},
        "evidence_verification": v.get("evidence_verification"),
        "evidence": [{k: e[k] for k in ("id", "filename", "content_type", "size_bytes", "created_at")}
                     for e in repo.list_evidence(case_id)],
        "proposed_resolution": v.get("proposed_resolution"),
        "policy_assessments": v.get("policy_assessments") or [],
        "validation_result": v.get("validation_result"),
        "risk_flags": v.get("risk_flags") or [],
        "investigation_history": [{k: h.get(k) for k in ("at", "step", "tool", "args", "ok", "summary", "planner", "tool_calls")}
                                  for h in v.get("investigation_history") or []],
        "draft_customer_response": v.get("draft_customer_response"),
        "administrator_decision": v.get("administrator_decision"),
        "final_response": v.get("final_response"),
        "log_saved": v.get("log_saved"),
        "emails": email_service.get_case_emails(case_id),
        "system_error": v.get("system_error") or (intr or {}).get("error"),
        "audit": repo.get_audit(case_id),
        "runtime": get_settings().public_runtime_info(),
    }


@router.post("/complaints", status_code=201)
def create_complaint(body: S.ComplaintCreate) -> dict:
    case_id = _svc().start_case(body.message.strip())
    return customer_view(case_id)


@router.post("/cases/{case_id}/messages")
def post_message(case_id: str, body: S.MessageCreate) -> dict:
    _wrap(_svc().customer_message, case_id, body.message.strip())
    return customer_view(case_id)


@router.post("/cases/{case_id}/evidence")
async def upload_evidence(case_id: str, file: UploadFile = File(...)) -> dict:
    if not repo.case_exists(case_id):
        raise HTTPException(404, "Case not found")
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    try:
        stored = store_evidence(case_id, file.filename or "photo", data)
    except EvidenceRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    _wrap(_svc().add_evidence, case_id, stored)
    return customer_view(case_id)


@router.get("/cases/pending")
def pending_cases(_: dict = Depends(require_admin)) -> list[dict]:
    return repo.list_cases("pending_approval")


@router.get("/cases/{case_id}")
def get_case(case_id: str, admin: dict | None = Depends(optional_admin)) -> dict:
    """Customers get a sanitised view; an authenticated admin gets the full investigation record."""
    return admin_view(case_id) if admin else customer_view(case_id)


# ---------------------------------------------------------------- admin
@router.get("/cases")
def list_cases(status: str | None = Query(None), issue: str | None = Query(None),
               _: dict = Depends(require_admin)) -> list[dict]:
    return repo.list_cases(status, issue)


@router.post("/cases/{case_id}/approve")
def approve(case_id: str, body: S.ApproveRequest, admin: dict = Depends(require_admin),
            idempotency_key: str | None = Header(None)) -> dict:
    res = _wrap(_svc().admin_decision, case_id, "approve", admin["sub"], body.model_dump(exclude_none=True), idempotency_key)
    return {**res, "case": admin_view(case_id)}


@router.post("/cases/{case_id}/reject")
def reject(case_id: str, body: S.RejectRequest, admin: dict = Depends(require_admin),
           idempotency_key: str | None = Header(None)) -> dict:
    res = _wrap(_svc().admin_decision, case_id, "reject", admin["sub"], body.model_dump(exclude_none=True), idempotency_key)
    return {**res, "case": admin_view(case_id)}


@router.post("/cases/{case_id}/request-information")
def request_info(case_id: str, body: S.RequestInfoRequest, admin: dict = Depends(require_admin),
                 idempotency_key: str | None = Header(None)) -> dict:
    res = _wrap(_svc().admin_decision, case_id, "request_information", admin["sub"],
                body.model_dump(exclude_none=True), idempotency_key)
    return {**res, "case": admin_view(case_id)}


@router.post("/cases/{case_id}/retry")
def retry(case_id: str, admin: dict = Depends(require_admin)) -> dict:
    res = _wrap(_svc().retry, case_id, admin["sub"])
    return {**res, "case": admin_view(case_id)}


@router.post("/cases/{case_id}/resend-email")
def resend_email(case_id: str, admin: dict = Depends(require_admin)) -> dict:
    """Retry a FAILED customer email. Never sends a second copy of a delivered email."""
    svc = _svc()
    v = svc.state(case_id)
    if not v.get("final_response") or v.get("approval_status") not in ("approved", "rejected"):
        raise HTTPException(409, "Case has no approved/rejected final response yet")
    if email_service.delivered_email(case_id):
        raise HTTPException(409, "Email already delivered for this case")
    prev = (v.get("email_delivery") or {})
    last = next((e for e in reversed(email_service.get_case_emails(case_id))), None)
    if not last:
        raise HTTPException(409, "No email was attempted for this case")
    res = email_service.send_case_email(case_id, last["intended_address"], last["subject"], last["body"])
    repo.audit(case_id, admin["sub"], "email_resend", {"status": res["status"], "previous": prev.get("status")})
    return {"email": res, "case": admin_view(case_id)}


@router.get("/cases/{case_id}/evidence/{evidence_id}")
def get_evidence_file(case_id: str, evidence_id: int, _: dict = Depends(require_admin)):
    e = repo.get_evidence(evidence_id)
    if not e or e["case_id"] != case_id or not Path(e["stored_path"]).exists():
        raise HTTPException(404, "Evidence not found")
    return FileResponse(e["stored_path"], media_type=e["content_type"])


@router.get("/dashboard/stats")
def dashboard_stats(_: dict = Depends(require_admin)) -> dict:
    return {**repo.stats(), "runtime": get_settings().public_runtime_info()}


@router.get("/resolution-logs")
def resolution_logs(_: dict = Depends(require_admin)) -> dict:
    ds = get_data_source()
    try:
        rows = ds.list_resolution_logs()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Resolution log source unavailable: {exc}") from exc
    return {"source": ds.label, "rows": rows}


# ---------------------------------------------------------------- demo controls (clearly labelled)
@router.get("/admin/demo/outage")
def outage_status(_: dict = Depends(require_admin)) -> dict:
    return {"simulate_outage": bool(getattr(get_data_source(), "simulate_outage", False))}


@router.post("/admin/demo/outage")
def toggle_outage(enabled: bool = Query(...), admin: dict = Depends(require_admin)) -> dict:
    ds = get_data_source()
    ds.simulate_outage = enabled
    repo.audit(None, admin["sub"], "demo_outage_toggle", {"enabled": enabled, "source": ds.label})
    return {"simulate_outage": enabled, "note": "DEMO CONTROL: simulates the business data source being unreachable."}


# ---------------------------------------------------------------- comparison
@router.post("/comparison/run")
def comparison_run(_: dict = Depends(require_admin)) -> dict:
    from app.baseline.comparison import run_comparison

    svc = _svc()
    results = run_comparison(svc.planner)
    repo.save_comparison(svc.planner.name, results)
    return repo.latest_comparison()


@router.get("/comparison/results")
def comparison_results(_: dict = Depends(require_admin)) -> dict:
    return repo.latest_comparison() or {"created_at": None, "planner": None, "results": []}
