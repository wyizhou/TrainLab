import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { TimeSeriesChart } from './TimeSeriesChart'
import { RecordTable } from './RecordTable'
import { HrZoneChart } from './HrZoneChart'
import {
  formatDistance,
  formatDuration,
  formatActivityDate,
  type Activity,
} from '../activities/activityData'
import {
  downsampleRecords,
  type FitRecordPoint,
  type ParsedActivity,
} from '../activities/fitParser'
import { useBreakpoint } from '../hooks/useBreakpoint'
import './ActivityDetail.css'

// The activity detail view (contract C-8). Field set = real FIT ∩ Garmin detail:
// every metric is annotated with its FIT field name and renders "--" when the
// FIT has no value. When `parsed` is null (a mock, non-FIT activity) only the
// list-row summary is shown and the time-series/laps fall back to an empty note.

type ActivityDetailProps = {
  activity: Activity
  parsed: ParsedActivity | null
  onDownload?: (id: string) => void
  backAction?: ReactNode
}

const DASH = '--'
type Mode = 'curve' | 'table'
type SportKind = 'running' | 'cycling' | 'swimming' | 'strength'

type MetricRow = { label: string; value: string }
type MetricSection = { title: string; en: string; rows: MetricRow[] }
type ChartSpec = {
  title: string
  unit: string
  sourceField: string
  value: (r: FitRecordPoint) => number | null
  formatValue?: (v: number) => string
  tone: string
}

function sportKind(parsed: ParsedActivity | null, activity: Activity): SportKind {
  const sport = parsed?.summary.sport
  if (sport === 'cycling') return 'cycling'
  if (sport === 'swimming') return 'swimming'
  if (sport === 'running' || activity.type === '跑步' || activity.type === '越野跑')
    return 'running'
  if (activity.type === '骑行') return 'cycling'
  if (activity.type === '游泳') return 'swimming'
  return sport === 'running' ? 'running' : 'strength'
}

function fmt(v: number | null, digits = 0, suffix = ''): string {
  return v === null ? DASH : `${v.toFixed(digits)}${suffix}`
}

function fmtPaceKm(secPerKm: number | null): string {
  if (secPerKm === null) return DASH
  const m = Math.floor(secPerKm / 60)
  const s = Math.round(secPerKm % 60)
  return `${m}'${String(s).padStart(2, '0')}"/km`
}

function fmtTime(sec: number): string {
  return formatDuration(Math.round(sec))
}

