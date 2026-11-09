import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'

const links = [
  { to: '/admin', label: 'Overview', end: true },
  { to: '/admin/cases', label: 'Cases' },
  { to: '/admin/comparison', label: 'Agent vs Traditional' },
]

export default function AdminLayout() {
  const { logout, user } = useAuth()
  const nav = useNavigate()
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="px-5 py-5">
          <div className="text-lg font-semibold text-slate-900">Resolve<span className="text-blue-600">AI</span></div>
          <div className="text-xs text-slate-500">Administrator console</div>
        </div>
        <nav className="flex flex-col gap-0.5 px-3">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end}
              className={({ isActive }) => `rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-600 hover:bg-slate-50'}`}>
              {l.label}
            </NavLink>
          ))}
          <a href="/" target="_blank" rel="noreferrer" className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">Customer chat ↗</a>
        </nav>
        <div className="mt-auto border-t border-slate-100 px-5 py-4 text-xs text-slate-500">
          Signed in as <b className="text-slate-700">{user}</b>
          <button className="mt-2 block text-blue-600 hover:underline" onClick={() => { logout(); nav('/admin/login') }}>Sign out</button>
        </div>
      </aside>
      <div className="flex-1">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
          <span className="font-semibold">Resolve<span className="text-blue-600">AI</span> Admin</span>
          <div className="flex gap-3 text-sm">
            {links.map((l) => <NavLink key={l.to} to={l.to} end={l.end} className="text-slate-600">{l.label.split(' ')[0]}</NavLink>)}
          </div>
        </div>
        <main className="mx-auto max-w-6xl px-4 py-6 md:px-8"><Outlet /></main>
      </div>
    </div>
  )
}
