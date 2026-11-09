"""Runs every scenario through ResolveAI (real graph, real tools) and the baseline."""
from __future__ import annotations

import struct
import uuid
import zlib
from typing import Any

from langgraph.types import Command

from app.baseline.scenarios import SCENARIOS
from app.baseline.traditional_workflow import run_traditional
from app.graph.builder import build_memory_graph
from app.services import evidence_store
from app.services.data_source import get_data_source


def sample_png(width: int = 64, height: int = 48) -> bytes:
    """Generate a small valid PNG used as demo 'damage photo' evidence."""
    rows = b"".join(b"\x00" + b"".join(bytes([(x * 3) % 256, (y * 5) % 256, 90]) for x in range(width)) for y in range(height))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _interrupt(graph, cfg) -> dict | None:
    st = graph.get_state(cfg)
    for t in st.tasks or []:
        if t.interrupts:
            return t.interrupts[0].value
    return None


def _resume_after_llm_pause(graph, cfg, scenario) -> None:
    """Free-tier LLMs rate-limit bursts. If a non-outage scenario paused for recovery, wait and retry."""
    import time

    from app.core.config import get_settings

    if scenario.get("outage"):
        return
    for _ in range(2):
        intr = _interrupt(graph, cfg)
        if not intr or intr["type"] != "system_recovery":
            return
        time.sleep(get_settings().llm_overload_wait_seconds * 1.5)
        graph.invoke(Command(resume={"by": "comparison-runner"}), cfg)


def run_agent(scenario: dict, graph=None) -> dict[str, Any]:
    graph = graph or build_memory_graph()[0]
    case_id = f"CMP-{scenario['id']}-{uuid.uuid4().hex[:6]}"
    cfg = {"configurable": {"thread_id": case_id}, "recursion_limit": 80}
    ds = get_data_source()
    transcript: list[dict[str, str]] = []
    turns = list(scenario["turns"])
    first = turns.pop(0)["message"]
    transcript.append({"role": "customer", "content": first})
    ds.simulate_outage = bool(scenario.get("outage"))
    try:
        graph.invoke({"case_id": case_id, "customer_message": first, "evidence_count": 0, "revision_count": 0,
                      "step_count": 0, "approval_status": "not_requested",
                      "conversation_history": [{"role": "customer", "content": first}]}, cfg)
        while True:
            _resume_after_llm_pause(graph, cfg, scenario)
            intr = _interrupt(graph, cfg)
            if not intr or intr["type"] != "customer_input" or not turns:
                break
            transcript.append({"role": "agent", "content": intr["question"]})
            turn = turns.pop(0)
            if turn.get("photo"):
                stored = evidence_store.store_evidence(case_id, "damage.png", sample_png())
                transcript.append({"role": "customer", "content": "[photo uploaded]"})
                graph.invoke(Command(resume={"message": f"[Uploaded photo: {stored['filename']}]",
                                             "evidence_uploaded": True, "evidence_count": 1}), cfg)
            else:
                transcript.append({"role": "customer", "content": turn["message"]})
                graph.invoke(Command(resume={"message": turn["message"]}), cfg)
        _resume_after_llm_pause(graph, cfg, scenario)
    finally:
        ds.simulate_outage = False

    v = graph.get_state(cfg).values
    intr = _interrupt(graph, cfg)
    if intr and intr["type"] == "customer_input":
        transcript.append({"role": "agent", "content": intr["question"]})
    status = {"customer_input": "awaiting_customer", "admin_review": "pending_approval",
              "system_recovery": "awaiting_system_recovery"}.get((intr or {}).get("type"), v.get("status"))
    tools = [h["tool"] for h in v.get("investigation_history", []) if h.get("step") == "tool"]
    prop = v.get("proposed_resolution") or {}
    return {
        "case_id": case_id,
        "status": status,
        "issues": [i["type"] for i in v.get("identified_issues") or []],
        "tool_sequence": tools,
        "proposal": [{"issue": i["issue"], "order_id": i["order_id"], "action": i["action"], "amount": i["amount"]}
                     for i in prop.get("items", [])],
        "validation_status": (v.get("validation_result") or {}).get("status"),
        "risk_flags": v.get("risk_flags") or [],
        "system_error": v.get("system_error") or (intr or {}).get("error"),
        "transcript": transcript,
        "order_info_invented": any(r.get("found") for r in (v.get("order_information") or {}).values()) and bool(scenario.get("outage")),
    }


def run_baseline(scenario: dict) -> dict[str, Any]:
    ds = get_data_source()
    ds.simulate_outage = bool(scenario.get("outage"))
    try:
        return run_traditional(scenario["turns"], ds)
    finally:
        ds.simulate_outage = False


