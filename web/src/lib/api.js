// The one place that talks to the backend.
//
// The access token lives in memory only. The refresh token is an httpOnly
// cookie the page can't read, so a reload signs back in through refresh().

const BASE = '/api/v1'

let accessToken = null
let refreshing = null
let onSessionLost = () => {}

export const setSessionLostHandler = (fn) => { onSessionLost = fn }
export const setAccessToken = (token) => { accessToken = token }

export class ApiError extends Error {
  constructor(problem, status) {
    const first = problem.errors?.[0]
    super(
      problem.detail ||
        (first && `${first.field.split('.').pop()}: ${first.message}`) ||
        problem.title ||
        `Request failed (${status})`,
    )
    this.status = status
    this.code = problem.code
    this.fields = problem.errors || []
  }
}

/** Returns true if signed in again, false if the session is really over.
 *  Throws if the server can't be reached, which is a different problem. */
export function refresh() {
  refreshing ||= fetch(`${BASE}/auth/refresh`, { method: 'POST' })
    .then(async (res) => {
      if (!res.ok) {
        accessToken = null
        return false
      }
      accessToken = (await res.json()).access_token
      return true
    })
    .finally(() => { refreshing = null })
  return refreshing
}

async function send(path, init = {}) {
  const attempt = () =>
    fetch(BASE + path, {
      ...init,
      headers: {
        ...init.headers,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  const hadToken = Boolean(accessToken)
  let res = await attempt()
  if (res.status === 401 && hadToken) {
    if (await refresh()) res = await attempt()
    else onSessionLost()
  }
  return res
}

async function fail(res) {
  let problem = {}
  try {
    problem = await res.json()
  } catch {
    // not JSON: a proxy error page, for example
  }
  return new ApiError(problem, res.status)
}

async function request(path, { json, ...init } = {}) {
  if (json !== undefined) {
    init.headers = { 'Content-Type': 'application/json', ...init.headers }
    init.body = JSON.stringify(json)
  }
  const res = await send(path, init)
  if (!res.ok) throw await fail(res)
  return res.status === 204 ? null : res.json()
}

const get = (path, params) => {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  }
  const suffix = query.size ? `?${query}` : ''
  return request(path + suffix)
}
const post = (path, json = {}) => request(path, { method: 'POST', json })
const patch = (path, json) => request(path, { method: 'PATCH', json })
const put = (path, json) => request(path, { method: 'PUT', json })
const del = (path) => request(path, { method: 'DELETE' })

/** POST and call onEvent(name, data) for every server-sent event. */
async function stream(path, body, onEvent, signal) {
  const res = await send(path, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) throw await fail(res)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) return
    buffer += value
    let end
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const name = /^event: (.*)$/m.exec(frame)?.[1]
      const data = /^data: (.*)$/m.exec(frame)?.[1]
      if (name && data) onEvent(name, JSON.parse(data))
    }
  }
}

