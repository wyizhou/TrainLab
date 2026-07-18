import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, vi } from 'vitest'
import { ActivitiesPage } from './ActivitiesPage'
import { AuthContext, demoUser, type AuthContextValue } from '../auth/AuthState'
import { addUploadedActivities, resetUploadedActivities } from '../activities/uploadStore'

// The page navigates to the detail route on row click (C-8), so it needs a
// router context in tests.
const renderPage = (demoMode = true) => {
  const auth: AuthContextValue = {
    status: 'authenticated',
    user: demoUser,
    demoMode,
    login: async () => {},
    logout: async () => {},
  }
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={auth}>
        <ActivitiesPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

const rows = () => screen.getAllByTestId('activity-row')
const totalFromInfo = () =>
  Number(screen.getByTestId('pager-info').textContent!.match(/共\s*(\d+)\s*条/)![1])

beforeEach(() => {
  resetUploadedActivities()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ items: [], nextCursor: null }), {
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
})

afterEach(() => {
  resetUploadedActivities()
  vi.unstubAllGlobals()
})

describe('ActivitiesPage', () => {
  it('paginates 20 per page by default and switches to 50', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(rows()).toHaveLength(20)
    expect(screen.getByTestId('pager-page')).toHaveTextContent(/^1 \//)

    await user.selectOptions(screen.getByLabelText('每页条数'), '50')
    expect(rows()).toHaveLength(50)
  })

  it('filters by type in real time and resets to the first page', async () => {
    const user = userEvent.setup()
    renderPage()
    const all = totalFromInfo()

    // Jump to a later page, then filter — filtering must snap back to page 1.
    await user.click(screen.getByRole('button', { name: '下一页 →' }))
    await user.click(screen.getByRole('button', { name: '力量' }))

    expect(screen.getByRole('button', { name: '力量' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('pager-page')).toHaveTextContent(/^1 \//)
    // Strength-only view is a strict subset; the run "晨间轻松跑" drops out.
    expect(totalFromInfo()).toBeLessThan(all)
    expect(screen.queryByText('晨间轻松跑')).not.toBeInTheDocument()

    // Back to 全部 restores the full count.
    await user.click(screen.getByRole('button', { name: '全部' }))
    expect(totalFromInfo()).toBe(all)
  })

  it('offers filters for every first-round imported activity type', () => {
    renderPage(false)
    for (const type of ['徒步', '难度攀岩', '抱石', '其他']) {
      expect(screen.getByRole('button', { name: type })).toBeInTheDocument()
    }
  })

  it('does not mix design fixture activities into a real authenticated account', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [
            {
              id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              date: '2026-07-17',
              type: '徒步',
              name: '真实账号徒步',
              distanceKm: 7.2,
              durationSec: 3600,
              avgHr: null,
              paceSecPerKm: null,
              pace100Sec: null,
              powerW: null,
              source: 'FIT上传',
              profile: 'hike',
            },
          ],
          nextCursor: null,
        }),
        { headers: { 'Content-Type': 'application/json' } },
      ),
    )
    renderPage(false)

    expect(await screen.findByText('真实账号徒步')).toBeInTheDocument()
    expect(screen.queryByText('晨间轻松跑')).not.toBeInTheDocument()
    expect(document.querySelector('.activities__count')).toHaveTextContent('共 1 条')
    expect(screen.getByRole('checkbox', { name: '选择 真实账号徒步' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '打开运动操作菜单' })).toBeInTheDocument()
  })

  it('keeps a real-session local preview out of FIT selection and download flows', async () => {
    addUploadedActivities([
      {
        date: '2026-07-17',
        type: '徒步',
        name: '本地 GPX 预览',
        distanceKm: 2.4,
        durationSec: 900,
        avgHr: null,
        paceSecPerKm: null,
        pace100Sec: null,
        powerW: null,
        source: 'FIT上传',
      },
    ])
    renderPage(false)

    expect(await screen.findByText('本地 GPX 预览')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: '选择 本地 GPX 预览' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '下载 本地 GPX 预览 的 FIT' }),
    ).not.toBeInTheDocument()
    expect(screen.getByTestId('batch-download')).toBeDisabled()
  })

  it('shows an explicit empty state for a real account with no activities', async () => {
    renderPage(false)
    expect(await screen.findByTestId('activities-empty')).toHaveTextContent('暂无运动记录')
    expect(screen.queryByTestId('activity-table')).not.toBeInTheDocument()
  })

  it('distinguishes list loading failure from a successful empty result and retries', async () => {
    vi.mocked(fetch)
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], nextCursor: null }), {
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    renderPage(false)

    expect(await screen.findByTestId('activities-load-error')).toHaveTextContent('暂时加载失败')
    expect(screen.queryByTestId('activities-empty')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByTestId('activities-empty')).toHaveTextContent('暂无运动记录')
  })

  it('tracks the batch-download count as selections change and simulates download', async () => {
    const user = userEvent.setup()
    renderPage()

    const batch = screen.getByTestId('batch-download')
    expect(batch).toBeDisabled()
    expect(batch).toHaveTextContent('下载选中 FIT (0)')

    const checks = screen.getAllByRole('checkbox')
    await user.click(checks[0])
    await user.click(checks[1])
    expect(batch).toHaveTextContent('下载选中 FIT (2)')
    expect(batch).toBeEnabled()

    await user.click(batch)
    expect(screen.getByTestId('download-status')).toHaveTextContent(
      '已开始下载 2 个 FIT 文件（模拟）',
    )
  })

  it('keeps selections when paging across the list', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getAllByRole('checkbox')[0])
    expect(screen.getByTestId('batch-download')).toHaveTextContent('(1)')

    await user.click(screen.getByRole('button', { name: '下一页 →' }))
    // Selection survives the page change (state lives above the table).
    expect(screen.getByTestId('batch-download')).toHaveTextContent('(1)')
  })

  it('downloads a single row FIT via its activity menu', async () => {
    const user = userEvent.setup()
    renderPage()

    const table = within(screen.getByTestId('activity-table'))
    await user.click(table.getAllByRole('button', { name: '打开运动操作菜单' })[0])
    await user.click(screen.getByRole('menuitem', { name: '下载原始 FIT' }))
    // a0 → 2026-07-09_a0.fit (see fitFileName); download is a mock (G-mock).
    expect(screen.getByTestId('download-status')).toHaveTextContent(
      '已开始下载 2026-07-09_a0.fit（模拟）',
    )
  })
})