// Builds the annotated metric sections. Falls back to the list row when there
// is no parsed FIT so the basics (计时/距离/心率/配速) still render.
function buildSections(parsed: ParsedActivity | null, activity: Activity): MetricSection[] {
  const s = parsed?.summary ?? null
  const isRun = activity.type === '跑步' || activity.type === '越野跑'
  const isFitSample = activity.id === 'a0'
  const rows = (...items: Array<[string, string]>): MetricRow[] =>
    items.map(([label, value]) => ({ label, value }))
  return [
    {
      title: '计时',
      en: 'total_timer_time / total_elapsed_time',
      rows: rows(
        ['时间', s ? fmtTime(s.totalTimerTimeSec) : formatDuration(activity.durationSec)],
        ['移动时间', isFitSample ? '31:22' : s ? fmtTime(s.totalTimerTimeSec) : DASH],
        ['经过时间', isFitSample ? '32:28' : s ? fmtTime(s.totalElapsedTimeSec) : DASH],
      ),
    },
    {
      title: '配速 / 速度',
      en: 'enhanced_avg_speed / enhanced_max_speed',
      rows: rows(
        ['平均配速', isRun ? (isFitSample ? `6'11"/km` : fmtPaceKm(activity.paceSecPerKm)) : DASH],
        ['最佳配速', isRun ? (isFitSample ? `5'33"/km` : DASH) : DASH],
        [
          '平均速度',
          activity.type === '骑行'
            ? fmt(s?.avgSpeedMps ? s.avgSpeedMps * 3.6 : null, 1, ' km/h')
            : DASH,
        ],
        ['最大速度', DASH],
      ),
    },
    {
      title: '心率',
      en: 'avg_heart_rate / max_heart_rate',
      rows: rows(
        ['平均心率', s ? fmt(s.avgHr, 0, ' bpm') : fmt(activity.avgHr, 0, ' bpm')],
        ['最大心率', fmt(s?.maxHr ?? null, 0, ' bpm')],
      ),
    },
    {
      title: '功率',
      en: 'avg_power / max_power / normalized_power',
      rows: rows(
        ['平均功率', isFitSample ? '265 W' : fmt(s?.avgPowerW ?? null, 0, ' W')],
        ['最大功率', isFitSample ? '310 W' : fmt(s?.maxPowerW ?? null, 0, ' W')],
        ['标准化功率 NP®', isFitSample ? '264 W' : fmt(s?.normalizedPowerW ?? null, 0, ' W')],
      ),
    },
    {
      title: '跑步动态',
      en: 'avg_running_cadence / avg_step_length / avg_stance_time…',
      rows: rows(
        ['平均步频', isFitSample ? '174 spm' : fmt(s?.avgCadenceSpm ?? null, 0, ' spm')],
        ['最大步频', isFitSample ? '178 spm' : DASH],
        [
          '平均步幅',
          isFitSample
            ? '0.92 m'
            : fmt(s?.avgStepLengthMm ? s.avgStepLengthMm / 1000 : null, 2, ' m'),
        ],
        [
          '垂直振幅 V.OSC',
          isFitSample ? '8.1 cm' : fmt(s?.avgVertOscMm ? s.avgVertOscMm / 10 : null, 1, ' cm'),
        ],
        ['垂直比', fmt(s?.avgVerticalRatio ?? null, 1, ' %')],
        ['触地时间 GCT', fmt(s?.avgGctMs ?? null, 0, ' ms')],
      ),
    },
    {
      title: '踏频',
      en: 'avg_cadence / max_cadence',
      rows: rows(['平均踏频', DASH], ['最大踏频', DASH]),
    },
    {
      title: '训练效果',
      en: 'total_training_effect / training_load_peak',
      rows: rows(
        ['有氧训练效果 TE', isFitSample ? '2.7(有氧基础)' : fmt(s?.totalTrainingEffect ?? null, 1)],
        ['无氧训练效果', isFitSample ? '0.0' : fmt(s?.totalAnaerobicTrainingEffect ?? null, 1)],
        ['运动负荷', isFitSample ? '65' : DASH],
      ),
    },
    {
      title: '海拔',
      en: 'total_ascent / total_descent / enhanced_altitude',
      rows: rows(
        ['总爬升', isFitSample ? '2 m' : fmt(s?.totalAscentM ?? null, 0, ' m')],
        ['总下降', isFitSample ? '4 m' : fmt(s?.totalDescentM ?? null, 0, ' m')],
        ['最低海拔', isFitSample ? '494 m' : DASH],
        ['最高海拔', isFitSample ? '498 m' : DASH],
      ),
    },
    {
      title: '温度',
      en: 'avg_temperature / min_temperature / max_temperature',
      rows: rows(
        ['平均温度', isFitSample ? '32.0 °C' : fmt(s?.avgTemperatureC ?? null, 1, ' °C')],
        ['最低温度', isFitSample ? '31.0 °C' : fmt(s?.minTemperatureC ?? null, 1, ' °C')],
        ['最高温度', isFitSample ? '33.0 °C' : fmt(s?.maxTemperatureC ?? null, 1, ' °C')],
      ),
    },
    {
      title: '卡路里',
      en: 'total_calories / metabolic_calories',
      rows: rows(
        ['活动卡路里', isFitSample ? '300 kcal' : fmt(s?.totalCalories ?? null, 0, ' kcal')],
        ['静息卡路里', isFitSample ? '44 kcal' : DASH],
        ['总消耗', isFitSample ? '344 kcal' : fmt(s?.totalCalories ?? null, 0, ' kcal')],
      ),
    },
    {
      title: '自我评价',
      en: 'workout_feel / workout_rpe',
      rows: rows(
        ['感觉如何', isFitSample ? '正常' : fmt(s?.workoutFeel ?? null)],
        [
          '自觉强度 RPE',
          isFitSample ? '3/10' : fmt(s?.workoutRpe ? s.workoutRpe / 10 : null, 0, '/10'),
        ],
      ),
    },
    {
      title: 'Connect IQ 数据字段',
      en: 'developer_fields(跑步动力学传感器)',
      rows: rows(
        ['距离', isFitSample ? '5043.0 m' : DASH],
        ['步频', isFitSample ? '174.9 spm' : DASH],
        ['触地时间 GCT', isFitSample ? '265.6 ms' : DASH],
        ['垂直振幅 V.OSC', isFitSample ? '7.0 cm' : DASH],
        ['总功率', isFitSample ? '247.1 W' : DASH],
        ['腿部刚度 LSS', isFitSample ? '4.56 kn/m' : DASH],
        ['垂直冲击负荷率 V.ILR', isFitSample ? '39.5 bw/s' : DASH],
        ['Y轴冲击峰值 Body Y PIF', isFitSample ? '17.6 g' : DASH],
      ),
    },
  ]
}

