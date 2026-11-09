import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../services/api.js'
import { Button, ErrorNote, RuntimeBanner, StatusBadge } from '../components/ui.jsx'

const CASE_KEY = 'resolveai_case_id'
const WELCOME =
  "Hi, I'm ResolveAI. I can help with orders that haven't arrived, late deliveries, damaged or wrong items, returns, refunds and cancellations - even several problems at once. Tell me what happened (include your order ID if you have it)."

const STATUS_HINT = {
  awaiting_customer: 'Waiting for your reply',
  info_requested: 'Our team asked a question',
  pending_approval: 'Investigation complete - awaiting human approval',
  awaiting_system_recovery: 'System temporarily unavailable - your case is saved',
  approved: 'Resolved',
  rejected: 'Reviewed',
}

export default function CustomerChat() {
  const [params, setParams] = useSearchParams()
  const [caseId, setCaseId] = useState(params.get('case') || localStorage.getItem(CASE_KEY))
  const [view, setView] = useState(null)
  const [runtime, setRuntime] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [resumeId, setResumeId] = useState('')
  const fileRef = useRef(null)
  const endRef = useRef(null)

  useEffect(() => { api.health().then(setRuntime).catch((e) => setErr(e.message)) }, [])

  useEffect(() => {
    if (!caseId) return
    api.getCustomerCase(caseId).then(setView).catch(() => {
      setErr('That case could not be found. Starting a new conversation.')
      startOver()
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  // Poll while the case is with a human or awaiting recovery, so the outcome appears without refresh.
  useEffect(() => {
    if (!view || !['pending_approval', 'awaiting_system_recovery'].includes(view.status)) return
    const t = setInterval(() => api.getCustomerCase(view.case_id).then(setView).catch(() => {}), 5000)
    return () => clearInterval(t)
  }, [view])

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [view, busy])

  const remember = (v) => {
    setView(v)
    setCaseId(v.case_id)
    localStorage.setItem(CASE_KEY, v.case_id)
    setParams({ case: v.case_id }, { replace: true })
  }

  const send = async (e) => {
    e?.preventDefault()
    const msg = text.trim()
    if (!msg || busy) return
    setBusy(true)
    setErr(null)
    setText('')
    setView((v) => v ? { ...v, messages: [...v.messages, { role: 'customer', content: msg, pending: true }] }
      : { case_id: null, status: 'investigating', messages: [{ role: 'customer', content: msg, pending: true }] })
    try {
      remember(caseId && view?.case_id ? await api.sendMessage(caseId, msg) : await api.startComplaint(msg))
    } catch (ex) {
      setErr(ex.message)
      setText(msg)
    } finally {
      setBusy(false)
    }
  }

  const upload = async (file) => {
    if (!file || !view?.case_id) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return setErr('Please choose a JPEG, PNG or WEBP image.')
    if (file.size > 5 * 1024 * 1024) return setErr('Image must be 5 MB or smaller.')
    setBusy(true)
    setErr(null)
    try {
      remember(await api.uploadEvidence(view.case_id, file))
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const startOver = () => {
    localStorage.removeItem(CASE_KEY)
    setCaseId(null)
    setView(null)
    setParams({}, { replace: true })
  }

  const closed = ['approved', 'rejected'].includes(view?.status)
  const messages = view?.messages || []

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Resolve<span className="text-blue-600">AI</span> <span className="font-normal text-slate-500">Customer Support</span></h1>
          {view?.case_id && (
            <p className="mt-0.5 text-xs text-slate-500">Case ID <span className="font-mono font-medium text-slate-700">{view.case_id}</span> · save it to come back later</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {view?.status && <StatusBadge status={view.status} />}
          {view?.case_id && <Button variant="secondary" onClick={startOver}>New conversation</Button>}
        </div>
      </header>

      <RuntimeBanner runtime={runtime} />

      <div className="mt-4 flex-1 space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        <Bubble role="agent" content={WELCOME} />
        {messages.map((m, i) => (closed && i === messages.length - 1 && m.role === 'agent' && m.content === view.final_response) ? null : <Bubble key={i} {...m} />)}
        {busy && (
          <div className="flex items-center gap-2 pl-1 text-sm text-slate-500">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue-600" /> ResolveAI is investigating - checking order records and store policies…
          </div>
        )}
        {view?.status && STATUS_HINT[view.status] && !busy && !closed && (
          <div className={`rounded-lg px-3 py-2 text-xs ${view.status === 'pending_approval' ? 'bg-indigo-50 text-indigo-800' : view.status === 'awaiting_system_recovery' ? 'bg-rose-50 text-rose-800' : 'bg-slate-50 text-slate-600'}`}>
            {view.status === 'pending_approval' && <b>Human approval required. </b>}{STATUS_HINT[view.status]}
          </div>
        )}
        {closed && view.final_response && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide">Final resolution</div>
            {view.final_response}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <ErrorNote>{err}</ErrorNote>

      <form onSubmit={send} className="mt-3 flex items-end gap-2">
        <textarea
          className="min-h-[46px] flex-1 resize-none rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm focus:border-blue-500 focus:outline-none"
          rows={2}
          placeholder={closed ? 'This case is closed - start a new conversation for a new issue' : 'Describe your issue…'}
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) send(e) }}
        />
        <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
        <Button type="button" variant="secondary" disabled={!view?.case_id || busy || closed} onClick={() => fileRef.current?.click()} title="Upload a photo of the damage">
          📷 Photo
        </Button>
        <Button disabled={busy || !text.trim()}>Send</Button>
      </form>

      {!view?.case_id && (
        <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
          Have a case ID?
          <input className="w-44 rounded-md border border-slate-300 px-2 py-1 font-mono" placeholder="RAI-XXXXXXXXXX" value={resumeId} onChange={(e) => setResumeId(e.target.value.trim())} />
          <button className="text-blue-600 hover:underline" onClick={() => resumeId && setCaseId(resumeId)}>Resume case</button>
        </div>
      )}
    </div>
  )
}

function Bubble({ role, content, progress, pending }) {
  const mine = role === 'customer'
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${mine ? 'rounded-br-md bg-blue-600 text-white' : 'rounded-bl-md bg-slate-100 text-slate-900'} ${pending ? 'opacity-70' : ''}`}>
        {!mine && progress?.length > 0 && (
          <ul className="mb-2 space-y-0.5 border-b border-slate-200 pb-2 text-xs text-slate-500">
            {progress.map((p) => <li key={p}>✓ {p}</li>)}
          </ul>
        )}
        <div className="whitespace-pre-wrap">{content}</div>
      </div>
    </div>
  )
}
