// Thin API client. The admin token lives in sessionStorage; no secrets ever reach the browser.
const TOKEN_KEY = 'resolveai_admin_token'
const API_BASE_URL = 'https://resolveai-production-e31d.up.railway.app'

export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

async function request(path, { method = 'GET', body, admin = false, headers = {}, raw = false } = {}) {
  const h = { ...headers }
  if (body && !(body instanceof FormData)) h['Content-Type'] = 'application/json'
  if (admin && tokenStore.get()) h.Authorization = `Bearer ${tokenStore.get()}`
  let res
  try {
    res = await fetch(`${API_BASE_URL}/api${path}`, { method, headers: h, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined })
  } catch {
    throw new Error('Cannot reach the ResolveAI server. Is the backend running?')
  }
  if (res.status === 401 && admin) {
    tokenStore.clear()
    window.location.href = '/admin/login'
    throw new Error('Session expired')
  }
  if (raw) return res
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join('; ') : data.detail
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return data
}

const idem = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random())

export const api = {
  health: () => request('/health'),
  login: (username, password) => request('/auth/login', { method: 'POST', body: { username, password } }),
  // customer
  startComplaint: (message) => request('/complaints', { method: 'POST', body: { message } }),
  sendMessage: (caseId, message) => request(`/cases/${caseId}/messages`, { method: 'POST', body: { message } }),
  uploadEvidence: (caseId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request(`/cases/${caseId}/evidence`, { method: 'POST', body: fd })
  },
  getCustomerCase: (caseId) => request(`/cases/${caseId}`),
  // admin
  stats: () => request('/dashboard/stats', { admin: true }),
  cases: (params = {}) => request(`/cases?${new URLSearchParams(Object.entries(params).filter(([, v]) => v))}`, { admin: true }),
  caseDetail: (caseId) => request(`/cases/${caseId}`, { admin: true }),
  approve: (caseId, body) => request(`/cases/${caseId}/approve`, { method: 'POST', body, admin: true, headers: { 'Idempotency-Key': idem() } }),
  reject: (caseId, body) => request(`/cases/${caseId}/reject`, { method: 'POST', body, admin: true, headers: { 'Idempotency-Key': idem() } }),
  requestInfo: (caseId, body) => request(`/cases/${caseId}/request-information`, { method: 'POST', body, admin: true, headers: { 'Idempotency-Key': idem() } }),
  resendEmail: (caseId) => request(`/cases/${caseId}/resend-email`, { method: 'POST', admin: true }),
  retry: (caseId) => request(`/cases/${caseId}/retry`, { method: 'POST', admin: true }),
  evidenceBlob: async (caseId, id) => {
    const res = await request(`/cases/${caseId}/evidence/${id}`, { admin: true, raw: true })
    return URL.createObjectURL(await res.blob())
  },
  logs: () => request('/resolution-logs', { admin: true }),
  outage: () => request('/admin/demo/outage', { admin: true }),
  setOutage: (enabled) => request(`/admin/demo/outage?enabled=${enabled}`, { method: 'POST', admin: true }),
  runComparison: () => request('/comparison/run', { method: 'POST', admin: true }),
  comparison: () => request('/comparison/results', { admin: true }),
}
