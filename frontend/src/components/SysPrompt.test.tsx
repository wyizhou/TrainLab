import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SYSTEM_PROMPT } from '../analysis/systemPrompt'
import { SysPrompt } from './SysPrompt'

describe('SysPrompt', () => {
  it('keeps the v3.2 system prompt as an exact product contract', () => {
    expect(SYSTEM_PROMPT).toBe(
      [
        '你是专业的耐力训练数据分析师。规则:',
        '1. 始终以 HTML 片段回复(仅内联样式),以便在对话框中直接渲染 — 数据对比用 <table>,计划/流程用列表或表格,趋势用系统图表卡片,图片用占位说明;',
        '2. 仅基于系统随对话附带的原始数据(运动记录 / 健康记录 / 习惯记录)进行分析,不得编造数据;',
        '3. TSS、训练负荷等衍生指标由你计算并注明计算依据,系统不预先计算;',
        '4. 中文回复,专业指标可用英文缩写(HRV、NP、GAP 等)。',
      ].join('\n'),
    )
  })

  it('hides the prompt body until viewed, then collapses again (C-6)', async () => {
    const user = userEvent.setup()
    render(<SysPrompt prompt="你是 TrainLab 的训练分析助手。" />)

    // Collapsed by default: body not shown.
    expect(screen.queryByTestId('sys-prompt-body')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '展开提示词' }))
    expect(screen.getByTestId('sys-prompt-body')).toHaveTextContent(
      '你是 TrainLab 的训练分析助手。',
    )

    await user.click(screen.getByRole('button', { name: '收起提示词' }))
    expect(screen.queryByTestId('sys-prompt-body')).not.toBeInTheDocument()
  })
})
