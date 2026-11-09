import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { Button, Card, ErrorNote, ISSUE_LABELS, RuntimeBanner, Spinner, STATUS_LABELS } from '../components/ui.jsx'

const ACTION_LABELS = {
  refund: 'Refund', replacement: 'Replacement', return_and_refund: 'Return & refund', store_credit: 'Store credit',
  cancel_order: 'Cancel order', carrier_investigation: 'Carrier investigation', deny: 'Deny', no_action_needed: 'No action', escalate: 'Escalate',
}

export default function AdminOverview() {
  const stats = useAsync(() => api.stats(), [])
  const outage = useAsync(() => api.outage(), [])
  const logs = useAsync(() => api.logs(), [])
  const [err, setErr] = useState(null)

  if (stats.loading && !stats.data) return <Spinner label="Loading dashboard…" />
  const s = stats.data || {}
  const cards = [
    ['Total cases', s.total_cases, ''],
    ['Pending approval', s.pending_approval, 'pending_approval'],
    ['Approved', s.approved, 'approved'],
    ['Rejected', s.rejected, 'rejected'],
    ['Need more information', (s.by_status?.awaiting_customer || 0) + (s.by_status?.info_requested || 0), 'awaiting_customer'],
    ['Awaiting recovery', s.awaiting_system_recovery, 'awaiting_system_recovery'],
  ]

  const toggle = async () => {
    setErr(null)
    try {
      await api.setOutage(!outage.data?.simulate_outage)
      outage.reload()
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <Button variant="secondary" onClick={() => { stats.reload(); logs.reload() }}>Refresh</Button>
      </div>
      <RuntimeBanner runtime={s.runtime} />
      <ErrorNote>{stats.error || err}</ErrorNote>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {cards.map(([label, value, status]) => (
          <Link key={label} to={status ? `/admin/cases?status=${status}` : '/admin/cases'}
            className="rounded-xl border border-slate-200 bg-white px-4 py-3 hover:border-blue-300">
            <div className="text-xs text-slate-500">{label}</div>
            <div className="mt-1 text-2xl font-semibold">{value ?? 0}</div>
          </Link>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Issue categories"><Bars data={s.by_issue} labels={ISSUE_LABELS} /></Card>
        <Card title="Proposed resolutions"><Bars data={s.by_proposed_action} labels={ACTION_LABELS} /></Card>
        <Card title="Case status"><Bars data={s.by_status} labels={STATUS_LABELS} /></Card>
      </div>

      <Card title="Demo controls" subtitle="Clearly labelled demonstration tools - not part of normal operation">
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <div>
            Simulate data-source outage (Scenario 8): <b className={outage.data?.simulate_outage ? 'text-rose-600' : 'text-emerald-600'}>
              {outage.data?.simulate_outage ? 'OUTAGE ACTIVE' : 'off'}</b>
            <p className="text-xs text-slate-500">While active, every order/policy lookup fails. Cases pause in “Awaiting system recovery” and can be retried.</p>
          </div>
          <Button variant={outage.data?.simulate_outage ? 'success' : 'danger'} onClick={toggle}>
            {outage.data?.simulate_outage ? 'Restore data source' : 'Simulate outage'}
          </Button>
        </div>
      </Card>

      <Card title="Resolution log" subtitle={logs.data ? `Source: ${logs.data.source}` : ''}>
        <ErrorNote>{logs.error}</ErrorNote>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-slate-500"><tr>{['Case', 'Time', 'Order', 'Issues', 'Proposed action', 'Validation', 'Approval'].map((h) => <th key={h} className="py-1.5 pr-3 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {(logs.data?.rows || []).slice(-15).reverse().map((r) => (
                <tr key={r.case_id + r.timestamp} className="border-t border-slate-100">
                  <td className="py-1.5 pr-3 font-mono"><Link className="text-blue-600" to={`/admin/cases/${r.case_id}`}>{r.case_id}</Link></td>
                  <td className="pr-3">{new Date(r.timestamp).toLocaleString()}</td>
                  <td className="pr-3">{r.order_id}</td>
                  <td className="pr-3">{r.issue_categories}</td>
                  <td className="pr-3">{r.proposed_action}</td>
                  <td className="pr-3">{r.validation_status}</td>
                  <td className="pr-3">{r.approval_status}</td>
                </tr>
              ))}
              {!logs.data?.rows?.length && <tr><td colSpan={7} className="py-3 text-slate-400">No finalised cases yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function Bars({ data, labels }) {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...entries.map(([, v]) => v))
  if (!entries.length) return <p className="text-sm text-slate-400">No data yet.</p>
  return (
    <ul className="space-y-2">
      {entries.map(([k, v]) => (
        <li key={k} className="text-xs">
          <div className="flex justify-between"><span className="text-slate-600">{labels[k] || k}</span><span className="font-medium">{v}</span></div>
          <div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${(v / max) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  )
}
