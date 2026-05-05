// Minimal dependency-free hash router.
//
// Routes are encoded in `location.hash` so the app is refresh-safe and its URLs
// are shareable (notably invite links). Recognised shapes:
//
//   #/login                       -> { name: 'login' }
//   #/invite/<token>              -> { name: 'invite', token }
//   #invite=<token>  (legacy)     -> { name: 'invite', token }
//   #/p/<projectId>/<page>        -> { name: 'project', projectId, page }
//   anything else / empty         -> { name: 'home' }

import { useEffect, useState } from 'react'

export const PAGES = [
  'chat',
  'search',
  'documents',
  'connectors',
  'members',
  'health',
]

export function parseHash(rawHash) {
  const hash = rawHash || ''

  // legacy invite form kept working: #invite=<token>
  const legacy = /^#invite=(.+)$/.exec(hash)
  if (legacy) return { name: 'invite', token: decode(legacy[1]) }

  // strip leading '#' and optional leading '/', then split into segments
  const path = hash.replace(/^#\/?/, '')
  const segments = path.split('/').filter(Boolean)

  if (segments.length === 0) return { name: 'home' }

  if (segments[0] === 'login') return { name: 'login' }

  // Health is global (no project); it also has a per-project form under
  // #/p/<id>/health, handled below.
  if (segments[0] === 'health') return { name: 'health' }

  if (segments[0] === 'invite' && segments[1]) {
    return { name: 'invite', token: decode(segments.slice(1).join('/')) }
  }

  if (segments[0] === 'p' && segments[1]) {
    const projectId = decode(segments[1])
    const page = PAGES.includes(segments[2]) ? segments[2] : 'chat'
    return { name: 'project', projectId, page }
  }

  return { name: 'home' }
}

function decode(s) {
  try {
    return decodeURIComponent(s)
  } catch {
    return s
  }
}

export function projectPath(projectId, page = 'chat') {
  return `#/p/${encodeURIComponent(projectId)}/${page}`
}

export function go(path) {
  if (window.location.hash !== path) window.location.hash = path
}

export function useHashRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return [route, go]
}