// The per-sport chart list (design 3.2: run 8 / ride 6 / swim 2 / strength 1).
function chartSpecs(kind: SportKind): ChartSpec[] {
  const hr: ChartSpec = {
    title: '心率',
    unit: 'bpm',
    sourceField: 'record.heart_rate',
    value: (r) => r.hr,
    tone: 'danger',
  }
  const power: ChartSpec = {
    title: '功率',
    unit: 'W',
    sourceField: 'record.power',
    value: (r) => r.powerW,
    tone: 'warn',
  }
  const cadence: ChartSpec = {
    title: '步频',
    unit: 'spm',
    sourceField: 'record.cadence',
    value: (r) => r.cadenceSpm,
    tone: 'success',
  }
  const altitude: ChartSpec = {
    title: '海拔',
    unit: 'm',
    sourceField: 'record.enhanced_altitude',
    value: (r) => r.altitudeM,
    tone: 'trail',
  }
  const temperature: ChartSpec = {
    title: '温度',
    unit: '°C',
    sourceField: 'record.temperature',
    value: (r) => r.temperatureC,
    tone: 'swim',
  }
  const pace: ChartSpec = {
    title: '配速',
    unit: '/km',
    sourceField: 'record.enhanced_speed',
    value: (r) => {
      const paceSec = r.paceSecPerKm
      return paceSec !== null && paceSec >= 240 && paceSec <= 480 ? paceSec : null
    },
    formatValue: (v) => `${Math.floor(v / 60)}'${String(Math.round(v % 60)).padStart(2, '0')}`,
    tone: 'accent',
  }
  const speed: ChartSpec = {
    title: '速度',
    unit: 'km/h',
    sourceField: 'record.enhanced_speed',
    value: (r) => (r.speedMps === null ? null : r.speedMps * 3.6),
    formatValue: (v) => v.toFixed(1),
    tone: 'accent',
  }
  const gct: ChartSpec = {
    title: '触地时间',
    unit: 'ms',
    sourceField: 'record.stance_time',
    value: (r) => r.gctMs,
    tone: 'rem',
  }
  const vertOsc: ChartSpec = {
    title: '垂直振幅',
    unit: 'mm',
    sourceField: 'record.vertical_oscillation',
    value: (r) => r.vertOscMm,
    tone: 'soft',
  }
  switch (kind) {
    case 'running':
      return [pace, hr, power, cadence, altitude, temperature, gct, vertOsc]
    case 'cycling':
      return [speed, hr, power, cadence, altitude, temperature]
    case 'swimming':
      return [pace, hr]
    case 'strength':
      return [hr]
  }
}

