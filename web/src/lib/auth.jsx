// Authentication context: the single source of truth for "who is signed in".
//
// Core rule (this is what fixes the old broken gate): a token's mere presence
// never grants access. On load we VERIFY it against GET /auth/me; only a
// successful verification flips status to 'authed'. Any failure clears the
// token and drops to 'anon', so a stale/legacy/expired token can never sneak
// past the login screen.

import { createContext, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken, setUnauthorizedHandler } from './api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // 'checking' -> we hold a token and are verifying it
  // 'authed'   -> verified; `user` is populated
  // 'anon'     -> no valid session; show the login/invite screen
  const [status, setStatus] = useState(() =>
    getToken() ? 'checking' : 'anon',
  )
  const [user, setUser] = useState(null)

  const signOut = () => {
    setToken('')
    setUser(null)
    setStatus('anon')
  }

  // Verify the current token by loading the identity it claims.
  const loadMe = async () => {
    const me = await api.me()
    setUser(me)
    setStatus('authed')
    return me
  }

  useEffect(() => {
    // Any 401 from any request means the session is gone -> reset to login.
    setUnauthorizedHandler(signOut)

    let alive = true
    if (getToken()) {
      loadMe().catch(() => {
        if (alive) signOut() // invalid/stale/expired token: clear and show login
      })
    }
    return () => {
      alive = false
      setUnauthorizedHandler(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const signIn = async (email, password) => {
    const res = await api.login(email, password)
    setToken(res.access_token)
    await loadMe()
  }

  const redeemInvite = async (inviteToken, body) => {
    const res = await api.signup(inviteToken, body)
    setToken(res.access_token)
    await loadMe()
  }

  const value = { status, user, signIn, redeemInvite, signOut }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
