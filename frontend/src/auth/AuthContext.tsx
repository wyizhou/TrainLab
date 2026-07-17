import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import * as authApi from './authApi'
import type { AuthUser } from './authApi'
import { AuthContext, demoUser, type AuthStatus } from './AuthState'
import { clearSessionScopedState, SESSION_INVALIDATED_EVENT } from './sessionScope'

export function AuthProvider({ children }: { children: ReactNode }) {
  // The bypass exists only for the checked-in Vite visual test harness. A
  // production build cannot enable it, even if the environment is mis-set.
  const demoMode = import.meta.env.DEV && import.meta.env.VITE_AUTH_MODE === 'demo'
  const [status, setStatus] = useState<AuthStatus>(demoMode ? 'authenticated' : 'loading')
  const [user, setUser] = useState<AuthUser | null>(demoMode ? demoUser : null)
  const subjectId = useRef<string | null>(demoMode ? demoUser.id : null)

  const beginSession = useCallback(
    (nextUser: AuthUser) => {
      if (!demoMode && subjectId.current !== nextUser.id) clearSessionScopedState()
      subjectId.current = nextUser.id
      setUser(nextUser)
      setStatus('authenticated')
    },
    [demoMode],
  )

  const clearSession = useCallback(() => {
    if (!demoMode) clearSessionScopedState()
    subjectId.current = null
    setUser(null)
    setStatus('unauthenticated')
  }, [demoMode])

  useEffect(() => {
    if (demoMode) return
    let active = true
    authApi
      .restoreSession()
      .then((session) => {
        if (!active) return
        beginSession(session.user)
      })
      .catch(() => {
        if (!active) return
        clearSession()
      })
    return () => {
      active = false
    }
  }, [beginSession, clearSession, demoMode])

  useEffect(() => {
    if (demoMode) return
    const invalidate = () => clearSession()
    window.addEventListener(SESSION_INVALIDATED_EVENT, invalidate)
    return () => window.removeEventListener(SESSION_INVALIDATED_EVENT, invalidate)
  }, [clearSession, demoMode])

  const authenticate = useCallback(
    async (username: string, password: string) => {
      if (demoMode) {
        beginSession({ ...demoUser, username, displayName: username })
        return
      }
      const session = await authApi.login(username, password)
      beginSession(session.user)
    },
    [beginSession, demoMode],
  )

  const endSession = useCallback(async () => {
    try {
      if (!demoMode) await authApi.logout()
    } finally {
      clearSession()
    }
  }, [clearSession, demoMode])

  const value = useMemo(
    () => ({ status, user, demoMode, login: authenticate, logout: endSession }),
    [authenticate, demoMode, endSession, status, user],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
