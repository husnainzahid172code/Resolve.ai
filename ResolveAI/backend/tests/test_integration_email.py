"""Gmail tool: sent only after human approval, exactly once, failures handled."""
import smtplib

import pytest

from app.services import email_service as es


class RecordingSender(es.EmailSender):
    mode = "gmail"

    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, subject, body):
        if self.fail:
            raise es.EmailSendError("SMTPAuthenticationError: bad app password")
        self.sent.append((to, subject, body))


@pytest.fixture()
def sender():
    s = RecordingSender()
    es.set_sender(s)
    yield s
    es.set_sender(None)


def _to_pending(client):
    r = client.post("/api/complaints", json={"message": "Please cancel my order ORD1006"})
    cid = r.json()["case_id"]
    assert r.json()["status"] == "pending_approval"
    return cid


def test_em01_no_email_before_human_decision(client, admin_headers, sender):
    cid = _to_pending(client)
    assert sender.sent == []  # agent finished, but nothing is sent until a human approves
    assert client.get(f"/api/cases/{cid}", headers=admin_headers).json()["emails"] == []


def test_em02_email_sent_once_after_approval(client, admin_headers, sender):
    cid = _to_pending(client)
    client.post(f"/api/cases/{cid}/approve", json={}, headers=admin_headers)
    assert len(sender.sent) == 1
    to, subject, body = sender.sent[0]
    assert to == "omar.farooq@example.com" and cid in subject and "cancelled" in body
    view = client.get(f"/api/cases/{cid}", headers=admin_headers).json()
    assert view["emails"][0]["status"] == "sent"
    # resend is refused once delivered -> no duplicate irreversible action
    assert client.post(f"/api/cases/{cid}/resend-email", headers=admin_headers).status_code == 409
    assert len(sender.sent) == 1


def test_em03_rejection_email_contains_reason(client, admin_headers, sender):
    cid = _to_pending(client)
    client.post(f"/api/cases/{cid}/reject", json={"reason": "the order has already been packed"}, headers=admin_headers)
    assert "already been packed" in sender.sent[0][2]


def test_em04_send_failure_is_flagged_and_retryable(client, admin_headers):
    failing = RecordingSender(fail=True)
    es.set_sender(failing)
    try:
        cid = _to_pending(client)
        r = client.post(f"/api/cases/{cid}/approve", json={}, headers=admin_headers)
        assert r.json()["status"] == "approved"  # decision is still recorded
        view = client.get(f"/api/cases/{cid}", headers=admin_headers).json()
        assert view["emails"][0]["status"] == "failed" and "email_send_failed" in view["risk_flags"]
        failing.fail = False
        r = client.post(f"/api/cases/{cid}/resend-email", headers=admin_headers)
        assert r.json()["email"]["status"] == "sent" and len(failing.sent) == 1
    finally:
        es.set_sender(None)


def test_em05_demo_recipient_override(client, admin_headers, sender, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "email_demo_recipient", "student@gmail.com")
    cid = _to_pending(client)
    client.post(f"/api/cases/{cid}/approve", json={}, headers=admin_headers)
    e = client.get(f"/api/cases/{cid}", headers=admin_headers).json()["emails"][0]
    assert sender.sent[0][0] == "student@gmail.com" and e["intended_address"] == "omar.farooq@example.com"


def test_em06_gmail_sender_uses_smtp_ssl_login(monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, context=None, timeout=None):
            calls["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            calls["login"] = (user, pw)

        def send_message(self, msg):
            calls["to"] = msg["To"]

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    es.GmailSender("me@gmail.com", "abcdabcdabcdabcd").send("x@y.com", "s", "b")
    assert calls == {"host": ("smtp.gmail.com", 465), "login": ("me@gmail.com", "abcdabcdabcdabcd"), "to": "x@y.com"}


def test_em07_demo_outbox_records_without_sending(client, admin_headers):
    es.set_sender(None)  # default in tests: demo outbox
    cid = _to_pending(client)
    client.post(f"/api/cases/{cid}/approve", json={}, headers=admin_headers)
    e = client.get(f"/api/cases/{cid}", headers=admin_headers).json()["emails"][0]
    assert e["mode"] == "demo_outbox" and e["status"] == "recorded"


def test_em08_apps_script_sender_posts_secret_over_https(monkeypatch):
    import httpx

    seen = {}

    class Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ok": true}'

        def json(self):
            return {"ok": True}

    def fake_post(url, json=None, timeout=None, follow_redirects=None):
        seen.update(url=url, json=json, follow=follow_redirects)
        return Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    es.GmailAppsScriptSender("https://script.google.com/macros/s/X/exec", "s3cret").send("a@b.com", "subj", "body")
    assert seen["json"] == {"secret": "s3cret", "to": "a@b.com", "subject": "subj", "body": "body"} and seen["follow"]


def test_em09_apps_script_error_raises(monkeypatch):
    import httpx

    class Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def json(self):
            return {"ok": False, "error": "bad secret"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    with pytest.raises(es.EmailSendError, match="bad secret"):
        es.GmailAppsScriptSender("https://x", "wrong").send("a@b.com", "s", "b")
