# ResolveAI — Presentation Outline (8 slides)

## Slide 1 — Project Introduction
**ResolveAI: an Agentic AI system for e-commerce order, return and refund resolution**
- Customers describe problems in plain language: not arrived, late, damaged, wrong item, return, refund, cancel, or several at once.
- The agent investigates order records and store policies, proposes a resolution, checks it, and hands it to a human.
- Nothing financial is executed automatically. The administrator decides.

*Speaker note:* "Support teams spend most of their time on investigation, not on the decision. ResolveAI does the investigation and leaves the decision to a person."

## Slide 2 — Problem Statement
- Complaints are messy: missing order IDs, vague wording, two problems in one message, issues on different orders.
- Each problem needs different evidence: tracking for delays, photos for damage, refund history before any refund.
- Scripted bots force one category from a menu and run a fixed branch. They miss the second problem and skip checks their branch doesn't include.
- Wrong refunds cost money; slow ones cost customers.

## Slide 3 — Why Agentic AI?
| Traditional fixed workflow | ResolveAI agent |
|---|---|
| One category from a menu | Keeps every issue in the case |
| Same steps for every complaint in a category | Chooses the next tool from the evidence so far |
| Can't tell what extra information it needs | Asks only for what is missing, then resumes |
| A branch without a refund-history check never checks it | Checks refund history whenever money is involved |
| A failure ends the conversation | Pauses, saves the case and retries |

**Measured on 9 identical scenarios:** the agent covered 2/2 issues where the baseline covered 1/2 (S5, S9). It also blocked a second refund that the baseline queued (S6) and recovered from an outage where the baseline dead-ended (S8). Both were equivalent on simple cases (S3, S4).

## Slide 4 — System Architecture
Use the Mermaid diagram from `architecture.md`.
- React + Tailwind: customer chat and admin dashboard.
- FastAPI: REST API, admin auth, idempotency, upload validation.
- LangGraph: a stateful graph with a SQLite checkpointer (one thread per case).
- LLM (OpenAI or Gemini) for understanding and tool selection.
- Tools → Google Sheets (Orders, Store Policies, Resolution Logs) and Gmail (customer email after approval).
- Deterministic policy engine and independent validator.

## Slide 5 — Agent Workflow
Use the Mermaid diagram from `workflow.md`.
1. Understand: LLM structured output, plus regex for order IDs and an injection scan.
2. Completeness check: ask the customer if the order ID or issue is missing.
3. Agent loop: the LLM picks a tool → executor runs it with permission checks → the result feeds the next decision.
4. Proposal: the engine computes amounts. The LLM never sets money.
5. Validation: 9 deterministic checks. Failures go back for revision or to the customer.
6. Human approval interrupt → final response → **Gmail email to the customer** (irreversible, only after approval) → resolution log.

## Slide 6 — Human-in-the-Loop and Safety
- The LLM has no approval tool and no write access to policies or payments.
- Every proposal stops at `interrupt()`. The admin can approve (and edit the response), reject (a reason is required) or request information.
- Sending the customer email is the irreversible action. It runs only after the admin's decision, once per case. No payment code exists.
- Prompt injection: customer text is wrapped as untrusted data, flagged, and contained by the validator. A test shows that even a model that *obeys* the injection gets stopped.
- Duplicate approvals are blocked by idempotency keys plus a state check.
- Outages pause the case instead of inventing data.

## Slide 7 — Testing and Results
- 65 automated tests: 27 unit (policy engine, validator, safety), 27 integration (incl. 7 Gmail), 11 end-to-end. **65/65 passed** (executed 9 Nov 2026).
- All 8 required scenarios plus a two-orders scenario: PASS.
- Failures found and fixed: validator over-strict on duplicate-refund denials; comparison labelling; validator confusing "not looked up" with "not found".
- Honest limits: live LLM and live Sheets were not testable in the build environment. The offline planner is rule-based. Photo checks are file-level only.

## Slide 8 — Live Demo and Conclusion
- Demo: damaged product → multi-issue case → admin approval → prompt injection → comparison page.
- Outcome: a working agent that investigates adaptively, validates itself and keeps humans in control.
- Future work: vision model for photo assessment, admin overrides (exceptions), streaming progress, real carrier/payment APIs (read-only), customer authentication, evaluation across many real complaints.
