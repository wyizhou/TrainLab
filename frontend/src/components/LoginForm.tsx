import { useCallback, useState, type FormEvent } from 'react'
import './LoginForm.css'

// Demo-only captcha: a 4-digit code shown on screen; the user must retype it.
// No real authentication (contract C-2 explicitly excludes it).
function generateCaptcha(): string {
  return String(Math.floor(1000 + Math.random() * 9000))
}

type LoginFormProps = {
  onAuthenticated: (username: string, password: string) => void | Promise<void>
}

export function LoginForm({ onAuthenticated }: LoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [captcha, setCaptcha] = useState('')
  const [captchaCode, setCaptchaCode] = useState(generateCaptcha)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const refreshCaptcha = useCallback(() => {
    setCaptchaCode(generateCaptcha())
    setCaptcha('')
  }, [])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (username.trim().length <= 6) {
      setError('账号必须大于 6 位')
      return
    }
    if (password.length <= 6) {
      setError('密码必须大于 6 位')
      return
    }
    if (captcha !== captchaCode) {
      setError('验证码错误')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await onAuthenticated(username.trim(), password)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '登录失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login" data-vc="login-page">
      <div className="login__column">
        <div className="login__brand">
          <div className="login__brand-row">
            <span className="login__mark">TL</span>
            <h1 className="login__title">TrainLab</h1>
          </div>
          <p className="login__subtitle">运动数据分析系统 · 原始数据存储 + AI 分析</p>
        </div>

        <form className="login__card" onSubmit={handleSubmit} noValidate data-vc="login-card">
          <h2 className="login__card-title">验证登录</h2>

          <div className="login__field">
            <label htmlFor="login-username">用户名</label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              placeholder="请输入用户名"
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
              placeholder="请输入密码"
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
                placeholder="输入右侧字符"
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

          <button type="submit" className="login__submit" aria-label="登录" disabled={submitting}>
            {submitting ? '登录中…' : '登 录'}
          </button>
          <p className="login__demo">账号和密码均需大于 6 位</p>
        </form>
      </div>
    </div>
  )
}
