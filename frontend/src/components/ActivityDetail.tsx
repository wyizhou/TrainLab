import { useMemo, useState, type ReactNode } from 'react'
import type { Activity } from '../activities/activityData'
import {
  buildActivityProfile,
  type ActivityProfile,
  type DetailDevice,
  type DetailSpecialized,
} from '../activities/activityProfiles'
import type { ParsedActivity } from '../activities/fitParser'
import { TimeSeriesChart } from './TimeSeriesChart'
import './ActivityDetail.css'

type ActivityDetailProps = {
  activity: Activity
  parsed: ParsedActivity | null
  onDownload?: (id: string) => void
  backAction?: ReactNode
}

type DetailTab = 'overview' | 'charts' | 'segments' | 'devices' | 'raw'
type DeviceFilter = DetailDevice['kind'] | 'all'

const TABS: Array<[DetailTab, string]> = [
  ['overview', '概览'],
  ['charts', '图表'],
  ['segments', '分段 / 训练组'],
  ['devices', '设备与指标'],
  ['raw', '原始数据'],
]

function EmptyExplanation({
  title,
  children,
  vc,
}: {
  title: string
  children: ReactNode
  vc?: string
}) {
  return (
    <div className="detail-empty" data-vc={vc}>
      <strong>{title}</strong>
      <span>{children}</span>
    </div>
  )
}

function Composition({ profile }: { profile: ActivityProfile }) {
  if (profile.composition.length === 0) {
    return <p className="detail-card__note">当前没有可验证的时间构成数据。</p>
  }

  const size = 104
  const radius = 40
  const circumference = 2 * Math.PI * radius
  const values = profile.composition.map((item) =>
    Number.isFinite(item.value) ? Math.max(0, item.value) : 0,
  )
  const total = values.reduce((sum, value) => sum + value, 0)

  if (total === 0) {
    return <p className="detail-card__note">当前没有可验证的时间构成数据。</p>
  }

  let elapsed = 0
  const segments = profile.composition.map((item, index) => {
    const percentage = (values[index] / total) * 100
    const arcLength = (percentage / 100) * circumference
    const segment = {
      ...item,
      arcLength,
      dashOffset: -elapsed,
      percentage,
    }
    elapsed += arcLength
    return segment
  })
  const accessibleName = `时间构成：${segments
    .map((item) => `${item.label} ${Math.round(item.percentage)}%`)
    .join('，')}`

  return (
    <div className="detail-composition">
      <svg
        className="detail-composition__ring"
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={accessibleName}
        data-testid="detail-composition-ring"
      >
        {segments.map((item, index) => (
          <circle
            className={`detail-composition__segment detail-composition__segment--${index}`}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeDasharray={`${item.arcLength} ${circumference - item.arcLength}`}
            strokeDashoffset={item.dashOffset}
            strokeWidth="20"
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            data-percentage={item.percentage}
            key={item.label}
          />
        ))}
      </svg>
      <div className="detail-composition__legend">
        {segments.map((item, index) => (
          <div className="detail-composition__row" key={item.label}>
            <span className={`detail-composition__swatch detail-composition__swatch--${index}`} />
            <span>{item.label}</span>
            <strong className="num">{Math.round(item.percentage)}%</strong>
          </div>
        ))}
      </div>
    </div>
  )
}

