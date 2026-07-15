import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConflictBanner } from './ConflictBanner'

describe('ConflictBanner', () => {
  it('shows the suspected-duplicate count', () => {
    render(<ConflictBanner count={2} onResolve={() => {}} />)
    expect(screen.getByTestId('conflict-banner')).toHaveTextContent('发现 2 组疑似重复运动')
  })

  it('「处理重复」invokes onResolve', async () => {
    const user = userEvent.setup()
    const onResolve = vi.fn()
    render(<ConflictBanner count={2} onResolve={onResolve} />)
    await user.click(screen.getByTestId('conflict-resolve'))
    expect(onResolve).toHaveBeenCalledTimes(1)
  })
})
