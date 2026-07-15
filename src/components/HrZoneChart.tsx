import { hrZoneRanges, type HrZoneConfig } from '../activities/hrZones'
import { useHrZoneConfig } from '../settings/settingsStore'
import type { FitHrZoneTime } from '../activities/fitParser'
import './HrZoneChart.css'

// Horizontal HR-zone time bars (contract C-8). Bar length = FIT time_in_hr_zone
// (raw stored value); the Z1–Z5 boundary labels come from the 区间设定 config in
// the settings store (C-14) — the detail page reads whatever the settings page
// wrote. A caller may still pin an explicit config. System never recomputes the
// times from these boundaries.

type HrZoneChartProps = {
  zones: FitHrZoneTime[]
  config?: HrZoneConfig
}

function fmtDuration(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export function HrZoneChart({ zones, config }: HrZoneChartProps) {
  const stored = useHrZoneConfig()
  const ranges = hrZoneRanges(config ?? stored)
  const max = Math.max(1, ...zones.map((z) => z.seconds))
  const total = Math.max(
    1,
    zones.reduce((sum, z) => sum + z.seconds, 0),
  )

  return (
    <div className="hr-zone" data-testid="hr-zone">
      {/* Compact distribution bar (C-8 AC-008c-2): a single hr-zone-bar whose five
          direct children are the Z1–Z5 segments in order, each in its zone colour;
          widths are time_in_hr_zone / total. Bar height 16 / radius 4. */}
      <div className="hr-zone-bar" data-vc="hr-zone-bar" data-testid="hr-zone-bar">
        {ranges.map((range) => {
          const seconds = zones.find((z) => z.zone === range.zone)?.seconds ?? 0
          return (
            <span
              className={`hr-zone-bar__seg hr-zone-bar__seg--z${range.zone}`}
              style={{ width: `${(seconds / total) * 100}%` }}
              key={range.zone}
            />
          )
        })}
      </div>
      {ranges.map((range) => {
        const bucket = zones.find((z) => z.zone === range.zone)
        const seconds = bucket?.seconds ?? 0
        const pct = (seconds / max) * 100
        return (
          <div className="hr-zone__row" data-testid="hr-zone-row" key={range.zone}>
            <span className="hr-zone__label">Z{range.zone}</span>
            <span className="hr-zone__bound num">
              {range.lo}–{range.hi}
            </span>
            <span className="hr-zone__track">
              <span
                className={`hr-zone__fill hr-zone__fill--z${range.zone}`}
                style={{ width: `${pct}%` }}
              />
            </span>
            <span className="hr-zone__time num">{fmtDuration(seconds)}</span>
          </div>
        )
      })}
    </div>
  )
}
