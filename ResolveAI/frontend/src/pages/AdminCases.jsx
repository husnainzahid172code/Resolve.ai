import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { Button, Card, ErrorNote, ISSUE_LABELS, Pill, Spinner, STATUS_LABELS, StatusBadge, fmtTime } from '../components/ui.jsx'

export default function AdminCases() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') || ''
  const issue = params.get('issue') || ''
  const { data, error, loading, reload } = useAsync(() => api.cases({ status, issue }), [status, issue])
  const set = (k, v) => {
    const p = new URLSearchParams(params)
    v ? p.set(k, v) : p.delete(k)
    setParams(p)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Cases</h1>
        <div className="flex flex-wrap gap-2">
          <select className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm" value={status} onChange={(e) => set('status', e.target.value)}>
            <option value="">All statuses</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm" value={issue} onChange={(e) => set('issue', e.target.value)}>
            <option value="">All issues</option>
            {Object.entries(ISSUE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <Button variant="secondary" onClick={reload}>Refresh</Button>
        </div>
      </div>
      <ErrorNote>{error}</ErrorNote>
      <Card>
        {loading && !data ? <Spinner label="Loading cases…" /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>{['Case', 'Status', 'Customer message', 'Orders', 'Issues', 'Proposed', 'Validation', 'Risk flags', 'Updated'].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {(data || []).map((c) => (
                  <tr key={c.case_id} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3 font-mono text-xs"><Link className="text-blue-600 hover:underline" to={`/admin/cases/${c.case_id}`}>{c.case_id}</Link></td>
                    <td className="pr-3"><StatusBadge status={c.status} /></td>
                    <td className="max-w-xs pr-3 text-slate-600"><span className="line-clamp-2">{c.first_message}</span></td>
                    <td className="pr-3 text-xs">{c.order_ids.join(', ') || '—'}</td>
                    <td className="pr-3"><div className="flex flex-wrap gap-1">{c.issues.map((i) => <Pill key={i} tone="blue">{ISSUE_LABELS[i] || i}</Pill>)}</div></td>
                    <td className="pr-3 text-xs">{c.proposed_actions.join(', ') || '—'}</td>
                    <td className="pr-3 text-xs">{c.validation_status || '—'}</td>
                    <td className="pr-3"><div className="flex flex-wrap gap-1">{c.risk_flags.map((f) => <Pill key={f} tone="red">{f}</Pill>)}</div></td>
                    <td className="whitespace-nowrap text-xs text-slate-500">{fmtTime(c.updated_at)}</td>
                  </tr>
                ))}
                {!data?.length && <tr><td colSpan={9} className="py-6 text-center text-slate-400">No cases match these filters.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
