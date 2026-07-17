import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
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
  downloadImportedActivity,
  isImportedActivityId,
  loadImportedActivity,
} from '../activities/activityApi'
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
  const [requestedImportId, setRequestedImportId] = useState<string | null>(null)
  const activity = localActivity ?? (requestedImportId === id ? importedActivity : undefined)
  const isFit = localActivity?.id === FIT_ACTIVITY_ID
  const [parsed, setParsed] = useState<ParsedActivity | null>(null)
  const [state, setState] = useState<LoadState>(imported ? 'loading' : 'idle')
  const [attempt, setAttempt] = useState(0)
  const [downloadNote, setDownloadNote] = useState('')
  const routeState = imported && requestedImportId !== id ? 'loading' : state
  const visibleParsed = imported && requestedImportId !== id ? null : parsed

  useEffect(() => {
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

  const download = (activityId: string) => {
    if (isImportedActivityId(activityId)) {
      void downloadImportedActivity(activityId)
        .then(() =>
          setDownloadNote(
            `已开始下载 ${visibleParsed?.backend?.originalFileName ?? 'activity.fit'}`,
          ),
        )
        .catch(() => setDownloadNote('原始 FIT 下载失败'))
      return
    }
    const a = activity && activity.id === activityId ? activity : undefined
    if (a) setDownloadNote(`已开始下载 ${fitFileName(a)}（模拟）`)
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
        <span className="activity-detail-shell__version num">v3.4 · DESIGN REV 7</span>
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
        <ActivityDetail activity={activity} parsed={visibleParsed} onDownload={download} />
        {downloadNote && (
          <p
            className="activity-detail-page__note num"
            role="status"
            data-testid="detail-download-note"
          >
            {downloadNote}
          </p>
        )}
      </main>
    </div>
  )
}
