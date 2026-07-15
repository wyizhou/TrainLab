import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ActivityDetail } from '../components/ActivityDetail'
import {
  fitFileName,
  generateActivities,
  FIT_ACTIVITY_ID,
  type Activity,
} from '../activities/activityData'
import { loadRealFitActivity } from '../activities/fitAsset'
import { type ParsedActivity } from '../activities/fitParser'
import './ActivityDetailPage.css'

type ActivityDetailPageProps = {
  // Injectable FIT loader so tests can supply a parsed fixture without fetch.
  loadFit?: () => Promise<ParsedActivity>
}

type LoadState = 'idle' | 'loading' | 'ready' | 'error'

// Contract C-8 container: resolves the activity from the route, parses the real
// FIT for the FIT-backed row (async), and renders the annotated detail view.
export function ActivityDetailPage({ loadFit = loadRealFitActivity }: ActivityDetailPageProps) {
  const { id } = useParams<{ id: string }>()
  const activity = useMemo<Activity | undefined>(
    () => generateActivities().find((a) => a.id === id),
    [id],
  )

  const isFit = activity?.id === FIT_ACTIVITY_ID
  const [parsed, setParsed] = useState<ParsedActivity | null>(null)
  const [state, setState] = useState<LoadState>('idle')
  const [downloadNote, setDownloadNote] = useState('')

  useEffect(() => {
    if (!isFit) {
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
  }, [isFit, loadFit])

  const download = (activityId: string) => {
    const a = activity && activity.id === activityId ? activity : undefined
    if (a) setDownloadNote(`已开始下载 ${fitFileName(a)}（模拟）`)
  }

  if (!activity) {
    return (
      <section className="page activity-detail-page" data-testid="page-activity-detail">
        <Link className="activity-detail-page__back" to="/activities">
          ← 返回运动记录
        </Link>
        <p className="activity-detail-page__missing">未找到该运动记录。</p>
      </section>
    )
  }

  return (
    <section
      className="page activity-detail-page"
      data-vc="page-activities"
      data-testid="page-activity-detail"
    >
      {state === 'loading' && (
        <p className="activity-detail-page__loading" data-testid="detail-loading">
          正在解析 FIT 原始数据…
        </p>
      )}
      {state === 'error' && (
        <p className="activity-detail-page__error" data-testid="detail-error">
          FIT 解析失败，仅显示摘要。
        </p>
      )}

      <ActivityDetail
        activity={activity}
        parsed={parsed}
        onDownload={download}
        backAction={
          <Link className="activity-detail-page__back" to="/activities">
            ← 返回列表
          </Link>
        }
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
    </section>
  )
}
