import { Fragment, useState } from 'react'
import { api } from '../services/api.js'
import { useAsync } from '../hooks/useAsync.js'
import { Button, Card, ErrorNote, ISSUE_LABELS, Pill, Spinner, fmtTime } from '../components/ui.jsx'

export default function AdminComparison() {
  const { data, error, loading, setData } = useAsync(() => api.comparison(), [])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [open, setOpen] = useState(null)

  const run = async () => {
    setBusy(true)
    setErr(null)
    try { setData(await api.runComparison()) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Agent vs Traditional Workflow</h1>
          <p className="text-sm text-slate-500">Both systems run live on the same scenarios, the same order data and the same policy thresholds.</p>
        </div>
        <Button onClick={run} disabled={busy}>{busy ? 'Running scenarios…' : 'Run comparison now'}</Button>
      </div>
      <ErrorNote>{error || err}</ErrorNote>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Traditional fixed workflow">
          <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700">
            <li>Keyword menu picks <b>one</b> category (fixed priority order).</li>
            <li>Requires order ID, looks up the order, runs that category's fixed branch.</li>
            <li>Each branch has a predetermined list of checks - nothing more.</li>
            <li>Cannot decide that another tool or more information is needed.</li>
          </ul>
        </Card>
        <Card title="ResolveAI agentic workflow">
          <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700">
            <li>Understands natural language and keeps <b>every</b> issue in the case.</li>
            <li>Chooses the next tool from the evidence gathered so far.</li>
            <li>Asks only for information that is genuinely missing, then resumes.</li>
            <li>Independent validation and human approval before anything is final.</li>
          </ul>
        </Card>
      </div>

      {loading && !data ? <Spinner label="Loading…" /> : !data?.results?.length ? (
        <Card><p className="text-sm text-slate-500">No comparison has been run yet. Click “Run comparison now”.</p></Card>
      ) : (
        <Card title="Results" subtitle={`Last run ${fmtTime(data.created_at)} · agent planner: ${data.planner}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>{['Scenario', 'Traditional workflow behaviour', 'ResolveAI behaviour', 'Main difference', 'Result'].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {data.results.map((r) => (
                  <Fragment key={r.scenario_id}>
                    <tr className="cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50" onClick={() => setOpen(open === r.scenario_id ? null : r.scenario_id)}>
                      <td className="py-2 pr-3"><b>{r.scenario_id}</b> {r.scenario}<div className="mt-1 flex flex-wrap gap-1">{r.expected_issues.map((i) => <Pill key={i}>{ISSUE_LABELS[i]}</Pill>)}</div></td>
                      <td className="pr-3 text-xs text-slate-700">{r.traditional.behavior}</td>
                      <td className="pr-3 text-xs text-slate-700">{r.agent.behavior}</td>
                      <td className="pr-3 text-xs text-slate-700">{r.main_difference}</td>
                      <td className="pr-3"><Pill tone={r.result.startsWith('Agent better') ? 'green' : 'slate'}>{r.result}</Pill></td>
                    </tr>
                    {open === r.scenario_id && (
                      <tr className="bg-slate-50">
                        <td colSpan={5} className="px-3 py-3">
                          <div className="grid gap-4 md:grid-cols-2">
                            <Transcript title="Traditional transcript" turns={r.traditional.transcript} />
                            <Transcript title="ResolveAI transcript" turns={r.agent.transcript} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">Click a row to see both transcripts. Results are computed from the live runs, not hard-coded.</p>
        </Card>
      )}
    </div>
  )
}

function Transcript({ title, turns }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-slate-500">{title}</div>
      <ul className="space-y-1 text-xs">
        {turns.map((t, i) => <li key={i} className={t.role === 'customer' ? 'text-blue-700' : 'text-slate-800'}><b>{t.role}:</b> {t.content}</li>)}
      </ul>
    </div>
  )
}
