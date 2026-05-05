// Server-Sent Events reader for POST /api/answer.
//
// The backend streams `event: <type>\n data: <json>\n\n` frames. We read the
// response body as a stream (EventSource can't POST), split on the blank-line
// frame boundary, and dispatch. Event types: sources, token, done, error.
//
// Adapted from the reference web app's SSE handler.

import { getToken } from './api.js'

export async function streamAnswer(projectId, query, k, callbacks, signal) {
  const { onSources, onToken, onDone, onError } = callbacks
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let res
  try {
    res = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/answer`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({ query, k }),
        signal,
      },
    )
  } catch (err) {
    if (err.name !== 'AbortError') onError(err.message)
    return
  }

  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body && body.detail) detail = body.detail
    } catch {
      /* ignore */
    }
    onError(detail)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handleFrame = (frame) => {
    let type = ''
    const dataLines = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) type = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    }
    if (!type || dataLines.length === 0) return
    let data
    try {
      data = JSON.parse(dataLines.join('\n'))
    } catch {
      return
    }
    if (type === 'sources') onSources(data)
    else if (type === 'token') onToken(data)
    else if (type === 'done') onDone(data)
    else if (type === 'error') onError((data && data.message) || 'stream error')
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let i
      while ((i = buffer.indexOf('\n\n')) >= 0) {
        handleFrame(buffer.slice(0, i))
        buffer = buffer.slice(i + 2)
      }
    }
    if (buffer.trim()) handleFrame(buffer)
  } catch (err) {
    if (err.name !== 'AbortError') onError(err.message)
  }
}
