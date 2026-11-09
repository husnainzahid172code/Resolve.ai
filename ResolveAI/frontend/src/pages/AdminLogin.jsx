import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'
import { Button, ErrorNote } from '../components/ui.jsx'

export default function AdminLogin() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [u, setU] = useState('admin')
  const [p, setP] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await login(u, p)
      nav('/admin')
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-6">
        <div>
          <div className="text-xl font-semibold">Resolve<span className="text-blue-600">AI</span></div>
          <p className="text-sm text-slate-500">Administrator sign in</p>
        </div>
        <label className="block text-sm">Username
          <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" value={u} onChange={(e) => setU(e.target.value)} />
        </label>
        <label className="block text-sm">Password
          <input type="password" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" value={p} onChange={(e) => setP(e.target.value)} />
        </label>
        <ErrorNote>{err}</ErrorNote>
        <Button className="w-full" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
      </form>
    </div>
  )
}
