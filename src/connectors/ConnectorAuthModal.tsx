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
          <button type="button" className="auth-modal__close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>

        <form className="auth-modal__form" onSubmit={handleSubmit} noValidate>
          <div className="auth-modal__field">
            <label htmlFor="auth-account">账号</label>
            <input
              id="auth-account"
              type="text"
              autoComplete="username"
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
              value={password}
              disabled={stage === 'code'}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          <label className="auth-modal__checkbox">
            <input
              type="checkbox"
              checked={twoFactor}
              // Locked once the two-stage flow has advanced to the code stage.
              disabled={stage === 'code'}
              onChange={(event) => setTwoFactor(event.target.checked)}
            />
            启用了 2FA
          </label>

          {stage === 'code' && (
            <div className="auth-modal__field" data-testid="auth-code-field">
              <label htmlFor="auth-code">6 位验证码</label>
              <input
                id="auth-code"
                className="num"
                type="text"
                inputMode="numeric"
                maxLength={6}
                autoFocus
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

          <button
            type="submit"
            className="auth-modal__submit"
            data-testid="auth-submit"
            disabled={busy}
            aria-busy={busy}
          >
            {busy && <span className="auth-modal__spinner" aria-hidden="true" />}
            {busy ? '登录中…' : '登录'}
          </button>
        </form>
      </div>
    </div>
  )
}
