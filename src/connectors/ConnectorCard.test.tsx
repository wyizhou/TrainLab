import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConnectorCard } from './ConnectorCard'
import type { Connector } from './connectorData'

const base: Connector = {
  id: 'garmin-cn',
  name: '佳明中国区',
  status: 'connected',
  lastSyncAt: '2026-07-11 08:00',
  syncedCount: 1200,
  autoSyncInterval: 60,
}

const make = (over: Partial<Connector>): Connector => ({ ...base, ...over })

describe('ConnectorCard four states', () => {
  it('已连接: green pill + 立即同步 button', () => {
    render(<ConnectorCard connector={make({ status: 'connected' })} />)
    expect(screen.getByTestId('connector-pill')).toHaveTextContent('已连接')
    expect(screen.getByTestId('connector-action')).toHaveTextContent('立即同步')
    expect(screen.getByTestId('connector-action')).toBeEnabled()
    expect(screen.queryByTestId('connector-error')).not.toBeInTheDocument()
  })

  it('未连接: grey pill + 连接账号 button, no last-sync', () => {
    render(
      <ConnectorCard
        connector={make({ status: 'disconnected', lastSyncAt: null, syncedCount: 0 })}
      />,
    )
    expect(screen.getByTestId('connector-pill')).toHaveTextContent('未连接')
    expect(screen.getByTestId('connector-action')).toHaveTextContent('连接账号')
    expect(screen.getByText('从未')).toBeInTheDocument()
  })

  it('同步中: pill 同步中 + disabled busy button with spinner', () => {
    render(<ConnectorCard connector={make({ status: 'syncing' })} />)
    expect(screen.getByTestId('connector-pill')).toHaveTextContent('同步中')
    const action = screen.getByTestId('connector-action')
    expect(action).toHaveTextContent('同步中…')
    expect(action).toBeDisabled()
    expect(action).toHaveAttribute('aria-busy', 'true')
  })

  it('同步失败: red pill + error block (失败时间 + 原因) + 重试同步 button', () => {
    render(
      <ConnectorCard
        connector={make({
          status: 'failed',
          error: { at: '2026-07-11 06:30', reason: 'ETIMEDOUT' },
        })}
      />,
    )
    expect(screen.getByTestId('connector-pill')).toHaveTextContent('同步失败')
    expect(screen.getByTestId('connector-action')).toHaveTextContent('重试同步')
    const err = screen.getByTestId('connector-error')
    expect(err).toHaveTextContent('2026-07-11 06:30')
    expect(err).toHaveTextContent('ETIMEDOUT')
  })

  it('mirrors pixel-contract data-vc anchors on card + status pill (AC-010c hard req)', () => {
    const { rerender } = render(<ConnectorCard connector={make({ status: 'connected' })} />)
    expect(screen.getByTestId('connector-card')).toHaveAttribute('data-vc', 'connector-card')
    expect(screen.getByTestId('connector-pill')).toHaveAttribute('data-vc', 'status-pill-connected')

    rerender(<ConnectorCard connector={make({ status: 'disconnected' })} />)
    expect(screen.getByTestId('connector-pill')).toHaveAttribute(
      'data-vc',
      'status-pill-disconnected',
    )

    rerender(
      <ConnectorCard connector={make({ status: 'failed', error: { at: 'x', reason: 'y' } })} />,
    )
    expect(screen.getByTestId('connector-pill')).toHaveAttribute('data-vc', 'status-pill-failed')
  })

  it('shows the four auto-sync interval options and the selected one', () => {
    render(<ConnectorCard connector={make({ autoSyncInterval: 360 })} />)
    const select = screen.getByLabelText('自动同步间隔') as HTMLSelectElement
    for (const label of ['30 分钟', '1 小时', '6 小时', '仅手动']) {
      expect(screen.getByRole('option', { name: label })).toBeInTheDocument()
    }
    expect(select.value).toBe('360')
  })

  it('fires callbacks for sync, connect and interval change', async () => {
    const user = userEvent.setup()
    const onSync = vi.fn()
    const onConnect = vi.fn()
    const onIntervalChange = vi.fn()

    const { rerender } = render(
      <ConnectorCard
        connector={make({ status: 'failed', error: { at: 'x', reason: 'ETIMEDOUT' } })}
        onSync={onSync}
        onConnect={onConnect}
        onIntervalChange={onIntervalChange}
      />,
    )
    await user.click(screen.getByTestId('connector-action'))
    expect(onSync).toHaveBeenCalledWith('garmin-cn')

    rerender(
      <ConnectorCard
        connector={make({ status: 'disconnected' })}
        onSync={onSync}
        onConnect={onConnect}
        onIntervalChange={onIntervalChange}
      />,
    )
    await user.click(screen.getByTestId('connector-action'))
    expect(onConnect).toHaveBeenCalledWith('garmin-cn')

    await user.selectOptions(screen.getByLabelText('自动同步间隔'), '仅手动')
    expect(onIntervalChange).toHaveBeenCalledWith('garmin-cn', 'manual')
  })
})