function RoutePreview({
  specialized,
}: {
  specialized: Extract<DetailSpecialized, { kind: 'route' }>
}) {
  const points = specialized.points.map((point) => point.join(',')).join(' ')
  return (
    <div className="detail-route">
      <div className="detail-route__map" aria-label="归一化 GPS 轨迹">
        <svg viewBox="0 0 300 190" role="img">
          <polyline points={points} />
          <circle cx={specialized.points[0][0]} cy={specialized.points[0][1]} r="5" />
        </svg>
      </div>
      <div className="detail-field-list">
        {specialized.facts.map(([key, value]) => (
          <div className="detail-field-list__row" key={key}>
            <span>{key}</span>
            <strong className="num">{value}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}

function SpecializedContent({ specialized }: { specialized: DetailSpecialized }) {
  if (specialized.kind === 'route') return <RoutePreview specialized={specialized} />
  if (specialized.kind === 'exercises') {
    return (
      <div className="detail-table-scroll">
        <table className="detail-table">
          <thead>
            <tr>
              <th>动作</th>
              <th>有效组</th>
              <th>次数</th>
              <th>容量 / 记录</th>
            </tr>
          </thead>
          <tbody>
            {specialized.rows.map((row) => (
              <tr key={row[0]}>
                {row.map((value) => (
                  <td key={value}>{value}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  if (specialized.kind === 'metrics') {
    return (
      <>
        <div className="detail-specialized-grid">
          {specialized.items.map((item) => (
            <div className="detail-specialized-metric" key={item.label}>
              <span>{item.label}</span>
              <strong className="num">
                {item.value} <small>{item.unit}</small>
              </strong>
            </div>
          ))}
        </div>
        <p className="detail-card__note">{specialized.note}</p>
      </>
    )
  }
  if (specialized.kind === 'capabilities') {
    return (
      <>
        <div className="detail-specialized-grid">
          {specialized.items.map((item) => (
            <div className="detail-specialized-metric" data-vc="activity-capability" key={item}>
              <span>{item}</span>
              <strong>按字段存在性启用</strong>
            </div>
          ))}
        </div>
        <p className="detail-card__note">{specialized.note}</p>
      </>
    )
  }
  return <p className="detail-card__note">{specialized.note}</p>
}

function OverviewPanel({
  profile,
  activeChart,
  setActiveChart,
}: {
  profile: ActivityProfile
  activeChart: string
  setActiveChart: (id: string) => void
}) {
  const chart =
    profile.charts.find((candidate) => candidate.id === activeChart) ?? profile.charts[0]
  return (
    <section
      className="activity-detail__panel"
      data-vc="activity-overview-panel"
      data-testid="detail-panel-overview"
    >
      <section className="detail-hero">
        <div className="detail-hero__head">
          <div className="detail-hero__token">{profile.token}</div>
          <div>
            <h2>{profile.title}</h2>
            <p className="num">{profile.meta}</p>
          </div>
          <span className="detail-hero__load">{profile.loadLabel}</span>
        </div>
        <div className="detail-hero__metrics">
          {profile.metrics.map((metric) => (
            <div
              className="detail-summary-metric"
              data-vc="activity-summary-metric"
              key={metric.label}
            >
              <span>{metric.label}</span>
              <strong className="num">
                {metric.value}
                <small>{metric.unit}</small>
              </strong>
            </div>
          ))}
        </div>
      </section>

      <section className="detail-insight">
        <strong>DATA INSIGHT</strong>
        <p>{profile.insight}</p>
      </section>

      <div className="detail-overview-layout">
        <div>
          <div className="detail-chart-toolbar">
            <div>
              <strong>{chart?.label ?? '时序数据'}趋势</strong>
              <span>刻度按容器宽度动态计算</span>
            </div>
            <div className="detail-chart-toolbar__tabs">
              {profile.charts.map((candidate) => (
                <button
                  type="button"
                  className={candidate.id === chart?.id ? 'is-active' : ''}
                  onClick={() => setActiveChart(candidate.id)}
                  key={candidate.id}
                >
                  {candidate.label}
                </button>
              ))}
            </div>
          </div>
          {chart && (
            <TimeSeriesChart
              title={chart.label}
              unit={chart.unit}
              sourceField={chart.source}
              values={chart.values}
              timesSec={chart.timesSec}
              distancesKm={chart.distancesKm}
            />
          )}
        </div>
        <aside className="detail-side-stack">
          <section className="detail-card">
            <h3>时间构成</h3>
            <Composition profile={profile} />
          </section>
          <section className="detail-card">
            <h3>FIT 数据来源</h3>
            <div className="detail-field-list">
              {profile.fields.map(([key, value]) => (
                <div className="detail-field-list__row" key={key}>
                  <span className="num">{key}</span>
                  <strong className="num">{value}</strong>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>

      <section className="detail-card detail-card--wide">
        <h3>{profile.specializedTitle}</h3>
        <p className="detail-card__note">{profile.specializedNote}</p>
        <SpecializedContent specialized={profile.specialized} />
      </section>
    </section>
  )
}

function ChartsPanel({
  profile,
  activeChart,
  setActiveChart,
  linkedProgress,
}: {
  profile: ActivityProfile
  activeChart: string
  setActiveChart: (id: string) => void
  linkedProgress: number | null
}) {
  const chart =
    profile.charts.find((candidate) => candidate.id === activeChart) ?? profile.charts[0]
  const route = profile.specialized.kind === 'route' ? profile.specialized : null
  return (
    <section
      className="activity-detail__panel"
      data-vc="activity-charts-panel"
      data-testid="detail-panel-charts"
    >
      {linkedProgress !== null && (
        <div className="detail-linked-note" data-vc="activity-chart-linked-selection">
          已联动选择分段；橙色标记表示对应活动进程。
        </div>
      )}
      <div className="detail-chart-toolbar">
        <div>
          <strong>专项图表</strong>
          <span>悬停显示精确时间、距离、值和单位</span>
        </div>
        <div className="detail-chart-toolbar__tabs">
          {profile.charts.map((candidate) => (
            <button
              type="button"
              className={candidate.id === chart?.id ? 'is-active' : ''}
              onClick={() => setActiveChart(candidate.id)}
              key={candidate.id}
            >
              {candidate.label}
            </button>
          ))}
        </div>
      </div>
      {chart && (
        <TimeSeriesChart
          title={chart.label}
          unit={chart.unit}
          sourceField={chart.source}
          values={chart.values}
          timesSec={chart.timesSec}
          distancesKm={chart.distancesKm}
          linkedProgress={linkedProgress}
        />
      )}
      {route ? (
        <section className="detail-card" data-vc="activity-gps-map">
          <h3>GPS 轨迹</h3>
          <RoutePreview specialized={route} />
        </section>
      ) : (
        <EmptyExplanation title="当前没有可验证的 GPS 数据" vc="activity-no-gps">
          {profile.noGpsReason}
        </EmptyExplanation>
      )}
    </section>
  )
}

function SegmentsPanel({
  profile,
  onSelect,
}: {
  profile: ActivityProfile
  onSelect: (progress: number) => void
}) {
  return (
    <section
      className="activity-detail__panel"
      data-vc="activity-segments-panel"
      data-testid="detail-panel-segments"
    >
      <section className="detail-card" data-vc="activity-segment-module">
        <h3>
          {profile.id === 'strength'
            ? '动作与训练组'
            : profile.id === 'lead'
              ? '攀爬与休息'
              : profile.id === 'boulder'
                ? '尝试与恢复'
                : '圈与分段'}
        </h3>
        <p className="detail-card__note">选择一项后自动进入图表页并显示活动进程标记。</p>
        {profile.segments.length ? (
          <div className="detail-segments">
            {profile.segments.map((segment) => (
              <button
                type="button"
                data-vc={
                  segment.kind === 'lap'
                    ? 'activity-lap-row'
                    : segment.kind === 'exercise'
                      ? 'activity-training-exercise'
                      : 'activity-climb-attempt'
                }
                onClick={() => onSelect(segment.progress)}
                key={segment.id}
              >
                <strong>{segment.label}</strong>
                <span className="num">{segment.duration}</span>
                <span>{segment.details.join(' · ')}</span>
              </button>
            ))}
          </div>
        ) : (
          <EmptyExplanation title="当前没有可验证的分段数据" vc="activity-no-laps">
            {profile.noLapsReason}
          </EmptyExplanation>
        )}
      </section>
    </section>
  )
}

function DevicesPanel({ profile }: { profile: ActivityProfile }) {
  const [filter, setFilter] = useState<DeviceFilter>('all')
  const [openGroups, setOpenGroups] = useState<Set<string>>(
    () => new Set(profile.extensionGroups[0] ? [profile.extensionGroups[0].id] : []),
  )
  const devices = profile.devices.filter((device) => filter === 'all' || device.kind === filter)
  const filterLabels: Array<[DeviceFilter, string]> = [
    ['all', '全部'],
    ['watch', '手表'],
    ['sensor', '传感器'],
    ['data', '数据源'],
    ['unknown', '来源未明确'],
  ]
  return (
    <section
      className="activity-detail__panel"
      data-vc="activity-devices-panel"
      data-testid="detail-panel-devices"
    >
      {profile.parseStatus === 'partial' && (
        <div className="detail-data-banner" data-vc="activity-partial-data">
          <strong>存在未映射或未绑定的数据</strong>
          <span>仅展示可读名称、单位、解释和来源状态齐全的指标。</span>
        </div>
      )}
      <section className="detail-card" data-vc="activity-device-sources">
        <h3>设备与数据来源</h3>
        <p className="detail-card__note">设备角色、厂商/产品、传输协议和字段来源分别表达。</p>
        <div className="detail-filter-row">
          {filterLabels.map(([id, label]) => (
            <button
              type="button"
              className={filter === id ? 'is-active' : ''}
              onClick={() => setFilter(id)}
              key={id}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="detail-device-grid">
          {devices.map((device) => (
            <article
              className="detail-device"
              data-vc="activity-device-card"
              key={`${device.role}-${device.protocol}`}
            >
              <div>
                <strong>{device.role}</strong>
                <span>{device.name}</span>
              </div>
              <em>{device.protocol}</em>
              <dl>
                <div>
                  <dt>软件版本</dt>
                  <dd className="num">{device.version}</dd>
                </div>
                <div>
                  <dt>电量</dt>
                  <dd className="num">{device.battery}</dd>
                </div>
              </dl>
              <div className="detail-device__provides">
                {device.provides.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
      <section className="detail-card" data-vc="activity-extension-metrics">
        <h3>扩展指标</h3>
        <p className="detail-card__note">默认展开第一组，原生字段与 developer field 并列保留。</p>
        <div className="detail-extension-groups">
          {profile.extensionGroups.map((group) => {
            const open = openGroups.has(group.id)
            return (
              <section
                className={open ? 'detail-extension is-open' : 'detail-extension'}
                data-vc="activity-extension-group"
                key={group.id}
              >
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() =>
                    setOpenGroups((current) => {
                      const next = new Set(current)
                      if (next.has(group.id)) next.delete(group.id)
                      else next.add(group.id)
                      return next
                    })
                  }
                >
                  <strong>{group.name}</strong>
                  <span>
                    {group.items.length} 项 · {open ? '收起' : '展开'}
                  </span>
                </button>
                {open && (
                  <div className="detail-extension__body">
                    {group.items.map((item) => (
                      <div data-vc="activity-extension-metric" key={item.label}>
                        <span>{item.label}</span>
                        <strong className="num">
                          {item.value} <small>{item.unit}</small>
                        </strong>
                        <em>{item.source}</em>
                        <p>{item.help}</p>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )
          })}
        </div>
      </section>
    </section>
  )
}

function RawPanel({ profile }: { profile: ActivityProfile }) {
  const [page, setPage] = useState(1)
  const [loadingState, setLoadingState] = useState<'idle' | 'loading' | 'done'>('idle')
  const [retryState, setRetryState] = useState<'idle' | 'loading' | 'done'>('idle')
  const pageCount = Math.max(1, Math.ceil(profile.rawRecords.length / 10))
  const rows = profile.rawRecords.slice((page - 1) * 10, page * 10)
  const runTransition = (setter: (value: 'idle' | 'loading' | 'done') => void) => {
    setter('loading')
    globalThis.setTimeout(() => setter('done'), 300)
  }
  return (
    <section
      className="activity-detail__panel"
      data-vc="activity-raw-panel"
      data-testid="detail-panel-raw"
    >
      <section className="detail-card" data-vc="activity-raw-records">
        <h3>原始数据预览</h3>
        <p className="detail-card__note">默认每页 10 条；缺失值显示原因，不用 0 或 -- 伪装。</p>
        {profile.rawRecords.length ? (
          <>
            <table className="detail-raw-table">
              <thead>
                <tr>
                  <th>采样序号</th>
                  <th>心率 bpm</th>
                  <th>专项字段</th>
                  <th>完整性</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.index}>
                    <td className="num">{String(row.index).padStart(4, '0')}</td>
                    <td className="num">{row.heartRate}</td>
                    <td>{row.specialized}</td>
                    <td>{row.completeness}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="detail-raw-cards">
              {rows.map((row) => (
                <article key={row.index}>
                  {[
                    ['采样序号', String(row.index).padStart(4, '0')],
                    ['心率 bpm', row.heartRate],
                    ['专项字段', row.specialized],
                    ['完整性', row.completeness],
                  ].map(([key, value]) => (
                    <div key={key}>
                      <span>{key}</span>
                      <strong className="num">{value}</strong>
                    </div>
                  ))}
                </article>
              ))}
            </div>
            <div className="detail-pager">
              <button
                type="button"
                disabled={page === 1}
                onClick={() => setPage((value) => value - 1)}
              >
                ‹
              </button>
              <span className="num" data-testid="raw-page-info">
                {page} / {pageCount}
              </span>
              <button
                type="button"
                disabled={page === pageCount}
                onClick={() => setPage((value) => value + 1)}
              >
                ›
              </button>
            </div>
          </>
        ) : (
          <EmptyExplanation title="等待真实 FIT 数据">
            运动 profile 已就绪；绑定样本后才按 10 条分页，不生成演示记录。
          </EmptyExplanation>
        )}
      </section>
      <section className="detail-card" data-vc="activity-parser-diagnostics">
        <h3>解析状态</h3>
        <div className="detail-diagnostics">
          <div>
            <strong>长数据加载</strong>
            <p>
              {loadingState === 'loading'
                ? '正在分批载入，概览仍可使用…'
                : loadingState === 'done'
                  ? '可用记录已载入；表格仍按 10 条分页。'
                  : '先显示已解析摘要，再分批载入长曲线和表格。'}
            </p>
            {loadingState === 'loading' && <div className="detail-skeleton" />}
            <button type="button" onClick={() => runTransition(setLoadingState)}>
              加载长数据
            </button>
          </div>
          <div>
            <strong>解析失败</strong>
            <p>
              {retryState === 'loading'
                ? '正在重新读取 FIT 消息定义…'
                : retryState === 'done'
                  ? '重试完成；未映射字段继续标记为来源未明确。'
                  : '保留文件名、错误阶段和重试入口，不把失败字段显示成 0。'}
            </p>
            {retryState === 'loading' && <div className="detail-skeleton" />}
            <button type="button" onClick={() => runTransition(setRetryState)}>
              重试解析
            </button>
          </div>
        </div>
      </section>
    </section>
  )
}

export function ActivityDetail({ activity, parsed, onDownload, backAction }: ActivityDetailProps) {
  const profile = useMemo(() => buildActivityProfile(activity, parsed), [activity, parsed])
  const [activeTab, setActiveTab] = useState<DetailTab>('overview')
  const [activeChart, setActiveChart] = useState(profile.charts[0]?.id ?? '')
  const [linkedProgress, setLinkedProgress] = useState<number | null>(null)

  return (
    <article
      className="activity-detail"
      data-vc="activity-detail"
      data-testid="activity-detail"
      data-profile={profile.id}
    >
      <div className="activity-detail__crumb">
        {backAction}
        <span>运动记录 / 运动详情</span>
      </div>
      <header className="activity-detail__title-row" data-vc="activity-detail-header">
        <div>
          <h1>运动详情</h1>
          <p>查看本次运动的指标、分段、设备与原始数据</p>
        </div>
        <div className="activity-detail__actions">
          <span className="activity-detail__file num">{profile.fileName}</span>
          <span
            className={
              profile.parseStatus === 'complete'
                ? 'activity-detail__quality'
                : 'activity-detail__quality is-partial'
            }
            data-vc="activity-parse-status"
          >
            {profile.parseStatusLabel}
          </span>
          <button
            type="button"
            className="activity-detail__download"
            data-vc="activity-fit-download"
            data-testid="detail-download"
            disabled={!profile.downloadAvailable}
            onClick={() => profile.downloadAvailable && onDownload?.(activity.id)}
          >
            {profile.downloadAvailable ? '下载原始 FIT' : '未绑定 FIT'}
          </button>
        </div>
      </header>
      <nav className="activity-detail__tabs" aria-label="详情视图" data-vc="activity-detail-tabs">
        {TABS.map(([id, label]) => (
          <button
            type="button"
            className={activeTab === id ? 'is-active' : ''}
            data-vc="activity-detail-tab"
            aria-selected={activeTab === id}
            onClick={() => setActiveTab(id)}
            key={id}
          >
            {label}
          </button>
        ))}
      </nav>
      {activeTab === 'overview' && (
        <OverviewPanel
          profile={profile}
          activeChart={activeChart}
          setActiveChart={setActiveChart}
        />
      )}
      {activeTab === 'charts' && (
        <ChartsPanel
          profile={profile}
          activeChart={activeChart}
          setActiveChart={setActiveChart}
          linkedProgress={linkedProgress}
        />
      )}
      {activeTab === 'segments' && (
        <SegmentsPanel
          profile={profile}
          onSelect={(progress) => {
            setLinkedProgress(progress)
            setActiveTab('charts')
          }}
        />
      )}
      {activeTab === 'devices' && <DevicesPanel profile={profile} />}
      {activeTab === 'raw' && <RawPanel profile={profile} />}
    </article>
  )
}
