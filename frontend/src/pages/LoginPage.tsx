import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthState'
import { LoginForm } from '../components/LoginForm'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const auth = useAuth()
  const destination =
    typeof location.state === 'object' &&
    location.state !== null &&
    'from' in location.state &&
    typeof location.state.from === 'string'
      ? location.state.from
      : '/'

  useEffect(() => {
    if (!auth.demoMode && auth.status === 'authenticated') navigate(destination, { replace: true })
  }, [auth.demoMode, auth.status, destination, navigate])

  return (
    <LoginForm
      onAuthenticated={async (username, password) => {
        await auth.login(username, password)
        navigate(destination, { replace: true })
      }}
    />
  )
}