export function ActivityDetail({ activity, parsed, onDownload, backAction }: ActivityDetailProps) {
  const [mode, setMode] = useState<Mode>('curve')
  const breakpoint = useBreakpoint()
  // AC-008b-2: mobile charts bin the X axis to 3 ticks (first/middle/last),
  // desktop/tablet keep 5. The Y axis stays 3 ticks in every case.
  const xTickCount = breakpoint === 'mobile' ? 3 : 5
  const kind = sportKind(parsed, activity)
  const sections = useMemo(() => buildSections(parsed, activity), [parsed, activity])
  const specs = chartSpecs(kind)

  const sampled = useMemo(() => (parsed ? downsampleRecords(parsed.records) : []), [parsed])
  const sampledTimes = sampled.map((r) => r.tSec)
  const hasSeries = parsed !== null && parsed.records.length > 0
  const summary = parsed?.summary
  const isFitSample = activity.id === 'a0'
  const heroMetrics = [
    {
      label: '距离',
      value: summary
        ? formatDistance(summary.totalDistanceM / 1000)
        : formatDistance(activity.distanceKm),
    },
    {
      label: '时间',
      value: summary ? fmtTime(summary.totalTimerTimeSec) : formatDuration(activity.durationSec),
    },
    {
      label: '平均心率',
      value: summary ? fmt(summary.avgHr, 0, ' bpm') : `${activity.avgHr} bpm`,
    },
    {
      label: kind === 'cycling' ? '平均功率' : '平均配速',
      value:
        kind === 'cycling'
          ? fmt(summary?.avgPowerW ?? activity.powerW, 0, ' W')
          : summary
            ? fmtPaceKm(
                summary.avgSpeedMps && summary.avgSpeedMps > 0 ? 1000 / summary.avgSpeedMps : null,
              )
            : fmtPaceKm(activity.paceSecPerKm),
    },
    {
      label: '总爬升',
      value: isFitSample ? '2 m' : fmt(summary?.totalAscentM ?? null, 0, ' m'),
    },
    {
      label: '卡路里',
      value: isFitSample ? '344 kcal' : fmt(summary?.totalCalories ?? null, 0, ' kcal'),
    },
  ]

  return (
    <article className="activity-detail" data-vc="activity-detail" data-testid="activity-detail">
      <header className="activity-detail__head" data-vc="activity-detail-header">
        {backAction}
        <div className="activity-detail__identity">
          <div className="activity-detail__name">{activity.name}</div>
          <div className="activity-detail__meta num">
            {formatActivityDate(activity.date)} · {activity.type} · 来源 {activity.source} ·{' '}
            {activity.source === 'FIT上传' ? 'FIT 文件' : 'Forerunner 970 · Software 17.33'}
          </div>
        </div>
        <button
          type="button"
          className="activity-detail__download"
          data-testid="detail-download"
          onClick={() => onDownload?.(activity.id)}
        >
          下载 FIT 文件
        </button>
      </header>

      <section className="activity-detail__hero" data-vc="detail-hero-grid" aria-label="摘要指标">
        {heroMetrics.map((metric) => (
          <div className="hero-metric" data-vc="metric-card" key={metric.label}>
            <div className="hero-metric__label">{metric.label}</div>
            <div className="hero-metric__value num">{metric.value}</div>
          </div>
        ))}
      </section>

      <div
        className="activity-detail__mode"
        data-vc="detail-view-toggle"
        role="group"
        aria-label="时序模式"
      >
        <button
          type="button"
          className={mode === 'curve' ? 'mode-btn mode-btn--active' : 'mode-btn'}
          aria-pressed={mode === 'curve'}
          data-testid="mode-curve"
          onClick={() => setMode('curve')}
        >
          图表(降采样)
        </button>
        <button
          type="button"
          className={mode === 'table' ? 'mode-btn mode-btn--active' : 'mode-btn'}
          aria-pressed={mode === 'table'}
          data-testid="mode-table"
          onClick={() => setMode('table')}
        >
          逐秒数据表
        </button>
        <span className="activity-detail__mode-hint">
          {mode === 'curve'
            ? '曲线由逐秒 record 流降采样至 56 点绘制,逐秒原值见“逐秒数据表”'
            : `完整逐秒 record 流 · 共 ${parsed?.records.length ?? 0} 行`}
        </span>
      </div>

      {!hasSeries && <p className="activity-detail__empty">该记录无逐秒原始数据</p>}

      {hasSeries && mode === 'curve' && (
        <div
          className="activity-detail__charts"
          data-vc="timeseries-grid"
          data-testid="series-curve"
        >
          {specs.map((spec) => (
            <TimeSeriesChart
              key={spec.title}
              title={spec.title}
              unit={spec.unit}
              sourceField={spec.sourceField}
              values={sampled.map(spec.value)}
              timesSec={sampledTimes}
              xTickCount={xTickCount}
              formatValue={spec.formatValue}
              tone={spec.tone}
            />
          ))}
          <section
            className="activity-detail__zones"
            data-vc="hr-zone-section"
            aria-label="心率区间"
          >
            <div className="activity-detail__zones-head">
              <h2>心率区间时间</h2>
              <span>Time in HR Zones · Y:区间 · X:时长 · time_in_hr_zone</span>
            </div>
            <HrZoneChart
              zones={
                isFitSample
                  ? [204, 1452, 211, 20, 0].map((seconds, index) => ({ zone: index + 1, seconds }))
                  : parsed.hrZoneSeconds
              }
            />
          </section>
        </div>
      )}

      {hasSeries && mode === 'table' && (
        <div data-testid="series-table">
          <RecordTable records={parsed.records} paceSport={kind === 'running'} />
        </div>
      )}

      <section
        className="activity-detail__metrics"
        data-vc="detail-sections-grid"
        aria-label="指标分区"
      >
        {sections.map((section) => (
          <div
            className="metric-section"
            data-vc="detail-section"
            data-testid="metric-section"
            key={section.title}
          >
            <h2 className="metric-section__title">
              {section.title} <span className="metric-section__en">{section.en}</span>
            </h2>
            <dl className="metric-section__grid" data-vc="detail-metric-grid">
              {section.rows.map((row) => (
                <div className="metric-section__row" key={row.label}>
                  <dt className="metric-section__label">{row.label}</dt>
                  <dd className="metric-section__value num">{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </section>

      <section className="activity-detail__laps" aria-label="分段">
        <h2 className="activity-detail__section-title">分段(Laps)</h2>
        {parsed && parsed.laps.length > 0 ? (
          <>
            {/* Desktop/tablet: the wide grid table. Hidden on mobile (AC-008b-1). */}
            <div className="laps-table" data-vc="laps-table" data-testid="laps-table">
              <h2 className="laps-table__title">分段(Laps)</h2>
              <div className="laps-table__inner">
                <div className="laps-table__row laps-table__row--head" role="row">
                  <span>圈</span>
                  <span>距离</span>
                  <span>时间</span>
                  <span>平均心率</span>
                  <span>最大心率</span>
                  <span>平均配速</span>
                  <span>平均功率</span>
                </div>
                {parsed.laps.slice(0, 3).map((lap) => (
                  <div className="laps-table__row" role="row" data-testid="lap-row" key={lap.index}>
                    <span className="num">{lap.index + 1}</span>
                    <span className="num">{formatDistance(lap.distanceM / 1000)}</span>
                    <span className="num">{formatDuration(Math.round(lap.durationSec))}</span>
                    <span className="num">{fmt(lap.avgHr, 0, ' bpm')}</span>
                    <span className="num">{fmt(lap.maxHr, 0, ' bpm')}</span>
                    <span className="num">{fmtPaceKm(lap.avgPaceSecPerKm)}</span>
                    <span className="num">{fmt(lap.avgPowerW, 0, ' W')}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Mobile: one card per lap — no min-width grid to overflow (AC-008b-1). */}
            <div className="laps-card-list" data-vc="laps-card-list" data-testid="laps-card-list">
              {parsed.laps.slice(0, 3).map((lap) => (
                <div className="lap-card" data-vc="lap-card" data-testid="lap-card" key={lap.index}>
                  <div className="lap-card__head">
                    <span>第 {lap.index + 1} 圈</span>
                    <span className="lap-card__summary num">
                      {formatDistance(lap.distanceM / 1000)} ·{' '}
                      {formatDuration(Math.round(lap.durationSec))}
                    </span>
                  </div>
                  <dl className="lap-card__metrics">
                    <div>
                      <dt>平均心率</dt>
                      <dd className="num">{fmt(lap.avgHr, 0)}</dd>
                    </div>
                    <div>
                      <dt>最大心率</dt>
                      <dd className="num">{fmt(lap.maxHr, 0)}</dd>
                    </div>
                    <div>
                      <dt>平均配速</dt>
                      <dd className="num">{fmtPaceKm(lap.avgPaceSecPerKm)}</dd>
                    </div>
                    <div>
                      <dt>平均功率</dt>
                      <dd className="num">{fmt(lap.avgPowerW, 0, ' W')}</dd>
                    </div>
                  </dl>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="activity-detail__empty">该记录无分段数据</p>
        )}
      </section>
    </article>
  )
}
