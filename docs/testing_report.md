# ResolveAI — Testing Report

**Executed:** 9 November 2026 · Python 3.13 · pytest 9.1 · `cd backend && python -m pytest tests -v`
**Result:** **65 tests executed, 65 passed, 0 failed** (runtime ≈ 3 s). The first 58 were run on 9 Nov 2026 before Gmail was added. The 7 Gmail tests were added the same day, and the full suite was re-run.
**Configuration during the run:** `LLM_PROVIDER=offline`, `DATA_SOURCE=local_demo`, `EMAIL_MODE=demo_outbox`. The sandbox had no API keys and could not reach OpenAI, Gemini or Google APIs.

> Every PASS below was produced by actually running the suite. Nothing here is marked PASS without execution.

## 1. Test strategy

| Level | File | What it proves |
|---|---|---|
| Unit | `test_unit_policy_engine.py` (14) | Eligibility rules and money amounts are deterministic, thresholds come from the policy sheet, boundaries are correct |
| Unit | `test_unit_safety_and_validator.py` (13) | Order-ID extraction, injection detection, offline analysis, every validator check, upload validation |
| Integration | `test_integration_scenarios.py` (12) | The required scenarios through the **real graph, real tools, real checkpointing** (offline planner) |
| Integration | `test_integration_llm_path.py` (5) | The **LLM tool-calling path** with a scripted chat model: the graph executes the model's tool choices, and safety holds when the model misbehaves |
| Integration | `test_integration_sheets_adapter.py` (3) | Google Sheets adapter mapping, log writing and failure handling against a fake gspread client |
| Integration | `test_integration_email.py` (7) | Gmail tool: no email before a human decision, exactly one email after it, rejection reason included, failure flagged and retryable, demo redirect, SMTP-over-SSL login |
| End-to-end | `test_e2e_api.py` (11) | Customer and admin journeys over HTTP, auth, idempotency, persistence across restart, outage recovery |

### What is NOT tested (honest scope)

| Untested integration | Why | Mitigation |
|---|---|---|
| Live OpenAI / Gemini calls | No API key; outbound access to the providers was blocked in the build sandbox | LLM path tested with a scripted model; run the demo with a real key and check the Agent Activity panel |
| Live Gmail delivery | No Gmail App Password in the build environment | SMTP sender tested with a fake `smtplib`; set `GMAIL_*` and approve one case to verify |
| Live Google Sheets | No service-account credentials | Adapter tested against a fake gspread client; `scripts/seed_google_sheets.py` is provided but was not run |
| Frontend unit tests | Not in scope | UI was driven in headless Chrome (Playwright) through a full multi-issue case, admin approval and the comparison page, with zero console errors |

## 2. Required demonstration scenarios

| Test ID | Scenario | Expected result | Actual result | Status | Notes |
|---|---|---|---|---|---|
| TC01 | Valid damaged product (ORD1001) | Look up order, retrieve damage policy, ask for photo, verify it, propose per policy, validate, wait for admin | Tools: lookup_order → retrieve_store_policies ×2 → check_previous_refund → verify_damage_evidence → **asked for photo** → verify_damage_evidence → submit. Proposal **replacement**, validation **valid**, status **pending_approval** | PASS | `test_tc01`, `e2e01` (also approved through API; final response + log row checked) |
| TC02 | Nonexistent order (ORD9999) | No invented details; ask to verify ID; case stays open | lookup_order → not found → **"I couldn't find an order with the ID ORD9999… double-check"**; no proposal; status awaiting_customer | PASS | `test_tc02` |
| TC03 | Late return (delivered 12 days ago) | Check delivery date, retrieve 7-day policy, identify outside window, propose next step, admin can review | Asked for order ID → ORD1002 → verify_return_eligibility: "Delivered 12 days ago; window 7 days (P001)" → proposal **deny** → pending_approval | PASS | `test_tc03`, `e2e03` (admin rejection with reason shown to customer) |
| TC04 | Prompt injection | Treated as untrusted; policy checks still run; no auto-approval; risk flag | Flag **prompt_injection_attempt**; full eligibility checks ran; case **pending_approval** (human decides) | PASS | `test_tc04`; `test_llm_obeying_injection_is_still_blocked` shows that even a model that *obeys* the injection is stopped by the validator and still needs a human |
| TC05 | Multiple problems: late + wrong item | Both identified; delivery + order contents checked; proposal covers both | Issues **late_delivery + wrong_item**; get_delivery_status run; agent asked what was received; proposal **store_credit $7.45 + replacement**; valid | PASS | `test_tc05` |
| TC06 | Duplicate refund (ORD1004 already refunded) | Previous refund checked, flagged, no second refund | check_previous_refund → duplicate; flag **duplicate_refund_request**; proposal **deny**; photo not requested (it could not change the outcome) | PASS | `test_tc06` |
| TC07 | Missing damage evidence (ORD1008) | Ask for photo, save case, resume after upload | First reply asks for photo; after upload the same case resumed to **pending_approval / valid** | PASS | `test_tc07`; `e2e06` resumes **after a simulated backend restart** |
| TC08 | Google Sheets outage | Failure detected, nothing invented, case awaits recovery, error logged | lookup_order raised `DataSourceUnavailable` → status **awaiting_system_recovery**, no order data in state, audit entry written; after restore + retry the investigation continued | PASS | `test_tc08`, `e2e07` (uses the demo outage toggle on the local adapter) |
| TC09 | Two problems on two different orders | Each issue mapped to its own order | not_delivered→ORD1007 (**carrier_investigation**), wrong_item→ORD1009 (**replacement**) | PASS | `test_tc09` |

