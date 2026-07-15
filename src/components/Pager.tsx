import './Pager.css'

// Reusable pagination control. Page sizes 20 (default) / 50 / 100 per the
// contract's table baseline (C-7 list, reused by C-8's per-second table).
export const PAGE_SIZES = [20, 50, 100] as const
export type PageSize = (typeof PAGE_SIZES)[number]

type PagerProps = {
  total: number
  page: number // zero-based
  pageSize: PageSize
  onPageChange: (page: number) => void
  onPageSizeChange: (size: PageSize) => void
}

export function Pager({ total, page, pageSize, onPageChange, onPageSizeChange }: PagerProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const clamped = Math.min(page, pageCount - 1)
  const first = total === 0 ? 0 : clamped * pageSize + 1
  const last = Math.min(total, (clamped + 1) * pageSize)

  return (
    <div className="pager" data-testid="pager">
      <span className="pager__info" data-testid="pager-info">
        共 <span className="num">{total}</span> 条 · 第{' '}
        <span className="num">
          {first}–{last}
        </span>
      </span>
      <span className="pager__spacer" />
      <label className="pager__size">
        每页
        <select
          aria-label="每页条数"
          value={pageSize}
          onChange={(event) => onPageSizeChange(Number(event.target.value) as PageSize)}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size} 条
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="pager__nav"
        disabled={clamped <= 0}
        onClick={() => onPageChange(clamped - 1)}
      >
        ← 上一页
      </button>
      <span className="pager__page num" data-testid="pager-page">
        {clamped + 1} / {pageCount}
      </span>
      <button
        type="button"
        className="pager__nav"
        disabled={clamped >= pageCount - 1}
        onClick={() => onPageChange(clamped + 1)}
      >
        下一页 →
      </button>
    </div>
  )
}
