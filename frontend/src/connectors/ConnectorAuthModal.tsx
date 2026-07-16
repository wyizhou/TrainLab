import { useId, useState, type FormEvent } from 'react'
import './ConnectorAuthModal.css'

// 连接器·授权登录弹窗 (contract C-11). Mock Garmin authorization (G-mock — no
// real network): account + password, plus an optional 「启用了 2FA」two-stage
// flow. Without 2FA a single 登录 connects. With 2FA the first 登录 validates
// the credentials and reveals a 6-digit code area (the checkbox locks); a
// second 登录 runs the mock backend verification before connecting.

type AuthStage = 'credentials' | 'code'

type ConnectorAuthModalProps = {
  // Connector display name, e.g. 佳明中国区 — shown in the title.
  connectorName: string
  onSuccess: () => void
  onClose: () => void
  // Busy delay for the mock login / verify steps; tests pass a small value.
  mockDelayMs?: number
}

// The mock backend rejects this reserved code to exercise the verification
// (后台验证) failure path; any other 6-digit code is accepted.
const REJECTED_CODE = '000000'

export function ConnectorAuthModal({
  connectorName,
  onSuccess,
  onClose,
  mockDelayMs = 500,
}: ConnectorAuthModalProps) {
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [twoFactor, setTwoFactor] = useState(false)
  const [code, setCode] = useState('')
  const [stage, setStage] = useState<AuthStage>('credentials')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const titleId = useId()

  // Resolve a mock async step, then run `next`. Guards against double-submits.
  const runBusy = (next: () => void) => {
    setBusy(true)
    setTimeout(() => {
      setBusy(false)
      next()
    }, mockDelayMs)
  }

  const submitCredentials = () => {
    if (account.trim() === '') {
      setError('请输入账号')
      return
    }
    if (password.length < 4) {
      setError('密码至少 4 位')
      return
    }
    setError(null)
    runBusy(() => {
      if (twoFactor) {
        // Two-stage: reveal the code area and lock the checkbox.
        setStage('code')
      } else {
        onSuccess()
      }
    })
  }

  const submitCode = () => {
    if (!/^\d{6}$/.test(code)) {
      setError('请输入 6 位验证码')
      return
    }
    setError(null)
    runBusy(() => {
      // Mock backend verification (G-mock).
      if (code === REJECTED_CODE) {
        setError('验证码有误，请重试')
        return
      }
      onSuccess()
    })
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy) return
    if (stage === 'code') {
      submitCode()
    } else {
      submitCredentials()
    }
  }

  return (
    <div
      className="auth-modal__backdrop"
      data-testid="auth-modal-backdrop"
      data-vc="modal-overlay"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="auth-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="auth-modal"
        data-vc="modal-connector-auth"
        data-stage={stage}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="auth-modal__head">
          <h2 id={titleId} className="auth-modal__title">
            连接 {connectorName}
          </h2>
          <p className="auth-modal__subtitle">使用该平台的账号授权，授权后将定时同步数据</p>
        </header>

        <form className="auth-modal__form" onSubmit={handleSubmit} noValidate data-vc="auth-form">
          <div className="auth-modal__field">
            <label htmlFor="auth-account">账号(邮箱 / 手机号)</label>
            <input
              id="auth-account"
              type="text"
              aria-label="账号"
              autoComplete="username"
              placeholder="请输入平台账号"
              value={account}
              disabled={stage === 'code'}
              onChange={(event) => setAccount(event.target.value)}
            />
          </div>

          <div className="auth-modal__field">
            <label htmlFor="auth-password">密码</label>
            <input
              id="auth-password"
              type="password"
              autoComplete="current-password"
              placeholder="请输入平台密码"
              value={password}
              disabled={stage === 'code'}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          <label className="auth-modal__checkbox">
            <input
              type="checkbox"
              aria-label="启用了 2FA"
              checked={twoFactor}
              // Locked once the two-stage flow has advanced to the code stage.
              disabled={stage === 'code'}
              onChange={(event) => setTwoFactor(event.target.checked)}
            />
            该账号启用了两步验证(2FA)
          </label>

          {stage === 'code' && (
            <div
              className="auth-modal__field auth-modal__code-panel"
              data-vc="auth-2fa-panel"
              data-testid="auth-code-field"
            >
              <label htmlFor="auth-code">
                已向你的设备发送验证码，请输入 2FA 验证码后再次点击登录
              </label>
              <input
                id="auth-code"
                className="num"
                type="text"
                aria-label="6 位验证码"
                inputMode="numeric"
                maxLength={6}
                autoFocus
                placeholder="6 位验证码"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </div>
          )}

          {error && (
            <p className="auth-modal__error" role="alert">
              {error}
            </p>
          )}

          <div className="auth-modal__actions">
            <button type="button" className="auth-modal__cancel" onClick={onClose} disabled={busy}>
              取消
            </button>
            <button
              type="submit"
              className="auth-modal__submit"
              data-testid="auth-submit"
              disabled={busy}
              aria-busy={busy}
            >
              {busy && <span className="auth-modal__spinner" aria-hidden="true" />}
              {busy ? '验证中…' : stage === 'code' ? '登 录(提交验证码)' : '登 录'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
