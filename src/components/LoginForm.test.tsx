import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, vi } from 'vitest'
import { LoginForm } from './LoginForm'

afterEach(() => {
  vi.restoreAllMocks()
})

async function fillValidCredentials(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('用户名'), 'alice')
  await user.type(screen.getByLabelText('密码'), 'secret')
  const code = screen.getByTestId('captcha-code').textContent ?? ''
  await user.type(screen.getByLabelText('验证码'), code)
  return code
}

describe('LoginForm', () => {
  it('renders the three fields, refreshable captcha and submit — no marketing copy', () => {
    render(<LoginForm onAuthenticated={() => {}} />)
    expect(screen.getByLabelText('用户名')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByLabelText('验证码')).toBeInTheDocument()
    expect(screen.getByTestId('captcha-code')).toHaveTextContent(/^\d{4}$/)
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('refreshes the captcha code when the code chip is clicked', async () => {
    const user = userEvent.setup()
    const randomSpy = vi.spyOn(Math, 'random').mockReturnValueOnce(0) // initial -> 1000
    render(<LoginForm onAuthenticated={() => {}} />)
    expect(screen.getByTestId('captcha-code')).toHaveTextContent('1000')

    randomSpy.mockReturnValueOnce(0.5) // refresh -> 1000 + 4500 = 5500
    await user.click(screen.getByTestId('captcha-code'))
    expect(screen.getByTestId('captcha-code')).toHaveTextContent('5500')
  })

  it('rejects an empty username without authenticating', async () => {
    const user = userEvent.setup()
    const onAuthenticated = vi.fn()
    render(<LoginForm onAuthenticated={onAuthenticated} />)
    await user.click(screen.getByRole('button', { name: '登录' }))
    expect(screen.getByRole('alert')).toHaveTextContent('请输入用户名')
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('rejects a password shorter than 4 characters', async () => {
    const user = userEvent.setup()
    const onAuthenticated = vi.fn()
    render(<LoginForm onAuthenticated={onAuthenticated} />)
    await user.type(screen.getByLabelText('用户名'), 'alice')
    await user.type(screen.getByLabelText('密码'), 'abc')
    await user.click(screen.getByRole('button', { name: '登录' }))
    expect(screen.getByRole('alert')).toHaveTextContent('密码至少 4 位')
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('rejects a wrong captcha and stays on the form', async () => {
    const user = userEvent.setup()
    const onAuthenticated = vi.fn()
    render(<LoginForm onAuthenticated={onAuthenticated} />)
    await user.type(screen.getByLabelText('用户名'), 'alice')
    await user.type(screen.getByLabelText('密码'), 'secret')
    await user.type(screen.getByLabelText('验证码'), '0000') // code is always 1000-9999
    await user.click(screen.getByRole('button', { name: '登录' }))
    expect(screen.getByRole('alert')).toHaveTextContent('验证码错误')
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('authenticates when username, password and captcha are all valid', async () => {
    const user = userEvent.setup()
    const onAuthenticated = vi.fn()
    render(<LoginForm onAuthenticated={onAuthenticated} />)
    await fillValidCredentials(user)
    await user.click(screen.getByRole('button', { name: '登录' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(onAuthenticated).toHaveBeenCalledOnce()
  })

  it('submits on Enter within the form', async () => {
    const user = userEvent.setup()
    const onAuthenticated = vi.fn()
    render(<LoginForm onAuthenticated={onAuthenticated} />)
    await fillValidCredentials(user)
    await user.keyboard('{Enter}')
    expect(onAuthenticated).toHaveBeenCalledOnce()
  })
})
