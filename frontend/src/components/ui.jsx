export const STATUS_STYLES = {
  received: 'bg-slate-100 text-slate-700',
  investigating: 'bg-sky-50 text-sky-700',
  awaiting_customer: 'bg-amber-50 text-amber-700',
  info_requested: 'bg-amber-50 text-amber-700',
  pending_approval: 'bg-indigo-50 text-indigo-700',
  awaiting_system_recovery: 'bg-rose-50 text-rose-700',
  approved: 'bg-emerald-50 text-emerald-700',
  rejected: 'bg-rose-50 text-rose-700',
}

export const STATUS_LABELS = {
  received: 'Received',
  investigating: 'Investigating',
  awaiting_customer: 'Awaiting customer',
  info_requested: 'More info requested',
  pending_approval: 'Pending approval',
  awaiting_system_recovery: 'Awaiting system recovery',
  approved: 'Approved',
  rejected: 'Rejected',
}

export const ISSUE_LABELS = {
  not_delivered: 'Not arrived', late_delivery: 'Late delivery', damaged_item: 'Damaged',
  wrong_item: 'Wrong item', return_request: 'Return', refund_request: 'Refund',
  cancellation: 'Cancellation', other: 'Other',
}

export function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[status] || 'bg-slate-100 text-slate-700'}`}>
      {STATUS_LABELS[status] || status}
    </span>
  )
}

export function Pill({ children, tone = 'slate' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700', blue: 'bg-blue-50 text-blue-700', red: 'bg-rose-50 text-rose-700',
    green: 'bg-emerald-50 text-emerald-700', amber: 'bg-amber-50 text-amber-800',
  }
  return <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>
}

export function Card({ title, subtitle, children, right, className = '' }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

export function Spinner({ label }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600" />
      {label}
    </span>
  )
}

export function ErrorNote({ children }) {
  if (!children) return null
  return <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{children}</div>
}

export function Button({ variant = 'primary', className = '', ...props }) {
  const v = {
    primary: 'bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-300',
    secondary: 'border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400',
    danger: 'bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300',
    success: 'bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300',
  }
  return <button className={`rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${v[variant]} ${className}`} {...props} />
}

export function RuntimeBanner({ runtime }) {
  if (!runtime) return null
  const demo = runtime.demo_mode
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg px-3 py-2 text-xs ${demo ? 'border border-amber-200 bg-amber-50 text-amber-900' : 'border border-emerald-200 bg-emerald-50 text-emerald-900'}`}>
      {demo && <span className="font-semibold">DEMO MODE</span>}
      <span><b>Planner:</b> {runtime.planner_label}</span>
      <span><b>Data:</b> {runtime.data_source_label}</span>
      {runtime.email_label && <span><b>Email:</b> {runtime.email_label}</span>}
    </div>
  )
}

export function KeyValue({ rows }) {
  return (
    <dl className="grid grid-cols-[minmax(70px,max-content)_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
      {rows.filter(Boolean).map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="text-slate-900 [overflow-wrap:anywhere]">{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : '')
export const money = (x) => `$${Number(x || 0).toFixed(2)}`
