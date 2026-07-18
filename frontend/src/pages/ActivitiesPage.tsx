import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ActivityTable } from '../components/ActivityTable'
import { ActivityCardList } from '../components/ActivityCardList'
import { Pager, type PageSize } from '../components/Pager'
import {
  fitFileName,
  generateActivities,
  DEMO_TYPE_FILTERS,
  TYPE_FILTERS,
  type Activity,
  type TypeFilter,
} from '../activities/activityData'
import { useUploadedActivities } from '../activities/uploadStore'
import {
  deleteImportedActivity,
  downloadImportedActivity,
  isImportedActivityId,
  listImportedActivities,
  updateImportedActivityName,
} from '../activities/activityApi'
import { useBreakpoint } from '../hooks/useBreakpoint'
import { useAuth } from '../auth/AuthState'
import { ActivityActions } from '../components/ActivityActions'
import { Toast } from '../components/Toast'
import './ActivitiesPage.css'

// Contract C-7: activity list with type filter and 20/50/100 paging. Persisted
// UUID rows use real owner-only source downloads; design fixtures and batch
// download remain simulated. Persisted and demo rows open the shared detail view.
export function ActivitiesPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const auth = useAuth()
  const authenticatedUserId = auth.user?.id ?? null
  // Only mobile swaps the desktop table for the card list (C-7 AC-007c-1: the
  // card list must be absent from the DOM on desktop, present on mobile — so it
  // is conditionally mounted, not merely display:none'd).
  const isMobile = useBreakpoint() === 'mobile'
  const generated = useMemo<Activity[]>(
    () => (auth.demoMode ? generateActivities() : []),
    [auth.demoMode],
  )
  const [persisted, setPersisted] = useState<Activity[]>([])
  const [demoOverrides, setDemoOverrides] = useState<Record<string, Activity>>({})
  const [deletedIds, setDeletedIds] = useState<ReadonlySet<string>>(() => new Set())
  const [listState, setListState] = useState<'loading' | 'ready' | 'error'>(
    auth.demoMode ? 'ready' : 'loading',
  )
  const [loadAttempt, setLoadAttempt] = useState(0)
  const uploaded = useUploadedActivities()
  useEffect(() => {
    if (auth.demoMode) return
    setPersisted([])
    if (auth.status !== 'authenticated' || authenticatedUserId === null) {
      setListState('loading')
      return
    }
    setListState('loading')
    let alive = true
    listImportedActivities()
      .then((items) => {
        if (alive) {
          setPersisted(items)
          setListState('ready')
        }
      })
      .catch(() => {
        if (alive) setListState('error')
      })
    return () => {
      alive = false
    }
  }, [auth.demoMode, auth.status, authenticatedUserId, loadAttempt])
  const activities = useMemo(() => {
    const seen = new Set<string>()
    return [...persisted, ...uploaded, ...generated]
      .map((activity) => demoOverrides[activity.id] ?? activity)
      .filter((activity) => {
        if (deletedIds.has(activity.id)) return false
        if (seen.has(activity.id)) return false
        seen.add(activity.id)
        return true
      })
  }, [persisted, uploaded, generated, demoOverrides, deletedIds])
  const [filter, setFilter] = useState<TypeFilter>('全部')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState<PageSize>(20)
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const [downloadNote, setDownloadNote] = useState('')
  const [toast, setToast] = useState('')
  const availableFilters = auth.demoMode ? DEMO_TYPE_FILTERS : TYPE_FILTERS

  useEffect(() => {
    const message = (location.state as { activityFeedback?: string } | null)?.activityFeedback
    if (!message) return
    setToast(message)
    navigate(location.pathname, { replace: true, state: null })
  }, [location.pathname, location.state, navigate])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(''), 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

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
    if (!canUseFitSource(id)) return
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Persisted UUID rows download the private source; fixture and batch actions
  // remain explicit design/demo simulations.
  const downloadOne = async (id: string) => {
    if (!canUseFitSource(id)) return
    const a = activities.find((item) => item.id === id)
    if (!a) return
    if (isImportedActivityId(id)) {
      await downloadImportedActivity(id)
      setDownloadNote(`已开始下载 ${fitFileName(a)}`)
      return
    }
    setDownloadNote(`已开始下载 ${fitFileName(a)}（模拟）`)
  }

  const downloadSelected = () => {
    if (selected.size === 0) return
    setDownloadNote(`已开始下载 ${selected.size} 个 FIT 文件（模拟）`)
  }

  const openOne = (id: string) => {
    if (canOpen(id)) navigate(`/activities/${id}`)
  }

  const canOpen = (id: string) =>
    isImportedActivityId(id) || (auth.demoMode && generated.some((activity) => activity.id === id))

  // Real authenticated sessions may contain TCX/GPX `upload-*` previews. They
  // are session-only summaries, not persisted FIT sources, so they cannot enter
  // selection or source-download flows. Demo keeps the established fixture UI.
  const canUseFitSource = (id: string) => auth.demoMode || isImportedActivityId(id)

  const updateActivity = (updated: Activity) => {
    if (isImportedActivityId(updated.id)) {
      setPersisted((items) => items.map((item) => (item.id === updated.id ? updated : item)))
    } else {
      setDemoOverrides((items) => ({ ...items, [updated.id]: updated }))
    }
    return updated
  }

  const renameActivity = async (activity: Activity, name: string) =>
    updateActivity(
      isImportedActivityId(activity.id)
        ? await updateImportedActivityName(activity.id, name)
        : { ...activity, name },
    )

  const restoreActivity = async (activity: Activity) => {
    if (isImportedActivityId(activity.id)) {
      return updateActivity(await updateImportedActivityName(activity.id, null))
    }
    const original = generated.find((candidate) => candidate.id === activity.id) ?? activity
    return updateActivity(original)
  }

  const removeActivity = async (activity: Activity) => {
    if (isImportedActivityId(activity.id)) await deleteImportedActivity(activity.id)
    setDeletedIds((ids) => new Set(ids).add(activity.id))
    setPersisted((items) => items.filter((item) => item.id !== activity.id))
    setSelected((ids) => {
      const next = new Set(ids)
      next.delete(activity.id)
      return next
    })
  }

  const actionsFor = (activity: Activity) =>
    canUseFitSource(activity.id) ? (
      <ActivityActions
        activity={activity}
        onRename={renameActivity}
        onRestore={restoreActivity}
        onDelete={removeActivity}
        onDownload={(item) => downloadOne(item.id)}
        onFeedback={setToast}
      />
    ) : null

  return (
    <section className="page activities" data-vc="page-activities" data-testid="page-activities">
      <div className="activities__head" data-vc="page-header">
        <div>
          <h1>运动记录</h1>
          <p className="activities__count">
            来自连接器的原始运动数据 · 共 <span className="num">{activities.length}</span> 条
          </p>
        </div>
        <div className="activities__head-spacer" aria-hidden="true" />
        <button
          type="button"
          className="activities__batch"
          data-vc="batch-download-button"
          data-testid="batch-download"
          disabled={selected.size === 0}
          onClick={downloadSelected}
        >
          下载选中 FIT (<span className="num">{selected.size}</span>)
        </button>
      </div>

      <div
        className="activities__filters"
        data-vc="activity-filter-row"
        role="group"
        aria-label="类型筛选"
      >
        {availableFilters.map((type) => {
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
        {listState === 'loading' && (
          <p className="activities__empty" data-testid="activities-loading">
            正在加载运动记录…
          </p>
        )}
        {listState === 'error' && (
          <div className="activities__empty" data-testid="activities-load-error">
            <p>运动记录暂时加载失败。</p>
            <button type="button" onClick={() => setLoadAttempt((value) => value + 1)}>
              重新加载
            </button>
          </div>
        )}
        {listState === 'ready' && filtered.length === 0 && (
          <p className="activities__empty" data-testid="activities-empty">
            {activities.length === 0
              ? '暂无运动记录。可前往连接器上传 FIT 文件。'
              : '当前筛选下暂无运动记录。'}
          </p>
        )}
        {/* Mobile mounts the card list (data-vc anchor, absent on desktop);
            the table stays in the DOM at every width and hides via CSS on mobile
            (AC-007b-1 asserts its computed display=none there). Only one surface
            is visible per viewport (AC-007c-1). */}
        {listState === 'ready' && filtered.length > 0 && isMobile && (
          <ActivityCardList
            activities={pageSlice}
            selectedIds={selected}
            onToggle={toggle}
            onDownload={downloadOne}
            onOpen={openOne}
            isOpenable={canOpen}
            isSelectable={canUseFitSource}
            isDownloadable={canUseFitSource}
            renderActions={actionsFor}
          >
            <Pager
              total={filtered.length}
              page={safePage}
              pageSize={pageSize}
              onPageChange={setPage}
              onPageSizeChange={changePageSize}
            />
          </ActivityCardList>
        )}
        {listState === 'ready' && filtered.length > 0 && !isMobile && (
          <ActivityTable
            activities={pageSlice}
            selectedIds={selected}
            onToggle={toggle}
            onDownload={downloadOne}
            onOpen={openOne}
            isOpenable={canOpen}
            isSelectable={canUseFitSource}
            isDownloadable={canUseFitSource}
            renderActions={actionsFor}
          >
            <Pager
              total={filtered.length}
              page={safePage}
              pageSize={pageSize}
              onPageChange={setPage}
              onPageSizeChange={changePageSize}
            />
          </ActivityTable>
        )}
      </div>

      {downloadNote && (
        <p className="activities__note num" role="status" data-testid="download-status">
          {downloadNote}
        </p>
      )}
      {toast && <Toast message={toast} />}
    </section>
  )
}