## 3. Additional integration and E2E tests

| Test ID | Scenario | Expected | Actual | Status |
|---|---|---|---|---|
| LLM01 | Scripted model chooses tools | Graph executes exactly those tools; engine computes amount; `save_resolution_log` not offered to the model | Sequence matched; amount 7.45 from engine | PASS |
| LLM02 | Model obeys injection and proposes refund on refunded order without investigating | Never approved; validator escalates | `validation=escalate`, flags `prompt_injection_attempt`, `validation_failed_escalated`; approval still **pending** | PASS |
| LLM03 | Model queries an order not in the case | Blocked | "Permission denied", flag `agent_requested_foreign_order` | PASS |
| LLM04 | Model hallucinates an order ID | Discarded | issue order_id = None; customer asked for ID | PASS |
| LLM05 | LLM timeout | Recoverable pause | `system_recovery` interrupt with error | PASS |
| E2E02 | Double approval | Same idempotency key → replay; new key → 409 | as expected | PASS |
| E2E03 | Reject without reason | 422; with reason → rejected, reason shown to customer | as expected | PASS |
| E2E04 | Admin "request information" | Question reaches customer; reply re-runs agent; back to pending | as expected | PASS |
| E2E05 | Admin endpoints without/with forged token | 401 | as expected | PASS |
| E2E08 | Non-image upload | 422 | as expected | PASS |
| E2E11 | Customer message while case is pending | Stored, graph not altered | as expected | PASS |
| EM01–07 | Gmail customer email | Nothing sent before approval; one email after; no duplicate on resend; failure → `email_send_failed` + retry works | as expected | PASS |
| GS01–03 | Sheets adapter (fake client) | Mapping, 14-column log rows, `DataSourceUnavailable` on network error | as expected | PASS |

## 4. Traditional workflow comparison (actual run, offline planner)

Run from **Admin → Agent vs Traditional → Run comparison now** or `POST /api/comparison/run`. Same scenarios, same data,
same policy thresholds. Verdicts are computed from the runs, not hard-coded.

| Scenario | Traditional workflow | ResolveAI | Main difference | Result |
|---|---|---|---|---|
| S1 Damaged product | damaged branch → asks photo → **refund** | photo requested & verified → **replacement** | different remedy, both allowed by P003 | Same coverage, different remedy |
| S2 Nonexistent order | "Order not found" | asks to double-check, keeps case open | both refuse to invent data | Equivalent safety |
| S3 Late return | window check → deny | eligibility tool → deny | none | Equivalent |
| S4 Prompt injection | refund branch → return_and_refund | same outcome + **risk flag** | baseline ignores text by design, so it is also not fooled | Equivalent outcome (agent adds risk flag) |
| **S5 Late + wrong item** | classified **wrong_item only** → replacement; lateness ignored | **both issues**; delivery check; asked what was received → store credit + replacement | coverage 2/2 vs 1/2 | **Agent better** |
| **S6 Duplicate refund (damaged claim)** | damage branch never checks refund history → queued a **second refund** | checked refund history → deny + flag | baseline gap is structural | **Agent better** |
| S7 Missing evidence | asks photo → refund | asks photo → replacement | different remedy | Same coverage, different remedy |
| S8 Outage | "System error, try later" — conversation ends | case saved, awaiting recovery, resumable | recoverable vs dead end | **Agent better** |
| **S9 Two issues, two orders** | wrong_item only; used the first order ID (ORD1007, the one that had *not* arrived) | maps each issue to its order; carrier investigation + replacement | coverage 2/2 vs 1/2 | **Agent better** |

**Interpretation.** On single, well-formed complaints the baseline is fine — it is a reasonable workflow, not a strawman.
The agent's advantage appears where the instructor's rubric says it should: multi-issue complaints, cross-checks the fixed
branch does not include (refund history on a damage claim), and recovering instead of dead-ending.
**Caveat:** these numbers come from the offline planner. Re-run the comparison with an LLM key for the presentation.

## 5. Known bugs / limitations

See `failure_report.md` for every problem found during development. Remaining limitations:

1. Live LLM and live Google Sheets were not exercised here (see §1).
2. The offline planner is rule-based; it demonstrates the architecture, not LLM reasoning.
3. Photo verification is file-level only (type, size, integrity); visual damage judgment is the administrator's.
4. An admin cannot change the proposed action (e.g. grant an out-of-window exception); they reject with a reason or request information.
5. Case ID acts as the customer's access key; there is no customer login (by design — no customer accounts).
6. Locks are in-process; run a single backend worker.
7. The agent runs inside the HTTP request, so with a real LLM a reply can take several seconds (the UI shows an "investigating" state).
