import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from './authApi'
import { AuthProvider } from './AuthContext'
import { RequireAuth } from './RequireAuth'
import { useAuth } from './AuthState'
import {
  addUploadedActivities,
  getUploadedActivities,
  resetUploadedActivities,
} from '../activities/uploadStore'
import { getSettings, resetSettings, updateSettings } from '../settings/settingsStore'

vi.mock('./authApi')

describe('AuthProvider route protection', () => {
  beforeEach(() => {
    vi.mocked(authApi.restoreSession).mockReset()
    vi.mocked(authApi.login).mockReset()
    vi.mocked(authApi.logout).mockReset()
    resetUploadedActivities()
    resetSettings()
  })

  function SessionControls() {
    const auth = useAuth()
    return (
      <>
        <span>{auth.user?.id ?? 'none'}</span>
        <button type="button" onClick={() => void auth.logout()}>
          logout
        </button>
        <button type="button" onClick={() => void auth.login('peer', 'password')}>
          switch
        </button>
      </>
    )
  }

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

  it('clears activity summaries and sensitive settings on logout', async () => {
    vi.mocked(authApi.restoreSession).mockResolvedValue({
      user: { id: 'u1', username: 'owner-user', displayName: 'Owner', isOwner: true },
      expiresAt: '2026-08-01T00:00:00Z',
    })
    vi.mocked(authApi.logout).mockResolvedValue({ status: 'logged_out' })
    render(
      <AuthProvider>
        <SessionControls />
      </AuthProvider>,
    )
    await screen.findByText('u1')
    act(() => {
      addUploadedActivities([
        {
          date: '2026-07-01',
          type: '力量',
          name: 'owner private summary',
          distanceKm: null,
          durationSec: 600,
          avgHr: null,
          paceSecPerKm: null,
          pace100Sec: null,
          powerW: null,
          source: 'FIT上传',
        },
      ])
      updateSettings((previous) => ({
        ...previous,
        ai: { ...previous.ai, apiKey: 'owner-secret-key' },
      }))
    })

    await userEvent.click(screen.getByRole('button', { name: 'logout' }))
    await screen.findByText('none')
    expect(getUploadedActivities()).toHaveLength(0)
    expect(getSettings().ai.apiKey).toBe('')
  })

  it('clears session state when the authenticated subject changes without a reload', async () => {
    vi.mocked(authApi.restoreSession).mockResolvedValue({
      user: { id: 'u1', username: 'owner-user', displayName: 'Owner', isOwner: true },
      expiresAt: '2026-08-01T00:00:00Z',
    })
    vi.mocked(authApi.login).mockResolvedValue({
      user: { id: 'u2', username: 'peer', displayName: 'Peer', isOwner: false },
      expiresAt: '2026-08-01T00:00:00Z',
    })
    render(
      <AuthProvider>
        <SessionControls />
      </AuthProvider>,
    )
    await screen.findByText('u1')
    act(() => {
      updateSettings((previous) => ({
        ...previous,
        ai: { ...previous.ai, apiKey: 'owner-secret-key' },
      }))
    })

    await userEvent.click(screen.getByRole('button', { name: 'switch' }))
    await screen.findByText('u2')
    expect(getSettings().ai.apiKey).toBe('')
  })
})
