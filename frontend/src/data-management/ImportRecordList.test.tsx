import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ImportRecordList } from './ImportRecordList'
import { demoImportFirstPage } from './demoData'

describe('ImportRecordList', () => {
  it('shows the authoritative four-record first page and appends all seven statuses', async () => {
    const user = userEvent.setup()
    render(<ImportRecordList demoMode />)
    expect(screen.getAllByTestId('import-record-row')).toHaveLength(4)
    expect(screen.getAllByText('617273913_ACTIVITY.fit').length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: '加载更多' }))
    expect(screen.getAllByTestId('import-record-row')).toHaveLength(7)
    for (const label of [
      '等待处理',
      '处理中',
      '处理完成',
      '部分完成',
      '处理失败',
      '正在删除',
      '删除未完成',
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('uses permission booleans rather than status guesses', () => {
    render(<ImportRecordList demoMode />)
    const pending = screen
      .getAllByTestId('import-record-row')
      .find((row) => within(row).queryByText('616634193_ACTIVITY.fit'))!
    expect(within(pending).queryByRole('button', { name: '重新处理' })).not.toBeInTheDocument()
    const partial = screen
      .getAllByTestId('import-record-row')
      .find((row) => within(row).queryByText('600348741_ACTIVITY.fit'))!
    expect(within(partial).getByRole('button', { name: '重新处理' })).toBeInTheDocument()
    expect(within(partial).getByRole('link', { name: '查看运动' })).toBeInTheDocument()
  })

  it('renders first-page loading, error, retry and empty states', async () => {
    let rejectLoad: (reason?: unknown) => void = () => {}
    const pending = new Promise<never>((_, reject) => {
      rejectLoad = reject
    })
    const loadPage = vi
      .fn()
      .mockReturnValueOnce(pending)
      .mockResolvedValueOnce({ items: [], nextCursor: null })
    render(<ImportRecordList demoMode={false} loadPage={loadPage} />)
    expect(document.querySelector('[data-vc="import-list-loading"]')).toBeInTheDocument()
    rejectLoad(new Error('private server failure'))
    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法加载')
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('暂无 FIT 导入记录')).toBeInTheDocument()
    expect(document.querySelector('[data-vc="import-list-empty"]')).toBeInTheDocument()
  })

  it('keeps current rows after cursor failure and retries through the API before refetching', async () => {
    const failed = { ...demoImportFirstPage[1], retryAvailable: true }
    const refreshed = { ...failed, status: 'processing' as const, retryAvailable: false }
    const loadPage = vi
      .fn()
      .mockResolvedValueOnce({ items: [failed], nextCursor: 'opaque-cursor' })
      .mockRejectedValueOnce(new Error('cursor unavailable'))
      .mockResolvedValueOnce({ items: [refreshed], nextCursor: null })
    const retryRecord = vi.fn(async () => undefined)
    render(<ImportRecordList demoMode={false} loadPage={loadPage} retryRecord={retryRecord} />)
    expect(await screen.findAllByTestId('import-record-row')).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: '加载更多' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('现有记录已保留')
    expect(screen.getAllByTestId('import-record-row')).toHaveLength(1)

    const tableRow = screen.getAllByTestId('import-record-row')[0]
    await userEvent.click(within(tableRow).getByRole('button', { name: '重新处理' }))
    await waitFor(() => expect(retryRecord).toHaveBeenCalledWith(failed.importId))
    await waitFor(() => expect(loadPage).toHaveBeenLastCalledWith())
    expect(within(tableRow).queryByRole('button', { name: '重新处理' })).not.toBeInTheDocument()
  })
})
