import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from './authApi'
import { AuthProvider } from './AuthContext'
import { RequireAuth } from './RequireAuth'

vi.mock('./authApi')

describe('AuthProvider route protection', () => {
  beforeEach(() => {
    vi.mocked(authApi.restoreSession).mockReset()
  })

  it('redirects a protected route to login when no server session exists', async () => {
    vi.mocked(authApi.restoreSession).mockRejectedValue(new Error('unauthenticated'))
    render(
      <MemoryRouter initialEntries={['/activities']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<div>login page</div>} />
            <Route element={<RequireAuth />}>
              <Route path="/activities" element={<div>private page</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('login page')).toBeInTheDocument())
    expect(screen.queryByText('private page')).not.toBeInTheDocument()
  })

  it('restores a protected route when the server session is valid', async () => {
    vi.mocked(authApi.restoreSession).mockResolvedValue({
      user: { id: 'u1', username: 'owner-user', displayName: 'Owner', isOwner: true },
      expiresAt: '2026-08-01T00:00:00Z',
    })
    render(
      <MemoryRouter initialEntries={['/activities']}>
        <AuthProvider>
          <Routes>
            <Route element={<RequireAuth />}>
              <Route path="/activities" element={<div>private page</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('private page')).toBeInTheDocument())
  })
})
