import { useState } from 'react'
import { HealthTabs, type HealthTab } from './HealthTabs'
import { HealthLineChart } from './HealthLineChart'
import { SleepStackChart } from './SleepStackChart'
import { MetricTable, type MetricColumn } from './MetricTable'
import { HabitPicker } from './HabitPicker'
import { useBreakpoint } from '../hooks/useBreakpoint'
import {
  formatSleepHm,
  generateHrv,
  generateRestingHr,
  generateSleep,
  generateWeight,
  type HrvRecord,
  type RestingHrRecord,
  type SleepRecord,
  type WeightRecord,
} from './healthData'
import './HealthPage.css'

// Contract C-9: 健康记录 five sub-tabs. Four raw-value series (chart + paginated
// detail table) plus the habit factor logger. All data is deterministic mock
// (G-mock); no system-side derivation of any metric (design §4).

const TABS: readonly HealthTab[] = [
  { id: 'sleep', label: '睡眠' },
  { id: 'weight', label: '体重' },
  { id: 'rhr', label: '静息心率' },
  { id: 'hrv', label: 'HRV' },
  { id: 'habit', label: '习惯' },
]

// Charts read oldest→newest; series are generated newest-first, so reverse the
// recent window before charting.
function recentAsc<T>(rows: T[], count: number): T[] {
  return rows.slice(0, count).reverse()
}

const SLEEP_COLUMNS: MetricColumn<SleepRecord>[] = [
  { key: 'date', header: '日期', render: (r) => r.date, numeric: true },
  { key: 'total', header: '总时长', render: (r) => formatSleepHm(r.totalMin), numeric: true },
  { key: 'deep', header: '深睡', render: (r) => `${r.deepMin} min`, numeric: true },
  { key: 'light', header: '浅睡', render: (r) => `${r.lightMin} min`, numeric: true },
  { key: 'rem', header: 'REM', render: (r) => `${r.remMin} min`, numeric: true },
  { key: 'rhr', header: '静息心率', render: (r) => `${r.restingHr} bpm`, numeric: true },
]

const WEIGHT_COLUMNS: MetricColumn<WeightRecord>[] = [
  { key: 'date', header: '日期', render: (r) => r.date, numeric: true },
  { key: 'weight', header: '体重', render: (r) => `${r.weightKg.toFixed(1)} kg`, numeric: true },
  { key: 'fat', header: '体脂率', render: (r) => `${r.bodyFatPct.toFixed(1)} %`, numeric: true },
  { key: 'muscle', header: '肌肉量', render: (r) => `${r.muscleKg.toFixed(1)} kg`, numeric: true },
  { key: 'water', header: '体水分', render: (r) => `${r.waterPct.toFixed(1)} %`, numeric: true },
]

const RHR_COLUMNS: MetricColumn<RestingHrRecord>[] = [
  { key: 'date', header: '日期', render: (r) => r.date, numeric: true },
  { key: 'resting', header: '静息心率', render: (r) => `${r.restingHr} bpm`, numeric: true },
  { key: 'min', header: '夜间最低', render: (r) => `${r.nightlyMinHr} bpm`, numeric: true },
]

const HRV_COLUMNS: MetricColumn<HrvRecord>[] = [
  { key: 'date', header: '日期', render: (r) => r.date, numeric: true },
  { key: 'hrv', header: 'HRV', render: (r) => `${r.hrvMs} ms`, numeric: true },
]

export function HealthPage() {
  const [tab, setTab] = useState<string>('sleep')
  const breakpoint = useBreakpoint()
  // AC-009b-1: sleep bar count is breakpoint-gated — mobile shows 近 7 天 (7 bars),
  // tablet/desktop/wide show 近 14 天 (14 bars). The window size lives in the title
  // so bar count and label can never drift apart.
  const sleepDays = breakpoint === 'mobile' ? 7 : 14
  // Generated once; the mock series are stable across renders.
  const [sleep] = useState<SleepRecord[]>(generateSleep)
  const [weight] = useState<WeightRecord[]>(generateWeight)
  const [rhr] = useState<RestingHrRecord[]>(generateRestingHr)
  const [hrv] = useState<HrvRecord[]>(generateHrv)

  return (
    <section className="page health" data-testid="page-health">
      <div className="health__head">
        <h1>健康记录</h1>
        <p className="health__intro">
          来自连接器与设备的原始健康数据 · 均为设备原始值，无系统预计算
        </p>
      </div>

      <HealthTabs tabs={TABS} active={tab} onSelect={setTab} />

      {tab === 'sleep' && (
        <div className="health__panel" data-testid="panel-sleep">
          <SleepStackChart records={recentAsc(sleep, sleepDays)} title={`近 ${sleepDays} 天`} />
          <MetricTable
            rows={sleep}
            columns={SLEEP_COLUMNS}
            rowKey={(r) => r.date}
            caption="睡眠明细（深/浅/REM + 静息心率）"
          />
        </div>
      )}

      {tab === 'weight' && (
        <div className="health__panel" data-testid="panel-weight">
          <HealthLineChart
            title="体重趋势（近 30 天）"
            unit="kg"
            colorSlug="accent"
            points={recentAsc(weight, 30).map((r) => ({ date: r.date, value: r.weightKg }))}
            formatValue={(v) => v.toFixed(1)}
          />
          <MetricTable
            rows={weight}
            columns={WEIGHT_COLUMNS}
            rowKey={(r) => r.date}
            caption="体重明细（体重/体脂率/肌肉量/体水分）"
          />
        </div>
      )}

      {tab === 'rhr' && (
        <div className="health__panel" data-testid="panel-rhr">
          <HealthLineChart
            title="静息心率趋势（近 30 天）"
            unit="bpm"
            colorSlug="heart"
            points={recentAsc(rhr, 30).map((r) => ({ date: r.date, value: r.restingHr }))}
          />
          <MetricTable
            rows={rhr}
            columns={RHR_COLUMNS}
            rowKey={(r) => r.date}
            caption="静息心率明细（静息/夜间最低）"
          />
        </div>
      )}

      {tab === 'hrv' && (
        <div className="health__panel" data-testid="panel-hrv">
          <HealthLineChart
            title="夜间 HRV 趋势（近 30 天）"
            unit="ms"
            colorSlug="hrv"
            points={recentAsc(hrv, 30).map((r) => ({ date: r.date, value: r.hrvMs }))}
          />
          <MetricTable
            rows={hrv}
            columns={HRV_COLUMNS}
            rowKey={(r) => r.date}
            caption="HRV 明细（夜间平均）"
          />
        </div>
      )}

      {tab === 'habit' && (
        <div className="health__panel" data-testid="panel-habit">
          <HabitPicker />
        </div>
      )}
    </section>
  )
}
