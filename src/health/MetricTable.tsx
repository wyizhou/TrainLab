import { useState, type ReactNode } from 'react'
import { Pager, type PageSize } from '../components/Pager'
import { useBreakpoint } from '../hooks/useBreakpoint'
import './MetricTable.css'

// Generic paginated detail table for the health tabs (contract C-9: 明细表, 各表
// 分页 20/50/100). Paging state is self-contained so each tab's table manages its
// own page independently; the Pager (shared C-7 control) supplies the 20/50/100
// tiers and the 共 N 条 count used by the row-count assertions.

export type MetricColumn<T> = {
  key: string
  header: string
  render: (row: T) => ReactNode
  numeric?: boolean // right-aligned monospace figures (G-nums)
}

type MetricTableProps<T> = {
  rows: T[]
  columns: MetricColumn<T>[]
  rowKey: (row: T) => string
  caption: string
  mobileVariant?: 'default' | 'rhr'
}

export function MetricTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  mobileVariant = 'default',
}: MetricTableProps<T>) {
  const breakpoint = useBreakpoint()
  const isMobile = breakpoint === 'mobile'
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState<PageSize>(20)

  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const slice = rows.slice(safePage * pageSize, (safePage + 1) * pageSize)

  const changePageSize = (size: PageSize) => {
    setPageSize(size)
    setPage(0)
  }

  return (
    <div className="metric-table" data-vc="health-table" data-testid="metric-table">
      <div className="metric-table__scroll">
        <table className="metric-table__grid">
          <caption className="metric-table__caption">{caption}</caption>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} className={col.numeric ? 'metric-table__th--num' : undefined}>
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((row) => (
              <tr key={rowKey(row)} data-testid="metric-row">
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={col.numeric ? 'num metric-table__td--num' : undefined}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: one card per row — the min-width:420px grid above is hidden, so
          the four detail tables no longer overflow a 390px viewport (AC-009b-2).
          Same paged slice, so paging behaviour is shared with the grid. Column 0
          (日期) is the card head; the rest render as label/value pairs. */}
      <div className="metric-card-list" data-vc="health-card-list" data-testid="metric-card-list">
        {slice.map((row) => (
          <div
            className={mobileVariant === 'rhr' ? 'metric-card metric-card--rhr' : 'metric-card'}
            data-vc="health-record-card"
            data-testid="metric-card"
            key={rowKey(row)}
          >
            {mobileVariant === 'rhr' ? (
              <>
                <span className="metric-card__rhr-date num">{columns[0]?.render(row)}</span>
                <span className="metric-card__rhr-value">
                  静息 <strong className="num">{columns[1]?.render(row)}</strong>
                </span>
                <span className="metric-card__rhr-value">
                  最低 <strong className="num">{columns[2]?.render(row)}</strong>
                </span>
              </>
            ) : (
              <>
                <div className="metric-card__head">
                  <span className="num">{columns[0]?.render(row)}</span>
                  <strong className="num">{columns[1]?.render(row)}</strong>
                </div>
                <dl className="metric-card__metrics">
                  {columns.slice(2).map((col) => (
                    <div key={col.key}>
                      <dt>{col.header}</dt>
                      <dd className={col.numeric ? 'num' : undefined}>{col.render(row)}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
          </div>
        ))}
        {isMobile && (
          <Pager
            total={rows.length}
            page={safePage}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={changePageSize}
          />
        )}
      </div>

      {!isMobile && (
        <Pager
          total={rows.length}
          page={safePage}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={changePageSize}
        />
      )}
    </div>
  )
}
