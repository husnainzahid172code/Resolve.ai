"""Customer email delivery - the system's one irreversible action.

* GmailSender      -- real delivery through Gmail SMTP (smtp.gmail.com:465) using
                      a Gmail App Password from the environment.
* DemoOutboxSender -- clearly labelled demo mode: the email is recorded in the
                      `emails` table and shown in the admin UI, but NOT sent.

The graph only reaches the send step after a human administrator has approved
or rejected the case (human_approval interrupt). Sending is idempotent per case:
if a final email was already sent/recorded, it is never sent again.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from app.core.config import get_settings
from app.database.db import now_iso, tx


class EmailSendError(Exception):
    pass


class EmailSender:
    mode = "abstract"

    def send(self, to: str, subject: str, body: str) -> None:  # pragma: no cover
        raise NotImplementedError


class GmailSender(EmailSender):
    mode = "gmail"

    def __init__(self, address: str, app_password: str, timeout: float = 15) -> None:
        self.address, self.app_password, self.timeout = address, app_password, timeout

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = f"ResolveAI Support <{self.address}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(),
                                  timeout=self.timeout) as smtp:
                smtp.login(self.address, self.app_password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailSendError(f"{type(exc).__name__}: {exc}") from exc


class DemoOutboxSender(EmailSender):
    mode = "demo_outbox"

    def send(self, to: str, subject: str, body: str) -> None:
        return None  # recorded by send_case_email; nothing leaves the machine


_sender: EmailSender | None = None


def get_sender() -> EmailSender:
    global _sender
    if _sender is None:
        s = get_settings()
        if s.resolved_email_mode == "gmail":
            _sender = GmailSender(s.gmail_address, s.gmail_app_password, s.email_timeout_seconds)
        else:
            _sender = DemoOutboxSender()
    return _sender


def set_sender(sender: EmailSender | None) -> None:
    global _sender
    _sender = sender


def _row(r) -> dict[str, Any]:
    return dict(r) if r else None


def get_case_emails(case_id: str) -> list[dict[str, Any]]:
    with tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM emails WHERE case_id=? ORDER BY id", (case_id,))]


def delivered_email(case_id: str, kind: str = "final_resolution") -> dict | None:
    with tx() as c:
        return _row(c.execute(
            "SELECT * FROM emails WHERE case_id=? AND kind=? AND status IN ('sent','recorded') ORDER BY id LIMIT 1",
            (case_id, kind)).fetchone())


def send_case_email(case_id: str, intended_to: str, subject: str, body: str,
                    kind: str = "final_resolution") -> dict[str, Any]:
    """Send (or record) the customer email exactly once per case."""
    existing = delivered_email(case_id, kind)
    if existing:
        return {**existing, "duplicate_prevented": True}
    s = get_settings()
    sender = get_sender()
    to = s.email_demo_recipient or intended_to
    status, error = ("sent" if sender.mode == "gmail" else "recorded"), ""
    try:
        sender.send(to, subject, body)
    except EmailSendError as exc:
        status, error = "failed", str(exc)[:500]
    with tx() as c:
        cur = c.execute(
            "INSERT INTO emails(case_id, kind, mode, to_address, intended_address, subject, body, status, error, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (case_id, kind, sender.mode, to, intended_to, subject, body, status, error, now_iso()))
        eid = cur.lastrowid
    return {"id": eid, "case_id": case_id, "mode": sender.mode, "to_address": to, "intended_address": intended_to,
            "subject": subject, "status": status, "error": error}
