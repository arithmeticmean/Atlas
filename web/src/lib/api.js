// Thin fetch wrapper around the Atlas backend (all routes under /api).
//
// Everything except auth + health is scoped to a project:
//   /api/projects/{projectId}/{documents,connectors,search,answer}
// The access token (from login/signup) is kept in localStorage and sent as a
// Bearer header on every request.

const BASE = '/api'
const TOKEN_KEY = 'atlas.token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

// A single global hook the auth layer registers, so an expired/invalid token
// seen by ANY request drops the user back to the login screen instead of
// leaving a half-broken page. Set via setUnauthorizedHandler (see lib/auth).
let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

// FastAPI errors put a human string in `detail` for our own HTTPExceptions,
// but a *list* of {loc,msg,type} objects for 422 request-validation failures.
// Turn either shape into a readable message (never "[object Object]").
function formatDetail(detail, fallback) {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === 'object' ? d.msg : String(d)))
      .filter(Boolean)
    return msgs.length ? msgs.join('; ') : fallback
  }
  return typeof detail === 'object' ? JSON.stringify(detail) : String(detail)
}

function authHeaders(extra) {
  const headers = { ...(extra || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

async function req(path, options = {}) {
  const { headers, json, ...rest } = options
  const init = { ...rest, headers: authHeaders(headers) }
  if (json !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(json)
  }
  const res = await fetch(BASE + path, init)
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = formatDetail(body?.detail, detail)
    } catch {
      /* non-JSON error body */
    }
    // 401 anywhere means the session is gone (expired/forged/wrong secret);
    // let the auth layer reset to the login screen.
    if (res.status === 401 && onUnauthorized) onUnauthorized()
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}

const P = (projectId) => `/projects/${encodeURIComponent(projectId)}`

export const api = {
  // --- health / status (global) ---
  ready: () => req('/health/ready'),
  status: () => req('/status'),
  network: () => req('/network'),

  // --- auth ---
  login: (email, password) =>
    req('/auth/login', { method: 'POST', json: { email, password } }),
  signup: (inviteToken, body) =>
    req(`/auth/signup/${encodeURIComponent(inviteToken)}`, {
      method: 'POST',
      json: body,
    }),
  me: () => req('/auth/me'),

  // --- user directory (scoped server-side to what the caller may see) ---
  listUsers: () => req('/users'),

  // --- projects ---
  listProjects: () => req('/projects'),
  createProject: (name) => req('/projects', { method: 'POST', json: { name } }),
  getProject: (id) => req(`/projects/${encodeURIComponent(id)}`),
  deleteProject: (id) =>
    req(`/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // --- members ---
  listMembers: (pid) => req(`${P(pid)}/members`),
  addMember: (pid, email, role) =>
    req(`${P(pid)}/members`, { method: 'POST', json: { email, role } }),
  removeMember: (pid, userId) =>
    req(`${P(pid)}/members/${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    }),
  createInvite: (pid, role) =>
    req(`${P(pid)}/invites`, { method: 'POST', json: { role } }),

  // --- search (project-scoped) ---
  search: (pid, query, k = 5) =>
    req(`${P(pid)}/search`, { method: 'POST', json: { query, k } }),

  // --- documents (project-scoped) ---
  listDocuments: (pid) => req(`${P(pid)}/documents`),
  getDocument: (pid, id) => req(`${P(pid)}/documents/${id}`),
  reingest: (pid, id) =>
    req(`${P(pid)}/documents/${id}/ingest`, { method: 'POST' }),
  uploadDocument: (pid, file) => {
    const form = new FormData()
    form.append('file', file)
    return req(`${P(pid)}/documents`, { method: 'POST', body: form })
  },

  // --- connectors (project-scoped, moderators only) ---
  listConnectors: (pid) => req(`${P(pid)}/connectors`),
  createConnector: (pid, body) =>
    req(`${P(pid)}/connectors`, { method: 'POST', json: body }),
  updateConnector: (pid, id, body) =>
    req(`${P(pid)}/connectors/${id}`, { method: 'PATCH', json: body }),
  deleteConnector: (pid, id) =>
    req(`${P(pid)}/connectors/${id}`, { method: 'DELETE' }),
  connectorHealth: (pid, id) => req(`${P(pid)}/connectors/${id}/health`),
  syncConnector: (pid, id) =>
    req(`${P(pid)}/connectors/${id}/sync`, { method: 'POST' }),
}
