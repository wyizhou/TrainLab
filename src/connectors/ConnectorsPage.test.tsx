import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ConnectorsPage } from './ConnectorsPage'

const cards = () => screen.getAllByTestId('connector-card')
const cardByName = (name: string) => cards().find((c) => within(c).queryByText(name))!

describe('ConnectorsPage demo initial state', () => {
  it('renders 中国区 = 同步失败(ETIMEDOUT) and 国际区 = 未连接', () => {
    render(<ConnectorsPage />)
    expect(screen.getByTestId('page-connectors')).toBeInTheDocument()
    expect(cards()).toHaveLength(2)

    const cn = cardByName('佳明中国区')
    expect(within(cn).getByTestId('connector-pill')).toHaveTextContent('同步失败')
    expect(within(cn).getByTestId('connector-error')).toHaveTextContent('ETIMEDOUT')
    expect(within(cn).getByTestId('connector-action')).toHaveTextContent('重试同步')

    const global = cardByName('佳明国际区')
    expect(within(global).getByTestId('connector-pill')).toHaveTextContent('未连接')
    expect(within(global).getByTestId('connector-action')).toHaveTextContent('连接账号')
  })

  it('retry-sync flips 中国区 to 已连接 and clears the error', async () => {
    const user = userEvent.setup()
    render(<ConnectorsPage />)

    await user.click(within(cardByName('佳明中国区')).getByTestId('connector-action'))

    const cn = cardByName('佳明中国区')
    expect(within(cn).getByTestId('connector-pill')).toHaveTextContent('已连接')
    expect(within(cn).queryByTestId('connector-error')).not.toBeInTheDocument()
    expect(within(cn).getByTestId('connector-action')).toHaveTextContent('立即同步')
    expect(within(cn).getByText('刚刚')).toBeInTheDocument()
  })

  it('connect opens the auth modal; a login flips 国际区 to 已连接', async () => {
    const user = userEvent.setup()
    render(<ConnectorsPage />)

    await user.click(within(cardByName('佳明国际区')).getByTestId('connector-action'))

    // C-11: connecting opens the auth modal rather than connecting directly.
    const modal = await screen.findByRole('dialog')
    expect(modal).toHaveTextContent('连接 佳明国际区')

    await user.type(screen.getByLabelText('账号'), 'alice')
    await user.type(screen.getByLabelText('密码'), 'secret')
    await user.click(screen.getByTestId('auth-submit'))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const global = cardByName('佳明国际区')
    expect(within(global).getByTestId('connector-pill')).toHaveTextContent('已连接')
  })

  it('connecting 国际区 surfaces 2 conflict groups; resolving them clears the banner', async () => {
    const user = userEvent.setup()
    render(<ConnectorsPage />)

    // Connect 国际区 (no 2FA) to trigger the double-account merge check.
    await user.click(within(cardByName('佳明国际区')).getByTestId('connector-action'))
    await user.type(screen.getByLabelText('账号'), 'alice')
    await user.type(screen.getByLabelText('密码'), 'secret')
    await user.click(screen.getByTestId('auth-submit'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    // Banner announces the two suspected duplicates.
    const banner = await screen.findByTestId('conflict-banner')
    expect(banner).toHaveTextContent('发现 2 组疑似重复运动')

    // 处理重复 → per-group choice → 确认合并.
    await user.click(screen.getByTestId('conflict-resolve'))
    const rows = screen.getAllByTestId('conflict-group')
    expect(rows).toHaveLength(2)
    await user.click(within(rows[0]).getByTestId('conflict-choice-cn'))
    await user.click(within(rows[1]).getByTestId('conflict-choice-global'))
    await user.click(screen.getByTestId('conflict-confirm'))

    // Merge applied — banner and modal are gone.
    expect(screen.queryByTestId('conflict-banner')).not.toBeInTheDocument()
    expect(screen.queryByTestId('conflict-modal')).not.toBeInTheDocument()
  })

  it('retry-sync surfaces a 同步成功 toast (AC-001c-4)', async () => {
    const user = userEvent.setup()
    render(<ConnectorsPage />)
    expect(screen.queryByTestId('toast')).not.toBeInTheDocument()

    await user.click(within(cardByName('佳明中国区')).getByTestId('connector-action'))

    const toast = screen.getByTestId('toast')
    expect(toast).toHaveAttribute('data-vc', 'toast')
    expect(toast).toHaveTextContent('同步成功')
  })

  it('retry-syncing 中国区 does not raise a merge banner', async () => {
    const user = userEvent.setup()
    render(<ConnectorsPage />)
    await user.click(within(cardByName('佳明中国区')).getByTestId('connector-action'))
    expect(screen.queryByTestId('conflict-banner')).not.toBeInTheDocument()
  })

  it('changes the auto-sync interval', async () => {
    const user = userEvent.setup()
    render(<ConnectorsPage />)

    const global = cardByName('佳明国际区')
    const select = within(global).getByLabelText('自动同步间隔') as HTMLSelectElement
    expect(select.value).toBe('manual')

    await user.selectOptions(select, '6 小时')
    expect(
      (within(cardByName('佳明国际区')).getByLabelText('自动同步间隔') as HTMLSelectElement).value,
    ).toBe('360')
  })
})
