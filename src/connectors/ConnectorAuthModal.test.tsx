import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConnectorAuthModal } from './ConnectorAuthModal'

function renderModal(overrides: Partial<Parameters<typeof ConnectorAuthModal>[0]> = {}) {
  const onSuccess = vi.fn()
  const onClose = vi.fn()
  render(
    <ConnectorAuthModal
      connectorName="佳明中国区"
      onSuccess={onSuccess}
      onClose={onClose}
      mockDelayMs={0}
      {...overrides}
    />,
  )
  return { onSuccess, onClose }
}

describe('ConnectorAuthModal', () => {
  it('renders account / password fields and the 2FA checkbox', () => {
    renderModal()
    expect(screen.getByRole('dialog')).toHaveTextContent('连接 佳明中国区')
    expect(screen.getByLabelText('账号')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByLabelText('启用了 2FA')).toBeInTheDocument()
  })

  it('validates account and password before submitting', async () => {
    const user = userEvent.setup()
    const { onSuccess } = renderModal()

    await user.click(screen.getByTestId('auth-submit'))
    expect(screen.getByRole('alert')).toHaveTextContent('请输入账号')

    await user.type(screen.getByLabelText('账号'), 'alice')
    await user.type(screen.getByLabelText('密码'), '123')
    await user.click(screen.getByTestId('auth-submit'))
    expect(screen.getByRole('alert')).toHaveTextContent('密码至少 4 位')
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('without 2FA: a single login connects', async () => {
    const user = userEvent.setup()
    const { onSuccess } = renderModal()

    await user.type(screen.getByLabelText('账号'), 'alice')
    await user.type(screen.getByLabelText('密码'), 'secret')
    await user.click(screen.getByTestId('auth-submit'))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
  })

  it('with 2FA: credentials → 6-digit code stage (checkbox locked) → connect', async () => {
    const user = userEvent.setup()
    const { onSuccess } = renderModal()

    await user.type(screen.getByLabelText('账号'), 'alice')
    await user.type(screen.getByLabelText('密码'), 'secret')
    await user.click(screen.getByLabelText('启用了 2FA'))
    await user.click(screen.getByTestId('auth-submit'))

    // Second stage appears; the checkbox is locked and creds not yet accepted.
    const codeField = await screen.findByTestId('auth-code-field')
    expect(codeField).toBeInTheDocument()
    expect(screen.getByLabelText('启用了 2FA')).toBeDisabled()
    expect(onSuccess).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('6 位验证码'), '123456')
    await user.click(screen.getByTestId('auth-submit'))
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
  })

  it('with 2FA: rejects a malformed code and a backend-rejected code', async () => {
    const user = userEvent.setup()
    const { onSuccess } = renderModal()

    await user.type(screen.getByLabelText('账号'), 'alice')
    await user.type(screen.getByLabelText('密码'), 'secret')
    await user.click(screen.getByLabelText('启用了 2FA'))
    await user.click(screen.getByTestId('auth-submit'))
    await screen.findByTestId('auth-code-field')

    // Too short → client-side format validation.
    await user.type(screen.getByLabelText('6 位验证码'), '123')
    await user.click(screen.getByTestId('auth-submit'))
    expect(screen.getByRole('alert')).toHaveTextContent('请输入 6 位验证码')

    // Reserved code → mock backend rejection.
    await user.clear(screen.getByLabelText('6 位验证码'))
    await user.type(screen.getByLabelText('6 位验证码'), '000000')
    await user.click(screen.getByTestId('auth-submit'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('验证码有误，请重试'))
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('closes via the backdrop and the cancel button', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(onClose).toHaveBeenCalledTimes(1)

    await user.click(screen.getByTestId('auth-modal-backdrop'))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
