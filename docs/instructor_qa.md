# ResolveAI — Likely Instructor Questions

**1. Why an AI agent instead of a normal chatbot?**
A chatbot answers messages. This task needs *investigation*: look up the order, decide which checks apply, gather missing evidence, and combine findings across several problems. The agent loop (`agent` → `tools` → `agent`) lets the LLM decide the next check from the evidence so far. Our comparison measured the difference: on the multi-issue scenarios the fixed workflow covered 1 of 2 issues and the agent covered 2 of 2.

**2. Why is this an Agentic AI project?**
It has the core agent properties, and each one is implemented in code. Goal-directed tool use: 8 tools bound to the LLM with `bind_tools`. Persistent state across turns: LangGraph `AgentState` with a SQLite checkpointer. Adaptive control flow: conditional edges driven by tool results. Self-correction: validator feedback goes back to the agent. Human oversight: `interrupt()` before any decision.

**3. What makes it different from a fixed workflow?**
The fixed workflow (`app/baseline/traditional_workflow.py`) picks one category and runs that branch's predetermined checks. The agent keeps every issue. It selects tools per situation (delivery tools appear only for delivery issues, which is tested), asks only for missing information, and can call checks that a branch would not include. The clearest example is the refund-history check on a damage claim (scenario S6).

**4. Why LangGraph?**
We needed explicit state, conditional routing, pause/resume and persistence. LangGraph gives typed state with reducers, `interrupt()`/`Command(resume=…)` for human-in-the-loop, and checkpointers so a case survives a restart (test `e2e06`). A plain ReAct loop wouldn't give us the validation stage and approval checkpoint as first-class graph nodes.

**4b. Which external tools does it use?**
Three separate services. **Google Sheets** holds orders, store policies and the resolution log, and is read through six agent tools. **Gmail** emails the customer after an administrator's decision. **Gemini (or OpenAI)** does understanding and tool selection. The agent decides when and how to use the Sheets tools. Gmail is deliberately *not* given to the LLM, because sending is irreversible and must come after a human checkpoint.

**5. What is the purpose of the tools?**
Tools are the agent's only access to facts. Each returns structured data (order record, delivery facts, policies, eligibility, refund history, photo verification). This means the agent cannot invent facts: if a fact isn't in a tool result, the validator rejects any proposal that depends on it.

**6. How does the agent select tools?**
The `agent` node sends the LLM a system prompt, a regenerated case brief and all previous tool calls and results, with the tool schemas bound. The model returns tool calls. The executor validates arguments with Pydantic, enforces permissions (only this case's order IDs, only this case's evidence) and returns results as `ToolMessage`s for the next decision. Without an API key, a clearly labelled offline planner produces the same kind of tool calls with deterministic rules, so the system can still run.

**7. How does the system retrieve store policies?**
`retrieve_store_policies(issue_category, query)` reads the Store Policies sheet. It filters active policies by category and ranks them by keyword overlap. Thresholds such as `return_window_days=7` are machine-readable in the `policy_conditions` column, so the policy engine uses whatever the sheet says (tested: changing the window to 14 days changes the decision). This is structured retrieval, not vector search. With fewer than ten policies, exact category retrieval is more reliable.

**8. What is reflection/validation in your system?**
A separate, deterministic validator node runs nine checks: order exists, all issues addressed, order supports the complaint, policies retrieved, required investigation done, policy-consistent action, required evidence, no duplicate refund, no unsupported assumptions. It recomputes eligibility from raw tool outputs with the policy engine instead of trusting the agent's narrative. On failure it sends feedback to the agent (maximum 2 revisions), asks the customer, or escalates to the admin with the failures shown.

**9. Why is human approval necessary?**
Refunds are financial and policy P005 requires approval. LLMs can be wrong or manipulated. Some judgments need a human, such as whether a photo really shows damage or whether to grant an exception. The graph cannot reach the final response, or the Gmail send step, without passing the `human_approval` interrupt. The LLM has no tool that approves or sends anything. Sending is idempotent: one email per case, and resending is only allowed after a failure.

**10. What happens if the agent makes a wrong decision?**
There are three layers. First, the validator blocks actions the policy doesn't allow, inflated amounts, skipped checks and duplicate refunds. Second, the admin sees the evidence, the validation results and the full tool timeline, and can reject with a reason or request more information. Third, everything is recorded in the audit trail and resolution log. Test `LLM02` shows a model that skips investigation and proposes an unsupported refund ends as "escalate", still pending a human.

**11. How do you handle prompt injection?**
Customer text is untrusted. It is scanned for injection patterns (risk flag), passed to the LLM inside `<customer_message>` tags declared as data, and stripped of fake closing tags. More importantly, the design doesn't depend on detection: the model has no approval tool, amounts are computed deterministically, and every proposal is validated and needs a human.

**12. How do you handle missing information?**
The completeness check asks for missing order IDs or issue details before investigating. During investigation the agent calls `request_customer_information` (for example, a damage photo or what item actually arrived). The validator also asks if required evidence is missing. Each question pauses the graph with `interrupt()`, and the same case resumes when the customer replies or uploads.

**13. What happens if Google Sheets is unavailable?**
The adapter has a timeout and one retry, then raises `DataSourceUnavailable`. The tool executor records the failure and routes to the `system_recovery` interrupt. The status becomes "Awaiting system recovery" and an audit entry is written. The customer is told the case is saved. Nothing is invented. A customer message or the admin's Retry button resumes the investigation (test `e2e07`).

**14. How do you maintain conversation state?**
Each case is a LangGraph thread (`thread_id = case_id`) checkpointed to `checkpoints.db` after every node. The customer keeps the case ID (shown in the chat and stored in the browser) and can resume later, even after a server restart. A separate SQLite DB keeps the transcript, evidence metadata, audit trail and idempotency keys for the dashboard.

**15. What are the current limitations?**
Live LLM and live Google Sheets runs were not tested in the build environment. The offline planner is rule-based. Photo checks are file-level, not visual. Admins can't modify a proposed action, only approve, reject or ask. There is no customer authentication beyond the case ID. The service runs as a single worker, and the agent runs inside the HTTP request.

**16. How could it be improved?**
Use a vision model to pre-assess damage photos. Add admin overrides for policy exceptions, with re-validation. Stream progress (Server-Sent Events) and move investigation to a background worker. Add read-only carrier tracking APIs. Add customer verification by email OTP. Add a Postgres checkpointer for multiple workers. Track LangSmith traces and an evaluation set of real complaints to measure accuracy per model.
