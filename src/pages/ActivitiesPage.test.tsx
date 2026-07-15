import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ActivitiesPage } from './ActivitiesPage'

// The page navigates to the detail route on row click (C-8), so it needs a
// router context in tests.
const renderPage = () => render(<ActivitiesPage />, { wrapper: MemoryRouter })

const rows = () => screen.getAllByTestId('activity-row')
const totalFromInfo = () =>
  Number(screen.getByTestId('pager-info').textContent!.match(/共\s*(\d+)\s*条/)![1])

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

  it('downloads a single row FIT via its row button', async () => {
    const user = userEvent.setup()
    renderPage()

    // The page renders both the desktop table and the mobile card list, so the
    // download button exists twice; scope to the table surface for this assert.
    const table = within(screen.getByTestId('activity-table'))
    await user.click(table.getByRole('button', { name: '下载 晨间轻松跑 的 FIT' }))
    // a0 → 2026-07-09_a0.fit (see fitFileName); download is a mock (G-mock).
    expect(screen.getByTestId('download-status')).toHaveTextContent(
      '已开始下载 2026-07-09_a0.fit（模拟）',
    )
  })
})