/** Upload with progress, which fetch can't report. */
function upload(path, form, onProgress) {
  const attempt = () =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', BASE + path)
      if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`)
      xhr.responseType = 'json'
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total)
      xhr.onerror = () => reject(new Error('Connection lost during upload'))
      xhr.onload = () =>
        xhr.status < 300
          ? resolve({ document: xhr.response, duplicate: xhr.status === 200 })
          : reject(new ApiError(xhr.response || {}, xhr.status))

      xhr.send(form)
    })
  return attempt().catch(async (error) => {
    if (error.status !== 401 || !(await refresh())) throw error
    return attempt()
  })
}

async function saveBlob(path, fallbackName) {
  const res = await send(path)
  if (!res.ok) throw await fail(res)
  const name =
    /filename\*?=(?:UTF-8'')?"?([^";]+)/i.exec(res.headers.get('content-disposition') || '')?.[1]
  const url = URL.createObjectURL(await res.blob())
  const link = Object.assign(document.createElement('a'), {
    href: url,
    download: name ? decodeURIComponent(name) : fallbackName,
  })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

const P = (id) => `/projects/${encodeURIComponent(id)}`

export const api = {
  // Instance
  info: () => get('/system/info'),
  ready: async () => {
    // 503 is an answer here: it says what isn't ready.
    const res = await fetch(`${BASE}/health/ready`)
    return res.json()
  },
  status: () => get('/system/status'),
  network: () => get('/system/network'),
  fileTypes: () => get('/system/file-types'),
  setup: (body) => post('/setup', body),

  // Settings
  settings: () => get('/system/settings'),
  saveSettings: (body) => patch('/system/settings', body),
  testSettings: (body) => post('/system/settings/test', body),
  providers: () => get('/system/settings/providers'),
  models: (body) => post('/system/settings/models', body),

  // Session and account
  login: (body) => post('/auth/login', body),
  logout: () => post('/auth/logout'),
  me: () => get('/auth/me'),
  updateMe: (body) => patch('/auth/me', body),
  changePassword: (body) => post('/auth/me/password', body),
  resetPassword: (body) => post('/auth/password-reset', body),

  // Invites
  createInvite: (body) => post('/invites', body),
  resolveInvite: (token) => post('/invites/resolve', { token }),
  acceptInvite: (body) => post('/invites/accept', body),

  // Users
  users: (params) => get('/users', params),
  lookupUsers: (q) => get('/users/lookup', { q }),
  updateUser: (id, body) => patch(`/users/${id}`, body),
  deleteUser: (id) => del(`/users/${id}`),
  userResetLink: (id) => post(`/users/${id}/password-reset`),
  transferOwnership: (id) => post(`/users/${id}/transfer-ownership`),

  // Projects
  projects: (params) => get('/projects', params),
  createProject: (name) => post('/projects', { name }),
  renameProject: (id, name) => patch(P(id), { name }),
  deleteProject: (id) => del(P(id)),

  // Members
  members: (pid, params) => get(`${P(pid)}/members`, params),
  addMember: (pid, body) => post(`${P(pid)}/members`, body),
  setMemberRole: (pid, uid, role) => patch(`${P(pid)}/members/${uid}`, { role }),
  removeMember: (pid, uid) => del(`${P(pid)}/members/${uid}`),

  // Documents
  documents: (pid, params) => get(`${P(pid)}/documents`, params),
  document: (pid, id) => get(`${P(pid)}/documents/${id}`),
  uploadDocument: (pid, file, onProgress) => {
    const form = new FormData()
    form.append('file', file)
    return upload(`${P(pid)}/documents`, form, onProgress)
  },
  updateDocument: (pid, id, body) => patch(`${P(pid)}/documents/${id}`, body),
  deleteDocument: (pid, id) => del(`${P(pid)}/documents/${id}`),
  reindexDocument: (pid, id) => post(`${P(pid)}/documents/${id}/reindex`),
  chunks: (pid, id, params) => get(`${P(pid)}/documents/${id}/chunks`, params),
  downloadDocument: (pid, doc) => saveBlob(`${P(pid)}/documents/${doc.id}/content`, doc.title),
  tags: (pid) => get(`${P(pid)}/tags`),

  // Connectors
  connectorTypes: () => get('/connector-types'),
  connectors: (pid, params) => get(`${P(pid)}/connectors`, params),
  createConnector: (pid, body) => post(`${P(pid)}/connectors`, body),
  updateConnector: (pid, id, body) => patch(`${P(pid)}/connectors/${id}`, body),
  deleteConnector: (pid, id) => del(`${P(pid)}/connectors/${id}`),
  testConnectorDraft: (pid, body) => post(`${P(pid)}/connectors/test`, body),
  testConnector: (pid, id) => post(`${P(pid)}/connectors/${id}/test`),
  syncConnector: (pid, id) => post(`${P(pid)}/connectors/${id}/sync`),

  // Chats
  chats: (pid, params) => get(`${P(pid)}/chats`, params),
  createChat: (pid) => post(`${P(pid)}/chats`),
  updateChat: (pid, id, body) => patch(`${P(pid)}/chats/${id}`, body),
  deleteChat: (pid, id) => del(`${P(pid)}/chats/${id}`),
  exportChat: (pid, chat) =>
    saveBlob(`${P(pid)}/chats/${chat.id}/export?format=md`, `${chat.title || 'chat'}.md`),
  messages: (pid, id, params) => get(`${P(pid)}/chats/${id}/messages`, params),
  sendMessage: (pid, id, body, onEvent, signal) =>
    stream(`${P(pid)}/chats/${id}/messages`, body, onEvent, signal),
  regenerate: (pid, id, messageId, onEvent, signal) =>
    stream(`${P(pid)}/chats/${id}/messages/${messageId}/regenerate`, {}, onEvent, signal),
  setFeedback: (pid, id, messageId, rating) =>
    put(`${P(pid)}/chats/${id}/messages/${messageId}/feedback`, { rating }),
  clearFeedback: (pid, id, messageId) =>
    del(`${P(pid)}/chats/${id}/messages/${messageId}/feedback`),
}
