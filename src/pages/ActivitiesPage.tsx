import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ActivityTable } from '../components/ActivityTable'
import { ActivityCardList } from '../components/ActivityCardList'
import { Pager, type PageSize } from '../components/Pager'
import {
  fitFileName,
  generateActivities,
  TYPE_FILTERS,
  type Activity,
  type TypeFilter,
} from '../activities/activityData'
import { useUploadedActivities } from '../activities/uploadStore'
import { useBreakpoint } from '../hooks/useBreakpoint'
import './ActivitiesPage.css'

// Contract C-7: activity list with type filter, 20/50/100 paging, per-row and
// batch FIT download (all simulated, G-mock). Detail navigation arrives in C-8.
// Files imported on the 连接器 page (C-13) are prepended here as 「FIT上传」 rows.
export function ActivitiesPage() {
  const navigate = useNavigate()
  // Only mobile swaps the desktop table for the card list (C-7 AC-007c-1: the
  // card list must be absent from the DOM on desktop, present on mobile — so it
  // is conditionally mounted, not merely display:none'd).
  const isMobile = useBreakpoint() === 'mobile'
  // Generated once; the mock dataset is stable across renders.
  const [generated] = useState<Activity[]>(generateActivities)
  const uploaded = useUploadedActivities()
  const activities = useMemo(
    () => (uploaded.length > 0 ? [...uploaded, ...generated] : generated),
    [uploaded, generated],
  )
  const [filter, setFilter] = useState<TypeFilter>('全部')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState<PageSize>(20)
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const [downloadNote, setDownloadNote] = useState('')

  const filtered = useMemo(
    () => (filter === '全部' ? activities : activities.filter((a) => a.type === filter)),
    [activities, filter],
  )

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const pageSlice = useMemo(
    () => filtered.slice(safePage * pageSize, (safePage + 1) * pageSize),
    [filtered, safePage, pageSize],
  )

  const selectFilter = (next: TypeFilter) => {
    setFilter(next)
    setPage(0)
  }

  const changePageSize = (size: PageSize) => {
    setPageSize(size)
    setPage(0)
  }

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Downloads are front-end mocks: no real network / file write (G-mock).
  const downloadOne = (id: string) => {
    const a = activities.find((item) => item.id === id)
    if (a) setDownloadNote(`已开始下载 ${fitFileName(a)}（模拟）`)
  }

  const downloadSelected = () => {
    if (selected.size === 0) return
    setDownloadNote(`已开始下载 ${selected.size} 个 FIT 文件（模拟）`)
  }

  return (
    <section className="page activities" data-testid="page-activities">
      <div className="activities__head">
        <div>
          <h1>运动记录</h1>
          <p className="activities__count">
            来自连接器的原始运动数据 · 共 <span className="num">{activities.length}</span> 条
          </p>
        </div>
        <button
          type="button"
          className="activities__batch"
          data-testid="batch-download"
          disabled={selected.size === 0}
          onClick={downloadSelected}
        >
          下载选中 FIT (<span className="num">{selected.size}</span>)
        </button>
      </div>

      <div className="activities__filters" role="group" aria-label="类型筛选">
        {TYPE_FILTERS.map((type) => {
          const active = type === filter
          return (
            <button
              key={type}
              type="button"
              className={active ? 'activities__chip activities__chip--active' : 'activities__chip'}
              // Keep the visual-contract selector stable for C-7 AC-007c-2 checks.
              data-vc={active ? 'type-chip-selected' : 'type-chip'}
              aria-pressed={active}
              onClick={() => selectFilter(type)}
            >
              {type}
            </button>
          )
        })}
      </div>

      <div className="activities__panel">
        {/* Mobile mounts the card list (data-vc anchor, absent on desktop);
            the table stays in the DOM at every width and hides via CSS on mobile
            (AC-007b-1 asserts its computed display=none there). Only one surface
            is visible per viewport (AC-007c-1). */}
        {isMobile && (
          <ActivityCardList
            activities={pageSlice}
            selectedIds={selected}
            onToggle={toggle}
            onDownload={downloadOne}
            onOpen={(id) => navigate(`/activities/${id}`)}
          />
        )}
        <ActivityTable
          activities={pageSlice}
          selectedIds={selected}
          onToggle={toggle}
          onDownload={downloadOne}
          onOpen={(id) => navigate(`/activities/${id}`)}
        />
        <Pager
          total={filtered.length}
          page={safePage}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={changePageSize}
        />
      </div>

      <p className="activities__note num" role="status" data-testid="download-status">
        {downloadNote}
      </p>
    </section>
  )
}
