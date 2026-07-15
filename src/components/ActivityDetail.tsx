import { useMemo, useState } from 'react'
import { TimeSeriesChart } from './TimeSeriesChart'
import { RecordTable } from './RecordTable'
import { HrZoneChart } from './HrZoneChart'
import {
  fitFileName,
  formatDistance,
  formatDuration,
  TYPE_DOT_SLUG,
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
}

const DASH = '--'
type Mode = 'curve' | 'table'
type SportKind = 'running' | 'cycling' | 'swimming' | 'strength'

type MetricRow = { label: string; value: string; field: string }
type MetricSection = { title: string; rows: MetricRow[] }
type ChartSpec = {
  title: string
  unit: string
  sourceField: string
  value: (r: FitRecordPoint) => number | null
  formatValue?: (v: number) => string
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
  return [
    {
      title: '计时',
      rows: [
        {
          label: '总耗时',
          value: s ? fmtTime(s.totalElapsedTimeSec) : formatDuration(activity.durationSec),
          field: 'total_elapsed_time',
        },
        {
          label: '计时时间',
          value: s ? fmtTime(s.totalTimerTimeSec) : formatDuration(activity.durationSec),
          field: 'total_timer_time',
        },
      ],
    },
    {
      title: '距离',
      rows: [
        {
          label: '总距离',
          value: s ? formatDistance(s.totalDistanceM / 1000) : formatDistance(activity.distanceKm),
          field: 'total_distance',
        },
      ],
    },
    {
      title: '配速 / 速度',
      rows: [
        {
          label: '平均配速',
          value: s
            ? fmtPaceKm(s.avgSpeedMps && s.avgSpeedMps > 0 ? 1000 / s.avgSpeedMps : null)
            : fmtPaceKm(activity.paceSecPerKm),
          field: 'enhanced_avg_speed',
        },
        {
          label: '平均速度',
          value: fmt(s?.avgSpeedMps ? s.avgSpeedMps * 3.6 : null, 1, ' km/h'),
          field: 'enhanced_avg_speed',
        },
      ],
    },
    {
      title: '心率',
      rows: [
        {
          label: '平均心率',
          value: s ? fmt(s.avgHr, 0, ' bpm') : fmt(activity.avgHr, 0, ' bpm'),
          field: 'avg_heart_rate',
        },
        { label: '最大心率', value: fmt(s?.maxHr ?? null, 0, ' bpm'), field: 'max_heart_rate' },
      ],
    },
    {
      title: '功率',
      rows: [
        { label: '平均功率', value: fmt(s?.avgPowerW ?? null, 0, ' W'), field: 'avg_power' },
        { label: '最大功率', value: fmt(s?.maxPowerW ?? null, 0, ' W'), field: 'max_power' },
        {
          label: '标准化功率 NP®',
          value: fmt(s?.normalizedPowerW ?? null, 0, ' W'),
          field: 'normalized_power',
        },
      ],
    },
    {
      title: '跑步动态',
      rows: [
        {
          label: '触地时间 GCT',
          value: fmt(s?.avgGctMs ?? null, 0, ' ms'),
          field: 'avg_stance_time',
        },
        {
          label: '垂直振幅 V.OSC',
          value: fmt(s?.avgVertOscMm ?? null, 1, ' mm'),
          field: 'avg_vertical_oscillation',
        },
        {
          label: '垂直比',
          value: fmt(s?.avgVerticalRatio ?? null, 1, ' %'),
          field: 'avg_vertical_ratio',
        },
        {
          label: '步幅',
          value: fmt(s?.avgStepLengthMm ?? null, 0, ' mm'),
          field: 'avg_step_length',
        },
        { label: '腿部刚度 LSS', value: fmt(s?.avgLSS ?? null, 2, ' kN/m'), field: 'dr_s_avg_LSS' },
        {
          label: '垂直负荷率 V.ILR',
          value: fmt(s?.avgVILR ?? null, 1, ' bw/s'),
          field: 'dr_s_avg_v_ILR',
        },
        {
          label: 'Body Y PIF',
          value: fmt(s?.avgBodyYPIF ?? null, 1, ' g'),
          field: 'dr_s_avg_body_Y_PIF',
        },
      ],
    },
    {
      title: '步频 / 踏频',
      rows: [
        {
          label: '平均步频',
          value: fmt(s?.avgCadenceSpm ?? null, 0, ' spm'),
          field: 'avg_cadence',
        },
      ],
    },
    {
      title: '训练效果',
      rows: [
        {
          label: '有氧训练效果',
          value: fmt(s?.totalTrainingEffect ?? null, 1),
          field: 'total_training_effect',
        },
        {
          label: '无氧训练效果',
          value: fmt(s?.totalAnaerobicTrainingEffect ?? null, 1),
          field: 'total_anaerobic_training_effect',
        },
      ],
    },
    {
      title: '海拔',
      rows: [
        { label: '累计爬升', value: fmt(s?.totalAscentM ?? null, 0, ' m'), field: 'total_ascent' },
        {
          label: '累计下降',
          value: fmt(s?.totalDescentM ?? null, 0, ' m'),
          field: 'total_descent',
        },
      ],
    },
    {
      title: '温度',
      rows: [
        {
          label: '平均温度',
          value: fmt(s?.avgTemperatureC ?? null, 0, ' °C'),
          field: 'avg_temperature',
        },
        {
          label: '最高温度',
          value: fmt(s?.maxTemperatureC ?? null, 0, ' °C'),
          field: 'max_temperature',
        },
        {
          label: '最低温度',
          value: fmt(s?.minTemperatureC ?? null, 0, ' °C'),
          field: 'min_temperature',
        },
      ],
    },
    {
      title: '卡路里',
      rows: [
        {
          label: '总卡路里',
          value: fmt(s?.totalCalories ?? null, 0, ' kcal'),
          field: 'total_calories',
        },
      ],
    },
    {
      title: '自我评价',
      rows: [
        {
          label: '主观感觉',
          value: fmt(s?.workoutFeel ?? null, 0, ' / 100'),
          field: 'workout_feel',
        },
        {
          label: 'RPE',
          value: fmt(s?.workoutRpe ? s.workoutRpe / 10 : null, 0, ' / 10'),
          field: 'workout_rpe',
        },
      ],
    },
  ]
}

