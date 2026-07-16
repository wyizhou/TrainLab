import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthApiError, login, logout, restoreSession } from './authApi'

afterEach(() => {
  vi.restoreAllMocks()
  document.cookie = 'trainlab_csrf=; Max-Age=0; Path=/'
})

describe('authApi', () => {
  it('restores the server session with same-origin credentials', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          user: { id: 'u1', username: 'owner-user', displayName: 'Owner', isOwner: true },
          expiresAt: '2026-08-01T00:00:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    await expect(restoreSession()).resolves.toMatchObject({ user: { username: 'owner-user' } })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/session',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('sends credentials as JSON and exposes the stable server error', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ code: 'invalid_credentials', message: '账号或密码错误' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(login('owner-user', 'wrong-password')).rejects.toEqual(
      new AuthApiError('账号或密码错误', 'invalid_credentials', 401),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/login',
      expect.objectContaining({ method: 'POST', credentials: 'same-origin' }),
    )
  })

  it('copies the CSRF cookie into the logout header', async () => {
    document.cookie = 'trainlab_csrf=csrf-value; Path=/'
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ status: 'logged_out' }), { status: 200 }))
    await logout()
    const init = fetchMock.mock.calls[0][1]
    const headers = new Headers(init?.headers)
    expect(headers.get('X-CSRF-Token')).toBe('csrf-value')
  })
})
