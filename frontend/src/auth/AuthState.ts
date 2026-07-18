import { createContext, useContext } from 'react'
import type { AuthUser } from './authApi'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export type AuthContextValue = {
  status: AuthStatus
  user: AuthUser | null
  demoMode: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

export const demoUser: AuthUser = {
  id: 'demo-user',
  username: 'audit-user',
  displayName: 'audit-user',
  isOwner: true,
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function useAuth(): AuthContextValue {
  const auth = useContext(AuthContext)
  if (auth === undefined) throw new Error('useAuth must be used inside AuthProvider')
  return auth
}

export function useOptionalAuth(): AuthContextValue | undefined {
  return useContext(AuthContext)
}