def _baseline_status(b: dict) -> str:
    return b["outcome"]["status"]


def compare_one(scenario: dict, graph=None) -> dict[str, Any]:
    agent = run_agent(scenario, graph)
    base = run_baseline(scenario)
    exp = set(scenario["expected_issues"])
    agent_cov = len(exp & set(agent["issues"]))
    base_handled = {base["category"]} if base["category"] else set()
    base_norm = {"delivery": {"late_delivery", "not_delivered"}}
    base_cov = len(exp & set().union(*[base_norm.get(c, {c}) for c in base_handled])) if base_handled else 0
    agent_actions = ", ".join(f"{p['issue']}->{p['action']}" for p in agent["proposal"]) or agent["status"]
    agent_action_set = {p["action"] for p in agent["proposal"]} or {agent["status"]}
    base_action = base["outcome"].get("action") or base["outcome"]["status"]
    differences = []
    if agent_cov != base_cov:
        differences.append(f"issue coverage agent {agent_cov}/{len(exp)} vs baseline {base_cov}/{len(exp)}")
    if agent_action_set != {base_action}:
        differences.append(f"outcome differs ({agent_actions} vs {base_action})")
    if base_action == "error" and agent["status"] == "awaiting_system_recovery":
        differences.append("agent saved the case for automatic retry; baseline ended the conversation with an error")
    if base_action == "order_not_found" and agent["status"] == "awaiting_customer":
        differences.append("both refuse to invent data; agent keeps the same case open for the corrected ID")
    if "prompt_injection_attempt" in agent["risk_flags"]:
        differences.append("agent recorded a prompt-injection risk flag")
    if "duplicate_refund_request" in agent["risk_flags"] and base_action == "refund":
        differences.append("baseline's damage branch never checks refund history and queued a second refund")
    return {
        "scenario_id": scenario["id"],
        "scenario": scenario["name"],
        "focus": scenario["focus"],
        "expected_issues": sorted(exp),
        "traditional": {
            "category": base["category"], "steps": base["steps"], "outcome": base["outcome"],
            "behavior": f"Classified as '{base['category']}', steps: {', '.join(base['steps']) or 'none'}; result: {base_action}.",
            "transcript": base["transcript"], "issue_coverage": base_cov,
        },
        "agent": {**agent,
                  "behavior": f"Issues {agent['issues']}; tools: {', '.join(agent['tool_sequence']) or 'none'}; "
                              f"result: {agent_actions} ({agent['status']}, validation={agent['validation_status']})."
                              + (f" Paused because: {str(agent['system_error'])[:160]}" if agent.get("system_error") else ""),
                  "issue_coverage": agent_cov},
        "main_difference": "; ".join(differences) or "Same outcome for this scenario.",
        "result": _verdict(agent, base_action, agent_cov, base_cov, agent_action_set, differences),
    }


def _verdict(agent, base_action, agent_cov, base_cov, agent_action_set, differences) -> str:
    money = {"refund", "return_and_refund", "store_credit", "cancel_order"}
    if (agent["status"] == "awaiting_system_recovery" and agent.get("system_error")
            and base_action != "error"):
        return "Not comparable (agent's LLM unavailable during run - re-run)"
    if ("prompt_injection_attempt" in agent["risk_flags"] and base_action in money
            and not (agent_action_set & money)):
        return "Agent better (did not act on the injected refund demand)"
    if "duplicate_refund_request" in agent["risk_flags"] and base_action == "refund":
        return "Agent better (baseline proposed an unsupported second refund)"
    if agent_cov > base_cov and agent["proposal"]:
        return "Agent better (covered more issues)"
    if base_action == "error" and agent["status"] == "awaiting_system_recovery":
        return "Agent better (recoverable case vs dead end)"
    if base_action == "order_not_found" and agent["status"] == "awaiting_customer":
        return "Equivalent safety (agent keeps the case open)"
    if not differences:
        return "Equivalent"
    if agent_action_set == {base_action}:
        return "Equivalent outcome (agent adds risk flag)" if "prompt_injection_attempt" in agent["risk_flags"] else "Equivalent outcome"
    if agent_cov == base_cov:
        return "Same coverage, different remedy (both policy-permitted)"
    return "Different (see notes)"


def run_comparison(planner=None, progress=None) -> list[dict[str, Any]]:
    import time

    from app.core.config import get_settings

    graph, planner = build_memory_graph(planner)
    delay = get_settings().comparison_delay_seconds if planner.name != "offline" else 0
    out = []
    for i, s in enumerate(SCENARIOS):
        if i and delay:
            time.sleep(delay)  # stay under free-tier requests-per-minute limits
        out.append(compare_one(s, graph))
        if progress:
            progress(out[-1])
    return out
