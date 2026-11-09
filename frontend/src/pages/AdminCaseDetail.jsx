import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { Button, Card, ErrorNote, ISSUE_LABELS, KeyValue, Pill, Spinner, StatusBadge, fmtTime, money } from '../components/ui.jsx'

export default function AdminCaseDetail() {
  const { caseId } = useParams()
  const { data: c, error, loading, reload, setData } = useAsync(() => api.caseDetail(caseId), [caseId])
  if (loading && !c) return <Spinner label="Loading case…" />
  if (error) return <ErrorNote>{error}</ErrorNote>
  if (!c) return null

  const orders = Object.entries(c.order_information || {})
  const policies = Object.entries(c.retrieved_policies || {})
  const val = c.validation_result

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/admin/cases" className="text-xs text-blue-600 hover:underline">← All cases</Link>
          <h1 className="mt-1 flex items-center gap-3 text-xl font-semibold"><span className="font-mono">{c.case_id}</span><StatusBadge status={c.status} /></h1>
          <p className="text-xs text-slate-500">Created {fmtTime(c.created_at)} · Updated {fmtTime(c.updated_at)} · Planner: {c.runtime?.planner_label}</p>
        </div>
        <Button variant="secondary" onClick={reload}>Refresh</Button>
      </div>

      {c.system_error && (
        <ErrorNote><b>System error:</b> {c.system_error}. No order data was assumed. Restore the data source, then retry.</ErrorNote>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title="1. Customer complaint">
            <p className="text-sm text-slate-800">{c.first_message}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {c.identified_issues.map((i) => <Pill key={i.type + i.order_id} tone="blue">{ISSUE_LABELS[i.type]} · {i.order_id || 'no order ID'}</Pill>)}
            </div>
            {Object.keys(c.customer_claims || {}).length > 0 && (
              <div className="mt-3"><KeyValue rows={Object.entries(c.customer_claims).map(([k, v]) => [k.replaceAll('_', ' '), v])} /></div>
            )}
          </Card>

          <Card title="2. Conversation history">
            <ul className="space-y-2 text-sm">
              {c.messages.map((m, i) => (
                <li key={i} className={`rounded-lg px-3 py-2 ${m.role === 'customer' ? 'bg-blue-50' : m.role === 'admin' ? 'bg-amber-50' : 'bg-slate-50'}`}>
                  <div className="mb-0.5 text-xs text-slate-500"><b className="capitalize">{m.role}</b>{m.meta?.internal ? ' (internal note)' : ''} · {fmtTime(m.created_at)}</div>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="3. Order lookup results" subtitle={c.runtime?.data_source_label}>
            {!orders.length && <p className="text-sm text-slate-400">No order looked up yet.</p>}
            <div className="space-y-4">
              {orders.map(([oid, rec]) => (
                <div key={oid}>
                  <div className="mb-1 font-mono text-sm font-medium">{oid} {!rec.found && <Pill tone="red">NOT FOUND</Pill>}</div>
                  {rec.found && <KeyValue rows={[
                    ['Customer', `${rec.order.customer_name} (${rec.order.customer_email})`],
                    ['Product', `${rec.order.product_name} · ${money(rec.order.product_price)}`],
                    ['Ordered / delivered', `${rec.order.order_date} → ${rec.order.delivery_date || 'not delivered'}`],
                    ['Delivery status', rec.order.delivery_status],
                    ['Tracking', rec.order.tracking_number || '—'],
                    ['Payment', rec.order.payment_method],
                    ['Condition', rec.order.product_condition],
                    ['Return / previous refund', `${rec.order.return_status} / ${rec.order.previous_refund_status}`],
                    c.delivery_information?.[oid] && ['Delivery check', deliverySummary(c.delivery_information[oid])],
                    c.return_eligibility?.[oid] && ['Return eligibility', `${c.return_eligibility[oid].eligible ? 'Eligible' : 'Not eligible'} - ${c.return_eligibility[oid].reasons.join(' ')}`],
                    c.refund_checks?.[oid] && ['Refund history', c.refund_checks[oid].duplicate ? 'ALREADY REFUNDED' : 'No previous refund'],
                  ]} />}
                </div>
              ))}
            </div>
          </Card>

          <Card title="4. Store policy evidence" subtitle="Retrieved by the agent's retrieve_store_policies tool">
            {!policies.length && <p className="text-sm text-slate-400">No policies retrieved yet.</p>}
            <ul className="space-y-2 text-sm">
              {policies.flatMap(([cat, list]) => list.map((p) => (
                <li key={cat + p.policy_id} className="rounded-lg border border-slate-100 px-3 py-2">
                  <div className="flex items-center gap-2"><Pill>{p.policy_id}</Pill><span className="text-xs text-slate-500">{p.policy_category}</span></div>
                  <p className="mt-1">{p.policy_description}</p>
                  <p className="mt-0.5 font-mono text-xs text-slate-500">{p.policy_conditions}</p>
                </li>
              )))}
            </ul>
            {c.policy_assessments?.length > 0 && (
              <div className="mt-4">
                <div className="mb-1 text-xs font-semibold uppercase text-slate-500">Deterministic policy assessment</div>
                <ul className="space-y-1 text-xs">
                  {c.policy_assessments.map((a) => (
                    <li key={a.issue + a.order_id}><b>{ISSUE_LABELS[a.issue]}</b> ({a.order_id}): allowed {a.allowed_actions.join(', ')} - {a.findings.join(' ')}</li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          <Card title="8. Agent investigation & tool activity" subtitle="Concise audit summaries - no private chain-of-thought is stored">
            <ol className="relative space-y-2 border-l border-slate-200 pl-4 text-sm">
              {c.investigation_history.map((h, i) => (
                <li key={i}>
                  <span className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${h.ok === false ? 'bg-rose-500' : h.step === 'tool' ? 'bg-blue-500' : 'bg-slate-300'}`} />
                  <div className="text-xs text-slate-500">{fmtTime(h.at)} · {h.step}{h.tool ? ` · ${h.tool}` : ''}{h.planner ? ` · ${h.planner}` : ''}</div>
                  <div className={h.ok === false ? 'text-rose-700' : ''}>{h.summary}</div>
                </li>
              ))}
            </ol>
          </Card>
        </div>

        <div className="space-y-5">
          <AdminActions c={c} onDone={(updated) => setData(updated)} />

          <Card title="5. Proposed resolution">
            {!c.proposed_resolution ? <p className="text-sm text-slate-400">No proposal yet.</p> : (
              <div className="space-y-3 text-sm">
                {c.proposed_resolution.items.map((it) => (
                  <div key={it.issue + it.order_id} className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="flex items-center justify-between"><b>{ISSUE_LABELS[it.issue]}</b><span className="font-mono text-xs">{it.order_id}</span></div>
                    <div className="mt-1"><Pill tone="green">{it.action.replaceAll('_', ' ')}</Pill> {it.amount > 0 && <span className="ml-1 font-medium">{money(it.amount)}</span>}</div>
                    <p className="mt-1 text-xs text-slate-600">{it.rationale}</p>
                    {it.policy_ids?.length > 0 && <p className="mt-1 text-xs text-slate-500">Policies: {it.policy_ids.join(', ')}</p>}
                  </div>
                ))}
                <p className="text-xs text-slate-600"><b>Summary:</b> {c.proposed_resolution.summary}</p>
              </div>
            )}
          </Card>

          <Card title="6. Validation result" subtitle="Independent deterministic validator">
            {!val ? <p className="text-sm text-slate-400">Not validated yet.</p> : (
              <>
                <div className="mb-2"><Pill tone={val.status === 'valid' ? 'green' : val.status === 'escalate' ? 'red' : 'amber'}>{val.status}</Pill></div>
                <ul className="space-y-1.5 text-xs">
                  {val.checks.map((ch) => (
                    <li key={ch.name} className="flex gap-2">
                      <span className={ch.passed ? 'text-emerald-600' : 'text-rose-600'}>{ch.passed ? '✓' : '✗'}</span>
                      <span><b>{ch.name.replaceAll('_', ' ')}</b> - {ch.detail}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Card>

          <Card title="7. Risk flags" subtitle="Internal only - never shown to the customer">
            {c.risk_flags.length ? <div className="flex flex-wrap gap-1.5">{c.risk_flags.map((f) => <Pill key={f} tone="red">{f}</Pill>)}</div>
              : <p className="text-sm text-slate-400">None</p>}
          </Card>

          <EmailCard c={c} onDone={(updated) => setData(updated)} />

          <Evidence c={c} />

          <Card title="Audit trail">
            <ul className="space-y-1 text-xs">
              {c.audit.map((a, i) => <li key={i}><span className="text-slate-500">{fmtTime(a.created_at)}</span> · <b>{a.actor}</b> · {a.action}</li>)}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  )
}

function deliverySummary(d) {
  if (d.delivery_days != null) return `Delivered in ${d.delivery_days} days (threshold ${d.late_threshold_days}) - ${d.was_late ? 'LATE' : 'on time'}`
  if (d.days_since_order != null) return `${d.days_since_order} days since order, not delivered - ${d.presumed_lost ? 'presumed lost' : d.is_overdue ? 'OVERDUE' : 'within window'}`
  return d.delivery_status
}

function Evidence({ c }) {
  const [urls, setUrls] = useState({})
  useEffect(() => {
    let alive = true
    c.evidence.forEach((e) => api.evidenceBlob(c.case_id, e.id).then((u) => alive && setUrls((x) => ({ ...x, [e.id]: u }))).catch(() => {}))
    return () => { alive = false }
  }, [c.case_id, c.evidence.length])
  return (
    <Card title="Damage photo evidence" subtitle={c.evidence_verification ? c.evidence_verification.note : 'No verification run'}>
      {!c.evidence.length ? <p className="text-sm text-slate-400">No photos uploaded.</p> : (
        <div className="grid grid-cols-2 gap-2">
          {c.evidence.map((e) => (
            <a key={e.id} href={urls[e.id]} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border border-slate-200">
              {urls[e.id] ? <img src={urls[e.id]} alt={e.filename} className="h-24 w-full object-cover" /> : <div className="h-24 bg-slate-100" />}
              <div className="truncate px-2 py-1 text-xs text-slate-500">{e.filename}</div>
            </a>
          ))}
        </div>
      )}
    </Card>
  )
}

function AdminActions({ c, onDone }) {
  const [mode, setMode] = useState(null)
  const [note, setNote] = useState('')
  const [response, setResponse] = useState(c.draft_customer_response || '')
  const [reason, setReason] = useState('')
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  useEffect(() => { setResponse(c.draft_customer_response || '') }, [c.draft_customer_response])

  const act = async (fn) => {
    setBusy(true)
    setErr(null)
    try {
      const r = await fn()
      onDone(r.case)
      setMode(null)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  if (c.awaiting === 'system_recovery') {
    return (
      <Card title="9. Administrator actions">
        <p className="mb-3 text-sm text-slate-600">The investigation is paused because a data source was unavailable.</p>
        <ErrorNote>{err}</ErrorNote>
        <Button disabled={busy} onClick={() => act(() => api.retry(c.case_id))}>Retry investigation</Button>
      </Card>
    )
  }
  if (c.awaiting !== 'admin_review') {
    return (
      <Card title="9. Administrator actions">
        <p className="text-sm text-slate-600">
          {c.status === 'approved' || c.status === 'rejected'
            ? <>Decision recorded: <b>{c.administrator_decision?.decision}</b> by {c.administrator_decision?.admin}{c.administrator_decision?.reason ? ` - “${c.administrator_decision.reason}”` : ''}.</>
            : 'No decision needed yet - the case is not awaiting approval.'}
        </p>
        {c.final_response && <div className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-900"><div className="text-xs font-semibold">Final customer response</div>{c.final_response}</div>}
        {c.log_saved != null && <p className="mt-2 text-xs text-slate-500">Resolution log: {c.log_saved ? 'saved' : 'FAILED to save (see risk flags)'}</p>}
      </Card>
    )
  }
  return (
    <Card title="9. Administrator actions" subtitle="Approving sends the customer email (irreversible). No payment is ever executed.">
      <ErrorNote>{err}</ErrorNote>
      <div className="flex flex-wrap gap-2">
        <Button variant="success" onClick={() => setMode('approve')}>Approve & email</Button>
        <Button variant="danger" onClick={() => setMode('reject')}>Reject</Button>
        <Button variant="secondary" onClick={() => setMode('info')}>Request info</Button>
      </div>
      {mode === 'approve' && (
        <div className="mt-4 space-y-2 text-sm">
          <label className="block">Final customer response (editable)
            <textarea rows={6} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={response} onChange={(e) => setResponse(e.target.value)} />
          </label>
          <label className="block">Internal note (optional)
            <input className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <Button variant="success" disabled={busy} onClick={() => act(() => api.approve(c.case_id, { note: note || undefined, customer_response: response !== c.draft_customer_response ? response : undefined }))}>
            {busy ? 'Saving…' : `Confirm approval & send email`}
          </Button>
        </div>
      )}
      {mode === 'reject' && (
        <div className="mt-4 space-y-2 text-sm">
          <label className="block">Reason (required, shown to the customer)
            <textarea rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="block">Internal note (optional)
            <input className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <p className="text-xs text-slate-500">The customer will be emailed this reason.</p>
          <Button variant="danger" disabled={busy || reason.trim().length < 3} onClick={() => act(() => api.reject(c.case_id, { reason, note: note || undefined }))}>Confirm rejection</Button>
        </div>
      )}
      {mode === 'info' && (
        <div className="mt-4 space-y-2 text-sm">
          <label className="block">Question for the customer
            <textarea rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5" value={question} onChange={(e) => setQuestion(e.target.value)} />
          </label>
          <Button disabled={busy || question.trim().length < 3} onClick={() => act(() => api.requestInfo(c.case_id, { question, note: note || undefined }))}>Send request</Button>
        </div>
      )}
    </Card>
  )
}

function EmailCard({ c, onDone }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const emails = c.emails || []
  const last = emails[emails.length - 1]
  const delivered = emails.some((e) => e.status === 'sent' || e.status === 'recorded')
  const resend = async () => {
    setBusy(true)
    setErr(null)
    try { onDone((await api.resendEmail(c.case_id)).case) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <Card title="Customer email (Gmail)" subtitle="Sent only after an administrator decision - never by the agent">
      {!last ? <p className="text-sm text-slate-400">Not sent - waiting for an administrator decision.</p> : (
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2">
            <Pill tone={last.status === 'sent' ? 'green' : last.status === 'recorded' ? 'amber' : 'red'}>
              {last.status === 'recorded' ? 'recorded (demo outbox, not sent)' : last.status}
            </Pill>
            <span className="text-xs text-slate-500">{fmtTime(last.created_at)}</span>
          </div>
          <KeyValue rows={[
            ['To', last.to_address],
            last.to_address !== last.intended_address && ['Customer address', `${last.intended_address} (demo redirect)`],
            ['Subject', last.subject],
          ]} />
          {last.error && <ErrorNote>{last.error}</ErrorNote>}
          <details className="text-xs text-slate-600"><summary className="cursor-pointer">Email body</summary><pre className="mt-1 whitespace-pre-wrap font-sans">{last.body}</pre></details>
          <ErrorNote>{err}</ErrorNote>
          {!delivered && <Button variant="secondary" disabled={busy} onClick={resend}>{busy ? 'Sending…' : 'Retry sending email'}</Button>}
        </div>
      )}
    </Card>
  )
}
