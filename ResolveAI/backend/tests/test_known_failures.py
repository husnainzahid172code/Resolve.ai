"""Two cases ResolveAI currently gets WRONG (known limitations, kept visible on purpose).

They are marked xfail(strict=True): each test asserts the behaviour we WANT. They are
reported as "xfailed" while the limitation exists, and turn into an error (XPASS) the day
someone fixes it, so the failure report cannot silently go stale.
"""
import pytest


def _admin(client, admin_headers, cid):
    return client.get(f"/api/cases/{cid}", headers=admin_headers).json()


@pytest.mark.xfail(strict=True, reason="KF1: photo check is file-level only; image content is not analysed")
def test_kf1_unrelated_photo_should_not_count_as_damage_evidence(client, admin_headers, png_bytes):
    # A plain generated gradient image (not a photo of any product) is uploaded as 'damage evidence'.
    cid = client.post("/api/complaints", json={"message": "My desk lamp arrived broken. Order ORD1008."}).json()["case_id"]
    client.post(f"/api/cases/{cid}/evidence", files={"file": ("not_a_lamp.png", png_bytes, "image/png")})
    case = _admin(client, admin_headers, cid)
    # WANTED: the system recognises the image does not show a damaged lamp and asks again / flags it.
    assert case["evidence_verification"]["verified"] is False


@pytest.mark.xfail(strict=True, reason="KF2: no customer identity check; anyone with an order ID can act on it")
def test_kf2_stranger_should_not_act_on_someone_elses_order(client, admin_headers):
    # ORD1006 belongs to Omar Farooq. The person chatting never proves who they are.
    cid = client.post("/api/complaints", json={"message": "Please cancel my order ORD1006"}).json()["case_id"]
    case = _admin(client, admin_headers, cid)
    # WANTED: identity verification (e.g. email code) before investigating or proposing anything.
    assert case["status"] != "pending_approval"
    assert "identity_not_verified" in case["risk_flags"]
