import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './AuthState'

export function RequireAuth() {
  const auth = useAuth()
  const location = useLocation()
  if (auth.demoMode) return <Outlet />
  if (auth.status === 'loading') {
    return <div role="status" aria-label="正在验证登录" />
  }
  if (auth.status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
