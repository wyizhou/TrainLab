import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { Pager, type PageSize } from './Pager'

// Thin controlled harness so we can drive the pager like the page does.
function Harness({ total }: { total: number }) {
  const [page, setPage] = useState(0)
  const [size, setSize] = useState<PageSize>(20)
  return (
    <Pager
      total={total}
      page={page}
      pageSize={size}
      onPageChange={setPage}
      onPageSizeChange={(s) => {
        setSize(s)
        setPage(0)
      }}
    />
  )
}

describe('Pager', () => {
  it('shows the current range and page count, disabling prev on page 1', () => {
    render(<Harness total={65} />)
    expect(screen.getByTestId('pager-info')).toHaveTextContent('共 65 条 · 第 1–20')
    expect(screen.getByTestId('pager-page')).toHaveTextContent('1 / 4')
    expect(screen.getByRole('button', { name: '← 上一页' })).toBeDisabled()
  })

  it('advances pages and re-clamps the range on the last page', async () => {
    const user = userEvent.setup()
    render(<Harness total={65} />)
    const next = screen.getByRole('button', { name: '下一页 →' })
    await user.click(next)
    expect(screen.getByTestId('pager-info')).toHaveTextContent('第 21–40')
    await user.click(next)
    await user.click(next)
    // Page 4 holds the final 5 of 65 and disables "next".
    expect(screen.getByTestId('pager-page')).toHaveTextContent('4 / 4')
    expect(screen.getByTestId('pager-info')).toHaveTextContent('第 61–65')
    expect(next).toBeDisabled()
  })

  it('changes page size and recomputes the page count', async () => {
    const user = userEvent.setup()
    render(<Harness total={65} />)
    await user.selectOptions(screen.getByLabelText('每页条数'), '50')
    expect(screen.getByTestId('pager-page')).toHaveTextContent('1 / 2')
    expect(screen.getByTestId('pager-info')).toHaveTextContent('第 1–50')
  })
})
