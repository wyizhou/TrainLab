import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SysPrompt } from './SysPrompt'

describe('SysPrompt', () => {
  it('hides the prompt body until viewed, then collapses again (C-6)', async () => {
    const user = userEvent.setup()
    render(<SysPrompt prompt="你是 TrainLab 的训练分析助手。" />)

    // Collapsed by default: body not shown.
    expect(screen.queryByTestId('sys-prompt-body')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '查看' }))
    expect(screen.getByTestId('sys-prompt-body')).toHaveTextContent(
      '你是 TrainLab 的训练分析助手。',
    )

    await user.click(screen.getByRole('button', { name: '收起' }))
    expect(screen.queryByTestId('sys-prompt-body')).not.toBeInTheDocument()
  })
})
