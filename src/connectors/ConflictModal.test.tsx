import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConflictModal } from './ConflictModal'
import { demoConflictGroups } from './conflictData'

const groups = demoConflictGroups()

describe('ConflictModal', () => {
  it('renders one group per conflict with both 保留 options', () => {
    render(<ConflictModal groups={groups} onConfirm={() => {}} onClose={() => {}} />)
    const rows = screen.getAllByTestId('conflict-group')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('保留中国区')).toBeInTheDocument()
    expect(within(rows[0]).getByText('保留国际区')).toBeInTheDocument()
  })

  it('confirm is disabled until every group has a choice, then reports the choices', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(<ConflictModal groups={groups} onConfirm={onConfirm} onClose={() => {}} />)

    const confirm = screen.getByTestId('conflict-confirm')
    expect(confirm).toBeDisabled()

    const rows = screen.getAllByTestId('conflict-group')
    await user.click(within(rows[0]).getByTestId('conflict-choice-cn'))
    // still disabled — second group unresolved
    expect(confirm).toBeDisabled()
    await user.click(within(rows[1]).getByTestId('conflict-choice-global'))
    expect(confirm).toBeEnabled()

    await user.click(confirm)
    expect(onConfirm).toHaveBeenCalledTimes(1)
    const choices = onConfirm.mock.calls[0][0]
    expect(choices[groups[0].id]).toBe('cn')
    expect(choices[groups[1].id]).toBe('global')
  })

  it('backdrop click closes', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<ConflictModal groups={groups} onConfirm={() => {}} onClose={onClose} />)
    await user.click(screen.getByTestId('conflict-modal-backdrop'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
