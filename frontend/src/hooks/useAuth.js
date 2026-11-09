import { useCallback, useState } from 'react'
import { api, tokenStore } from '../services/api.js'

export function useAuth() {
  const [token, setToken] = useState(tokenStore.get())
  const login = useCallback(async (u, p) => {
    const r = await api.login(u, p)
    tokenStore.set(r.token)
    sessionStorage.setItem('resolveai_admin_user', r.username)
    setToken(r.token)
  }, [])
  const logout = useCallback(() => {
    tokenStore.clear()
    setToken(null)
  }, [])
  return { token, login, logout, user: sessionStorage.getItem('resolveai_admin_user') }
}
