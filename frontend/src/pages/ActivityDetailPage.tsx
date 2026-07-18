import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ActivityDetail } from '../components/ActivityDetail'
import {
  fitFileName,
  generateActivities,
  FIT_ACTIVITY_ID,
  type Activity,
} from '../activities/activityData'
import { profileActivityById } from '../activities/activityProfiles'
import { loadRealFitActivity } from '../activities/fitAsset'
import { type ParsedActivity } from '../activities/fitParser'
import {
  ActivityApiError,
  deleteImportedActivity,
  downloadImportedActivity,
  isImportedActivityId,
  loadImportedActivity,
  updateImportedActivityName,
} from '../activities/activityApi'
import { ActivityActions } from '../components/ActivityActions'
import { Toast } from '../components/Toast'
import './ActivityDetailPage.css'
import { useAuth } from '../auth/AuthState'

type ActivityDetailPageProps = {
  // Injectable FIT loader so tests can supply a parsed fixture without fetch.
  loadFit?: () => Promise<ParsedActivity>
}

type LoadState = 'idle' | 'loading' | 'ready' | 'error' | 'not-found'

// Contract C-8 container: resolves the activity from the route, parses the real
// FIT for the FIT-backed row (async), and renders the annotated detail view.
export function ActivityDetailPage({ loadFit = loadRealFitActivity }: ActivityDetailPageProps) {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const auth = useAuth()
  const localActivity = useMemo<Activity | undefined>(
    () =>
      auth.demoMode
        ? (generateActivities().find((candidate) => candidate.id === id) ?? profileActivityById(id))
        : undefined,
    [auth.demoMode, id],
  )

  const imported = id !== undefined && isImportedActivityId(id)
  const [importedActivity, setImportedActivity] = useState<Activity | undefined>()
  const [localOverride, setLocalOverride] = useState<Activity | undefined>()
  const [requestedImportId, setRequestedImportId] = useState<string | null>(null)
  const activity =
    localOverride ?? localActivity ?? (requestedImportId === id ? importedActivity : undefined)
  const isFit = localActivity?.id === FIT_ACTIVITY_ID
  const [parsed, setParsed] = useState<ParsedActivity | null>(null)
  const [state, setState] = useState<LoadState>(imported ? 'loading' : 'idle')
  const [attempt, setAttempt] = useState(0)
  const [downloadNote, setDownloadNote] = useState('')
  const [toast, setToast] = useState('')
  const routeState = imported && requestedImportId !== id ? 'loading' : state
  const visibleParsed = imported && requestedImportId !== id ? null : parsed

  useEffect(() => {
    setLocalOverride(undefined)
    if (imported && id) {
      let alive = true
      setRequestedImportId(id)
      setImportedActivity(undefined)
      setParsed(null)
      setState('loading')
      loadImportedActivity(id)
        .then((data) => {
          if (!alive) return
          setImportedActivity(data.activity)
          setParsed(data.parsed)
          setState('ready')
        })
        .catch((error: unknown) => {
          if (!alive) return
          setImportedActivity(undefined)
          setParsed(null)
          setState(
            error instanceof ActivityApiError && error.status === 404 ? 'not-found' : 'error',
          )
        })
      return () => {
        alive = false
      }
    }
    if (!isFit) {
      setRequestedImportId(null)
      setImportedActivity(undefined)
      setParsed(null)
      setState('idle')
      return
    }
    let alive = true
    setState('loading')
    loadFit()
      .then((data) => {
        if (!alive) return
        setParsed(data)
        setState('ready')
      })
      .catch(() => {
        if (alive) setState('error')
      })
    return () => {
      alive = false
    }
  }, [attempt, id, imported, isFit, loadFit])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(''), 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

  const download = async (activityId: string) => {
    if (isImportedActivityId(activityId)) {
      await downloadImportedActivity(activityId)
      setDownloadNote(`已开始下载 ${visibleParsed?.backend?.originalFileName ?? 'activity.fit'}`)
      return
    }
    const a = activity && activity.id === activityId ? activity : undefined
    if (a) setDownloadNote(`已开始下载 ${fitFileName(a)}（模拟）`)
  }

  const replaceActivity = (updated: Activity) => {
    if (isImportedActivityId(updated.id)) setImportedActivity(updated)
    else setLocalOverride(updated)
    return updated
  }

  const renameActivity = async (current: Activity, name: string) =>
    replaceActivity(
      isImportedActivityId(current.id)
        ? await updateImportedActivityName(current.id, name)
        : { ...current, name },
    )

  const restoreActivity = async (current: Activity) =>
    replaceActivity(
      isImportedActivityId(current.id)
        ? await updateImportedActivityName(current.id, null)
        : (localActivity ?? current),
    )

  const removeActivity = async (current: Activity) => {
    if (isImportedActivityId(current.id)) await deleteImportedActivity(current.id)
    navigate('/activities', {
      replace: true,
      state: { activityFeedback: '运动、导入记录和原始文件已删除' },
    })
  }

  if (!activity && imported && routeState === 'error') {
    return (
      <div className="activity-detail-shell">
        <header className="activity-detail-shell__topbar">
          <Link className="activity-detail-page__back" to="/activities">
            返回运动记录
          </Link>
          <div className="activity-detail-shell__brand">
            <span>TL</span>
            <strong>TrainLab</strong>
          </div>
        </header>
        <section className="activity-detail-page" data-testid="page-activity-detail">
          <p className="activity-detail-page__error" data-testid="detail-load-error">
            运动详情暂时加载失败，请重试。
          </p>
          <button
            type="button"
            className="activity-detail-page__retry"
            onClick={() => {
              setState('loading')
              setAttempt((value) => value + 1)
            }}
          >
            重新加载
          </button>
        </section>
      </div>
    )
  }

  if (!activity && (routeState === 'loading' || (imported && routeState === 'idle'))) {
    return (
      <div className="activity-detail-shell" data-vc="page-activities">
        <main className="activity-detail-page" data-testid="page-activity-detail">
          <p className="activity-detail-page__loading" data-testid="detail-loading">
            正在读取已导入运动…
          </p>
        </main>
      </div>
    )
  }

  if (!activity) {
    return (
      <div className="activity-detail-shell">
        <header className="activity-detail-shell__topbar">
          <Link className="activity-detail-page__back" to="/activities">
            返回运动记录
          </Link>
          <div className="activity-detail-shell__brand">
            <span>TL</span>
            <strong>TrainLab</strong>
          </div>
        </header>
        <section className="activity-detail-page" data-testid="page-activity-detail">
          <p className="activity-detail-page__missing">未找到该运动记录。</p>
        </section>
      </div>
    )
  }

  return (
    <div className="activity-detail-shell" data-vc="page-activities">
      <header className="activity-detail-shell__topbar" data-vc="app-header">
        <Link className="activity-detail-page__back" to="/activities">
          返回运动记录
        </Link>
        <div className="activity-detail-shell__brand">
          <span>TL</span>
          <strong>TrainLab</strong>
        </div>
        <span className="activity-detail-shell__version num">v3.5 · DESIGN REV 8</span>
      </header>
      <main className="activity-detail-page" data-testid="page-activity-detail">
        {routeState === 'loading' && (
          <p className="activity-detail-page__loading" data-testid="detail-loading">
            正在解析 FIT 原始数据…
          </p>
        )}
        {routeState === 'error' && (
          <p className="activity-detail-page__error" data-testid="detail-error">
            FIT 解析失败；已解析摘要仍可使用，请在“原始数据”中重试。
          </p>
        )}
        <ActivityDetail
          activity={activity}
          parsed={visibleParsed}
          onDownload={download}
          managementAction={(downloadAvailable) => (
            <ActivityActions
              activity={activity}
              detail
              onRename={renameActivity}
              onRestore={restoreActivity}
              onDelete={removeActivity}
              onDownload={(item) => download(item.id)}
              onFeedback={setToast}
              downloadAvailable={downloadAvailable}
            />
          )}
        />
        {downloadNote && (
          <p
            className="activity-detail-page__note num"
            role="status"
            data-testid="detail-download-note"
          >
            {downloadNote}
          </p>
        )}
        {toast && <Toast message={toast} />}
      </main>
    </div>
  )
}
