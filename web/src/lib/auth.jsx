import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, refresh, setAccessToken, setSessionLostHandler } from './api.js'

const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

// status: loading | offline | setup | signed-out | signed-in
export function AuthProvider({ children }) {
  const [status, setStatus] = useState('loading')
  const [user, setUser] = useState(null)

  const boot = useCallback(async () => {
    setStatus('loading')
    try {
      localStorage.removeItem('atlas.token') // from the previous UI
    } catch {
      // storage can be blocked; nothing depends on it
    }
    try {
      const info = await api.info()
      if (info.needs_setup) return setStatus('setup')
      if (!(await refresh())) return setStatus('signed-out')
      setUser(await api.me())
      setStatus('signed-in')
    } catch (error) {
      setStatus(error.status === 401 ? 'signed-out' : 'offline')
    }
    return undefined
  }, [])

  useEffect(() => {
    setSessionLostHandler(() => {
      setAccessToken(null)
      setUser(null)
      setStatus('signed-out')
    })
    boot()
  }, [boot])

  const value = useMemo(
    () => ({
      status,
      user,
      setUser,
      retry: boot,
      isInstanceAdmin: user?.role === 'owner' || user?.role === 'admin',
      /** After login, setup or accepting an invite. */
      startSession(session) {
        setAccessToken(session.access_token)
        setUser(session.user)
        setStatus('signed-in')
      },
      async signOut() {
        try {
          await api.logout()
        } catch {
          // signed out locally either way
        }
        setAccessToken(null)
        setUser(null)
        setStatus('signed-out')
        window.location.hash = '#/login'
      },
    }),
    [status, user, boot],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
