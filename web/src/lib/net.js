// Helpers for "how do other devices reach this Atlas instance".
//
// The server already listens on 0.0.0.0, so reachability is really a URL
// question: whatever address the current user opened Atlas with is the address
// that works. We build shareable links from window.location so a link is
// correct exactly when the owner is browsing via the machine's LAN IP/hostname
// (not localhost). We deliberately don't ask the server for its IP -- inside
// Docker it only sees its bridge address (172.x), which would mislead.

export function appOrigin() {
  return window.location.origin
}

// True when Atlas is being viewed on this machine only (loopback), so any link
// built from the current origin won't work from another device.
export function isLoopbackHost() {
  const h = window.location.hostname
  return (
    h === 'localhost' ||
    h === '127.0.0.1' ||
    h === '0.0.0.0' ||
    h === '::1' ||
    h === '[::1]' ||
    h.endsWith('.localhost')
  )
}

// A full, openable invite URL for the current origin, e.g.
//   http://192.168.1.42:8000/#/invite/<token>
export function inviteLink(token) {
  return `${appOrigin()}/#/invite/${encodeURIComponent(token)}`
}
