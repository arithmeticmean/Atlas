// Routes live in the URL hash, so reloads and shared links work without any
// server rewrite rules. The backend's invite and reset links use this form.

import { useEffect, useState } from 'react'

export function parseRoute(hash) {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(safeDecode)
  const [head, a, b, c] = parts
  if (['login', 'setup', 'account', 'onboarding'].includes(head)) return { name: head }
  if (head === 'join' && a) return { name: 'join', token: parts.slice(1).join('/') }
  if (head === 'reset' && a) return { name: 'reset', token: parts.slice(1).join('/') }
  if (head === 'admin') return { name: 'admin', page: a || 'ai' }
  if (head === 'p' && a) return { name: 'project', projectId: a, page: b || 'chat', chatId: c || null }
  return { name: 'home' }
}

function safeDecode(part) {
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

export const projectHref = (id, page = 'chat', chatId) =>
  `#/p/${encodeURIComponent(id)}/${page}${chatId ? `/${encodeURIComponent(chatId)}` : ''}`

export function navigate(href, { replace = false } = {}) {
  if (window.location.hash === href) return
  window.history[replace ? 'replaceState' : 'pushState'](null, '', href)
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return route
}
