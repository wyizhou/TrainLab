import { useCallback, useState, type FormEvent } from 'react'
import './LoginForm.css'

// Demo-only captcha: a 4-digit code shown on screen; the user must retype it.
// No real authentication (contract C-2 explicitly excludes it).
function generateCaptcha(): string {
  return String(Math.floor(1000 + Math.random() * 9000))
}

type LoginFormProps = {
  onAuthenticated: () => void
}

export function LoginForm({ onAuthenticated }: LoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [captcha, setCaptcha] = useState('')
  const [captchaCode, setCaptchaCode] = useState(generateCaptcha)
  const [error, setError] = useState<string | null>(null)

  const refreshCaptcha = useCallback(() => {
    setCaptchaCode(generateCaptcha())
    setCaptcha('')
  }, [])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    // Demo validation: any non-empty username, password >= 4 chars, matching captcha.
    if (username.trim() === '') {
      setError('请输入用户名')
      return
    }
    if (password.length < 4) {
      setError('密码至少 4 位')
      return
    }
    if (captcha !== captchaCode) {
      setError('验证码错误')
      return
    }
    setError(null)
    onAuthenticated()
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={handleSubmit} noValidate>
        <h1 className="login__title">TrainLab</h1>

        <div className="login__field">
          <label htmlFor="login-username">用户名</label>
          <input
            id="login-username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>

        <div className="login__field">
          <label htmlFor="login-password">密码</label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        <div className="login__field">
          <label htmlFor="login-captcha">验证码</label>
          <div className="login__captcha-row">
            <input
              id="login-captcha"
              className="num"
              type="text"
              inputMode="numeric"
              maxLength={4}
              value={captcha}
              onChange={(event) => setCaptcha(event.target.value)}
            />
            <button
              type="button"
              className="login__captcha num"
              onClick={refreshCaptcha}
              aria-label="点击刷新验证码"
              data-testid="captcha-code"
            >
              {captchaCode}
            </button>
          </div>
        </div>

        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="login__submit">
          登录
        </button>
      </form>
    </div>
  )
}
