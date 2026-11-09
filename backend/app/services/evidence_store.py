"""Damage-photo upload handling with type and size validation.

Type is checked from the file's magic bytes, not the client-supplied
Content-Type or filename, so a renamed executable is rejected.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.services import case_repository as repo

MIN_BYTES = 100

_SIGNATURES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],  # plus 'WEBP' at offset 8
}


class EvidenceRejected(ValueError):
    pass


def sniff_image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def store_evidence(case_id: str, filename: str, data: bytes) -> dict:
    s = get_settings()
    if len(data) > s.max_upload_bytes:
        raise EvidenceRejected(f"File too large ({len(data)} bytes); limit is {s.max_upload_bytes} bytes.")
    if len(data) < MIN_BYTES:
        raise EvidenceRejected("File is too small to be a usable photo.")
    ctype = sniff_image_type(data)
    if ctype is None:
        raise EvidenceRejected("Only JPEG, PNG or WEBP images are accepted.")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[ctype]
    safe_name = Path(filename or "photo").name[:100]
    stored = s.evidence_dir / f"{case_id}_{uuid.uuid4().hex[:10]}{ext}"
    stored.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    eid = repo.add_evidence(case_id, safe_name, str(stored), ctype, len(data), sha)
    return {"evidence_id": eid, "filename": safe_name, "content_type": ctype, "size_bytes": len(data), "sha256": sha}


def verify_case_evidence(case_id: str) -> dict:
    """Deterministic file-level verification. Visual judgment stays with the admin."""
    s = get_settings()
    items = repo.list_evidence(case_id)
    checked = []
    for e in items:
        p = Path(e["stored_path"])
        ok = p.exists()
        reason = "ok"
        if ok:
            data = p.read_bytes()
            if sniff_image_type(data) is None:
                ok, reason = False, "not a valid image"
            elif len(data) > s.max_upload_bytes:
                ok, reason = False, "too large"
            elif hashlib.sha256(data).hexdigest() != e["sha256"]:
                ok, reason = False, "file changed after upload"
        else:
            reason = "file missing"
        checked.append({"evidence_id": e["id"], "filename": e["filename"], "valid": ok, "reason": reason})
    verified = any(c["valid"] for c in checked)
    return {
        "case_id": case_id,
        "photo_count": len(items),
        "files": checked,
        "verified": verified,
        "note": (
            "Photo passed file-integrity checks. Visual confirmation of damage is part of administrator review."
            if verified
            else "No valid photo evidence has been submitted for this case."
        ),
    }
