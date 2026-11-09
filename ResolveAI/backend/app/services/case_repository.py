"""Queries and writes for the case projection, transcript, audit trail and idempotency."""
from __future__ import annotations

from typing import Any

from app.database.db import dumps, loads, now_iso, tx


def create_case(case_id: str, first_message: str) -> None:
    ts = now_iso()
    with tx() as c:
        c.execute(
            "INSERT INTO cases(case_id, created_at, updated_at, status, first_message) VALUES (?,?,?,?,?)",
            (case_id, ts, ts, "received", first_message[:4000]),
        )


def case_exists(case_id: str) -> bool:
    with tx() as c:
        return c.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone() is not None


def update_projection(case_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(dumps(v) if isinstance(v, (list, dict)) else v)
    cols.append("updated_at=?")
    vals.append(now_iso())
    with tx() as c:
        c.execute(f"UPDATE cases SET {', '.join(cols)} WHERE case_id=?", (*vals, case_id))


def _row_to_case(r) -> dict[str, Any]:
    d = dict(r)
    for k in ("order_ids", "issues", "proposed_actions", "risk_flags"):
        d[k] = loads(d.get(k), [])
    return d


def get_case_row(case_id: str) -> dict[str, Any] | None:
    with tx() as c:
        r = c.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    return _row_to_case(r) if r else None


def list_cases(status: str | None = None, issue: str | None = None) -> list[dict[str, Any]]:
    q, args = "SELECT * FROM cases", []
    if status:
        q += " WHERE status=?"
        args.append(status)
    q += " ORDER BY updated_at DESC"
    with tx() as c:
        rows = [_row_to_case(r) for r in c.execute(q, args).fetchall()]
    if issue:
        rows = [r for r in rows if issue in r["issues"]]
    return rows


def add_message(case_id: str, role: str, content: str, meta: dict | None = None) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO case_messages(case_id, role, content, created_at, meta) VALUES (?,?,?,?,?)",
            (case_id, role, content, now_iso(), dumps(meta or {})),
        )


def get_messages(case_id: str) -> list[dict[str, Any]]:
    with tx() as c:
        rows = c.execute(
            "SELECT role, content, created_at, meta FROM case_messages WHERE case_id=? ORDER BY id", (case_id,)
        ).fetchall()
    return [{**dict(r), "meta": loads(r["meta"], {})} for r in rows]


def audit(case_id: str | None, actor: str, action: str, detail: dict | None = None) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO audit_log(case_id, actor, action, detail, created_at) VALUES (?,?,?,?,?)",
            (case_id, actor, action, dumps(detail or {}), now_iso()),
        )


def get_audit(case_id: str) -> list[dict[str, Any]]:
    with tx() as c:
        rows = c.execute(
            "SELECT actor, action, detail, created_at FROM audit_log WHERE case_id=? ORDER BY id", (case_id,)
        ).fetchall()
    return [{**dict(r), "detail": loads(r["detail"], {})} for r in rows]


def get_idempotent(key: str) -> dict | None:
    with tx() as c:
        r = c.execute("SELECT response FROM idempotency WHERE key=?", (key,)).fetchone()
    return loads(r["response"]) if r else None


def save_idempotent(key: str, case_id: str, action: str, response: dict) -> None:
    with tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO idempotency(key, case_id, action, response, created_at) VALUES (?,?,?,?,?)",
            (key, case_id, action, dumps(response), now_iso()),
        )


def add_evidence(case_id: str, filename: str, path: str, ctype: str, size: int, sha: str) -> int:
    with tx() as c:
        cur = c.execute(
            "INSERT INTO evidence(case_id, filename, stored_path, content_type, size_bytes, sha256, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (case_id, filename, path, ctype, size, sha, now_iso()),
        )
        return int(cur.lastrowid)


def list_evidence(case_id: str) -> list[dict[str, Any]]:
    with tx() as c:
        rows = c.execute("SELECT * FROM evidence WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def get_evidence(evidence_id: int) -> dict | None:
    with tx() as c:
        r = c.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
    return dict(r) if r else None


def save_comparison(planner: str, results: list[dict]) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO comparison_runs(created_at, planner, results) VALUES (?,?,?)", (now_iso(), planner, dumps(results))
        )


def latest_comparison() -> dict | None:
    with tx() as c:
        r = c.execute("SELECT * FROM comparison_runs ORDER BY id DESC LIMIT 1").fetchone()
    return {"created_at": r["created_at"], "planner": r["planner"], "results": loads(r["results"], [])} if r else None


def stats() -> dict[str, Any]:
    rows = list_cases()
    by_status: dict[str, int] = {}
    by_issue: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        for i in r["issues"]:
            by_issue[i] = by_issue.get(i, 0) + 1
        for a in r["proposed_actions"]:
            by_action[a] = by_action.get(a, 0) + 1
    return {
        "total_cases": len(rows),
        "pending_approval": by_status.get("pending_approval", 0),
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
        "awaiting_customer": by_status.get("awaiting_customer", 0),
        "awaiting_system_recovery": by_status.get("awaiting_system_recovery", 0),
        "by_status": by_status,
        "by_issue": by_issue,
        "by_proposed_action": by_action,
    }
