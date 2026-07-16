import { useNavigate } from 'react-router-dom'
import { LoginForm } from '../components/LoginForm'

export function LoginPage() {
  const navigate = useNavigate()
  // Demo flow: a successful login sends the user to the analysis page (C-2).
  return <LoginForm onAuthenticated={() => navigate('/')} />
}
