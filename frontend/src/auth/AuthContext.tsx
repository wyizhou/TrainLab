import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import * as authApi from './authApi'
import type { AuthUser } from './authApi'
import { AuthContext, demoUser, type AuthStatus } from './AuthState'

export function AuthProvider({ children }: { children: ReactNode }) {
  // The bypass exists only for the checked-in Vite visual test harness. A
  // production build cannot enable it, even if the environment is mis-set.
  const demoMode = import.meta.env.DEV && import.meta.env.VITE_AUTH_MODE === 'demo'
  const [status, setStatus] = useState<AuthStatus>(demoMode ? 'authenticated' : 'loading')
  const [user, setUser] = useState<AuthUser | null>(demoMode ? demoUser : null)

  useEffect(() => {
    if (demoMode) return
    let active = true
    authApi
      .restoreSession()
      .then((session) => {
        if (!active) return
        setUser(session.user)
        setStatus('authenticated')
      })
      .catch(() => {
        if (!active) return
        setUser(null)
        setStatus('unauthenticated')
      })
    return () => {
      active = false
    }
  }, [demoMode])

  const authenticate = useCallback(
    async (username: string, password: string) => {
      if (demoMode) {
        setUser({ ...demoUser, username, displayName: username })
        setStatus('authenticated')
        return
      }
      const session = await authApi.login(username, password)
      setUser(session.user)
      setStatus('authenticated')
    },
    [demoMode],
  )

  const endSession = useCallback(async () => {
    try {
      if (!demoMode) await authApi.logout()
    } finally {
      setUser(null)
      setStatus('unauthenticated')
    }
  }, [demoMode])

  const value = useMemo(
    () => ({ status, user, demoMode, login: authenticate, logout: endSession }),
    [authenticate, demoMode, endSession, status, user],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
