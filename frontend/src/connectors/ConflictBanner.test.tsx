import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConflictBanner } from './ConflictBanner'

describe('ConflictBanner', () => {
  it('shows the suspected-duplicate count', () => {
    render(<ConflictBanner count={2} onResolve={() => {}} />)
    const banner = screen.getByTestId('conflict-banner')
    expect(banner).toHaveAttribute('data-vc', 'conflict-banner')
    expect(banner).toHaveTextContent('中国区与国际区发现 2 组疑似重复运动,需要你确认保留哪一条')
    expect(screen.getByTestId('conflict-resolve')).toHaveTextContent('处理重复 (2)')
  })

  it('「处理重复」invokes onResolve', async () => {
    const user = userEvent.setup()
    const onResolve = vi.fn()
    render(<ConflictBanner count={2} onResolve={onResolve} />)
    await user.click(screen.getByTestId('conflict-resolve'))
    expect(onResolve).toHaveBeenCalledTimes(1)
  })
})