// The per-sport chart list (design 3.2: run 8 / ride 6 / swim 2 / strength 1).
function chartSpecs(kind: SportKind): ChartSpec[] {
  const hr: ChartSpec = {
    title: '心率',
    unit: 'bpm',
    sourceField: 'heart_rate',
    value: (r) => r.hr,
  }
  const power: ChartSpec = {
    title: '功率',
    unit: 'W',
    sourceField: 'power',
    value: (r) => r.powerW,
  }
  const cadence: ChartSpec = {
    title: '步频',
    unit: 'spm',
    sourceField: 'cadence',
    value: (r) => r.cadenceSpm,
  }
  const altitude: ChartSpec = {
    title: '海拔',
    unit: 'm',
    sourceField: 'enhanced_altitude',
    value: (r) => r.altitudeM,
  }
  const temperature: ChartSpec = {
    title: '温度',
    unit: '°C',
    sourceField: 'temperature',
    value: (r) => r.temperatureC,
  }
  const pace: ChartSpec = {
    title: '配速',
    unit: '/km',
    sourceField: 'enhanced_speed',
    value: (r) => r.paceSecPerKm,
    formatValue: (v) => `${Math.floor(v / 60)}'${String(Math.round(v % 60)).padStart(2, '0')}`,
  }
  const speed: ChartSpec = {
    title: '速度',
    unit: 'km/h',
    sourceField: 'enhanced_speed',
    value: (r) => (r.speedMps === null ? null : r.speedMps * 3.6),
    formatValue: (v) => v.toFixed(1),
  }
  const gct: ChartSpec = {
    title: '触地时间',
    unit: 'ms',
    sourceField: 'stance_time',
    value: (r) => r.gctMs,
  }
  const vertOsc: ChartSpec = {
    title: '垂直振幅',
    unit: 'mm',
    sourceField: 'vertical_oscillation',
    value: (r) => r.vertOscMm,
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

export function ActivityDetail({ activity, parsed, onDownload }: ActivityDetailProps) {
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

  return (
    <article className="activity-detail" data-testid="activity-detail">
      <header className="activity-detail__head">
        <div className="activity-detail__title">
          <span className={`activity-dot activity-dot--${TYPE_DOT_SLUG[activity.type]}`} />
          <h1>{activity.name}</h1>
        </div>
        <p className="activity-detail__meta num">
          {activity.date} · {activity.type} · {activity.source}
        </p>
        <button
          type="button"
          className="activity-detail__download"
          data-testid="detail-download"
          onClick={() => onDownload?.(activity.id)}
        >
          下载 FIT 文件（{fitFileName(activity)}）
        </button>
      </header>

      <section className="activity-detail__metrics" aria-label="指标分区">
        {sections.map((section) => (
          <div
            className="metric-section"
            data-vc="metric-card"
            data-testid="metric-section"
            key={section.title}
          >
            <h2 className="metric-section__title">{section.title}</h2>
            <dl className="metric-section__grid">
              {section.rows.map((row) => (
                <div className="metric-section__row" key={row.label}>
                  <dt className="metric-section__label">
                    {row.label}
                    <span className="metric-section__field num">{row.field}</span>
                  </dt>
                  <dd className="metric-section__value num">{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </section>

      <section className="activity-detail__zones" aria-label="心率区间">
        <h2 className="activity-detail__section-title">心率区间（time_in_hr_zone）</h2>
        {hasSeries ? (
          <HrZoneChart zones={parsed.hrZoneSeconds} />
        ) : (
          <p className="activity-detail__empty">该记录无心率区间数据</p>
        )}
      </section>

      <section className="activity-detail__series" aria-label="时序数据">
        <div className="activity-detail__series-head">
          <h2 className="activity-detail__section-title">时序数据</h2>
          <div className="activity-detail__mode" role="group" aria-label="时序模式">
            <button
              type="button"
              className={mode === 'curve' ? 'mode-btn mode-btn--active' : 'mode-btn'}
              aria-pressed={mode === 'curve'}
              data-testid="mode-curve"
              onClick={() => setMode('curve')}
            >
              降采样曲线
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
          </div>
        </div>

        {!hasSeries && <p className="activity-detail__empty">该记录无逐秒原始数据</p>}

        {hasSeries && mode === 'curve' && (
          <div className="activity-detail__charts" data-testid="series-curve">
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
              />
            ))}
          </div>
        )}

        {hasSeries && mode === 'table' && (
          <div data-testid="series-table">
            <RecordTable records={parsed.records} paceSport={kind === 'running'} />
          </div>
        )}
      </section>

      <section className="activity-detail__laps" aria-label="分段">
        <h2 className="activity-detail__section-title">分段 Laps</h2>
        {parsed && parsed.laps.length > 0 ? (
          <>
            {/* Desktop/tablet: the wide grid table. Hidden on mobile (AC-008b-1). */}
            <div className="laps-table" data-testid="laps-table">
              <div className="laps-table__row laps-table__row--head" role="row">
                <span>#</span>
                <span>距离</span>
                <span>时长</span>
                <span>平均心率</span>
                <span>平均配速</span>
                <span>平均功率</span>
              </div>
              {parsed.laps.map((lap) => (
                <div className="laps-table__row" role="row" data-testid="lap-row" key={lap.index}>
                  <span className="num">{lap.index + 1}</span>
                  <span className="num">{formatDistance(lap.distanceM / 1000)}</span>
                  <span className="num">{formatDuration(Math.round(lap.durationSec))}</span>
                  <span className="num">{fmt(lap.avgHr, 0)}</span>
                  <span className="num">{fmtPaceKm(lap.avgPaceSecPerKm)}</span>
                  <span className="num">{fmt(lap.avgPowerW, 0, ' W')}</span>
                </div>
              ))}
            </div>

            {/* Mobile: one card per lap — no min-width grid to overflow (AC-008b-1). */}
            <div className="laps-card-list" data-testid="laps-card-list">
              {parsed.laps.map((lap) => (
                <div className="lap-card" data-testid="lap-card" key={lap.index}>
                  <div className="lap-card__head">第 {lap.index + 1} 圈</div>
                  <dl className="lap-card__metrics">
                    <div>
                      <dt>距离</dt>
                      <dd className="num">{formatDistance(lap.distanceM / 1000)}</dd>
                    </div>
                    <div>
                      <dt>时长</dt>
                      <dd className="num">{formatDuration(Math.round(lap.durationSec))}</dd>
                    </div>
                    <div>
                      <dt>平均心率</dt>
                      <dd className="num">{fmt(lap.avgHr, 0)}</dd>
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
