import type { ReactNode } from 'react'
import { AuthContext, demoUser, type AuthContextValue } from './AuthState'

const testAuth: AuthContextValue = {
  status: 'authenticated',
  user: demoUser,
  demoMode: true,
  login: async () => {},
  logout: async () => {},
}

export function AuthTestProvider({ children }: { children: ReactNode }) {
  return <AuthContext.Provider value={testAuth}>{children}</AuthContext.Provider>
}
