# ResolveAI — Failure Report

Problems found while building and testing, in the order they were found.

| # | What failed? | Why did it fail? | What was changed? | Did the fix work? |
|---|---|---|---|---|
| F1 | Duplicate-refund scenario (S6) was escalated with `validation_failed_escalated` after three identical proposals | The validator required `verify_damage_evidence` for **every** damage item, even when the agent correctly proposed *deny* because the order was already refunded. The agent could not satisfy the check, so it ran out of revisions | `required_investigation_done` now requires the evidence step only when the action grants something (refund/replacement), not for deny/escalate/no-action | Yes — S6 now validates as `valid` with `deny`; `test_tc06` passes |
| F2 | Same scenario: the offline planner asked the customer for a photo on an already-refunded order | Planner logic did not consider that the refund history makes the photo irrelevant | Planner skips evidence requests when `check_previous_refund` reports a duplicate; validator no longer demands evidence for deny/no-action items | Yes |
| F3 | Comparison table labelled identical outcomes as "different" (e.g. `return_request->deny` vs `deny`) | Compared an "issue->action" string with a bare action | Compare sets of actions; verdict logic moved to `_verdict()` with explicit categories | Yes |
| F4 | Comparison reported baseline issue coverage 0/1 for the nonexistent-order and outage scenarios although it had classified them correctly | Coverage used "categories handled" (empty when the branch stops early) | Coverage now uses the baseline's classification | Yes |
| F5 | (Found in code review while writing the LLM injection test, before running it.) If the model proposed a resolution **without looking up the order**, the validator would have told the customer "I couldn't find your order" | `order_exists` treated "not looked up" the same as "not found" | Only orders actually looked up and returned `found=false` trigger the customer question; un-looked-up orders send the proposal back to the agent | Yes — `test_llm_obeying_injection_is_still_blocked` passes and ends in `escalate`, not in a false customer message |
| F6 | Customer chat showed the final resolution twice (as a chat bubble and in the "Final resolution" box) | Found while reviewing UI screenshots from headless Chrome | Hide the last agent bubble when it equals the final response | Yes (verified by screenshot) |
| F8 | Admin "Customer email" card: long email addresses overflowed the card | Grid label column too wide and no wrapping for unbroken strings | Narrower label column, `overflow-wrap:anywhere` | Yes (verified by screenshot) |
| F7 | Outbound calls to `api.openai.com` returned 403 from the sandbox proxy | Build environment restricts network egress; no API key either | Built the full LLM path, tested with a scripted model, added a clearly labelled offline planner so the system still runs | **Partially** — the code path is tested, a live LLM run is not |

## Unresolved

* **Live LLM behaviour is unverified.** Real models may choose tools in a different order, ask different questions or
  propose different remedies. The validator and permission checks are designed to contain this, but prompt quality with a
  specific model has not been measured. *Action:* run all scenarios with your key before the demo and note any differences.
* **Google Sheets connectivity is unverified** (no credentials). *Action:* follow README §4, run the seed script, then
  start a case and confirm a row appears in "Resolution Logs".
* **Gemini model names change often.** The default is `gemini-3.8-flash`; if Google retires it, set `GEMINI_MODEL` to a
  current free Flash model shown in AI Studio.
* Limitations listed in `testing_report.md` §5.
