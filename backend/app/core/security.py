"""Minimal signed-token admin authentication (HMAC-SHA256, expiring).

Deliberately dependency-free. Tokens carry the username, role and expiry and
are verified on every admin request. The LLM never sees or produces tokens,
so it cannot grant itself admin permissions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(username: str, role: str = "admin") -> str:
    s = get_settings()
    payload = {"sub": username, "role": role, "exp": int(time.time()) + s.token_ttl_minutes * 60}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(s.auth_secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> dict:
    s = get_settings()
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("malformed token") from exc
    expected = _b64(hmac.new(s.auth_secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ValueError("bad signature")
    payload = json.loads(_unb64(body))
    if payload.get("exp", 0) < time.time():
        raise ValueError("token expired")
    return payload


def check_credentials(username: str, password: str) -> bool:
    s = get_settings()
    return secrets.compare_digest(username, s.admin_username) and secrets.compare_digest(
        password, s.admin_password
    )


def optional_admin(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict | None:
    if not creds:
        return None
    try:
        payload = verify_token(creds.credentials)
    except ValueError:
        return None
    return payload if payload.get("role") == "admin" else None


def require_admin(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin authentication required")
    try:
        payload = verify_token(creds.credentials)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    if payload.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return payload
