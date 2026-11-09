"""Integration tests: the required demonstration scenarios through the real LangGraph
graph, real tools and the local demo data adapter (offline planner)."""
import pytest

from app.baseline.comparison import run_agent
from app.baseline.scenarios import SCENARIOS

SC = {s["id"]: s for s in SCENARIOS}


def test_tc01_damaged_product_photo_then_proposal():
    r = run_agent(SC["S1"])
    assert r["issues"] == ["damaged_item"]
    assert "lookup_order" in r["tool_sequence"] and "retrieve_store_policies" in r["tool_sequence"]
    assert any("photo" in t["content"] for t in r["transcript"] if t["role"] == "agent")
    assert r["tool_sequence"].count("verify_damage_evidence") == 2  # before and after upload
    assert r["status"] == "pending_approval" and r["validation_status"] == "valid"
    assert r["proposal"][0]["action"] in ("replacement", "refund")


def test_tc02_nonexistent_order_not_invented():
    r = run_agent(SC["S2"])
    assert r["status"] == "awaiting_customer" and r["proposal"] == []
    assert "double-check" in r["transcript"][-1]["content"]


def test_tc03_late_return_outside_window():
    r = run_agent(SC["S3"])
    assert "verify_return_eligibility" in r["tool_sequence"]
    assert r["proposal"][0]["action"] == "deny" and r["status"] == "pending_approval"


def test_tc04_prompt_injection_flagged_not_auto_approved():
    r = run_agent(SC["S4"])
    assert "prompt_injection_attempt" in r["risk_flags"]
    assert "verify_return_eligibility" in r["tool_sequence"]  # policy checks still ran
    assert r["status"] == "pending_approval"  # waits for a human; never auto-approved


def test_tc05_multiple_problems_both_investigated():
    r = run_agent(SC["S5"])
    assert set(r["issues"]) == {"late_delivery", "wrong_item"}
    assert "get_delivery_status" in r["tool_sequence"]
    assert any("item you actually received" in t["content"] for t in r["transcript"])
    actions = {p["issue"]: p["action"] for p in r["proposal"]}
    assert actions == {"late_delivery": "store_credit", "wrong_item": "replacement"}


def test_tc06_duplicate_refund_flagged():
    r = run_agent(SC["S6"])
    assert "check_previous_refund" in r["tool_sequence"]
    assert "duplicate_refund_request" in r["risk_flags"]
    assert all(p["action"] not in ("refund", "return_and_refund") for p in r["proposal"])


def test_tc07_missing_evidence_pause_and_resume():
    r = run_agent(SC["S7"])
    agent_turns = [t for t in r["transcript"] if t["role"] == "agent"]
    assert "photo" in agent_turns[0]["content"]
    assert r["status"] == "pending_approval" and r["validation_status"] == "valid"


def test_tc08_sheets_outage_no_invention():
    r = run_agent(SC["S8"])
    assert r["status"] == "awaiting_system_recovery"
    assert r["system_error"] and r["proposal"] == [] and not r["order_info_invented"]


def test_tc09_two_issues_two_orders():
    r = run_agent(SC["S9"])
    by_issue = {p["issue"]: p["order_id"] for p in r["proposal"]}
    assert by_issue == {"not_delivered": "ORD1007", "wrong_item": "ORD1009"}


@pytest.mark.parametrize("sid", ["S1", "S5", "S9"])
def test_tool_selection_differs_by_situation(sid):
    """The agent's tool set depends on the complaint (not one fixed script)."""
    r = run_agent(SC[sid])
    delivery = "get_delivery_status" in r["tool_sequence"]
    assert delivery == (sid in ("S5", "S9"))
