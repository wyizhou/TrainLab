import { useMemo, useState } from 'react'
import { Pager, type PageSize } from './Pager'
import type { FitRecordPoint } from '../activities/fitParser'
import './RecordTable.css'

// The per-second data table (contract C-8 逐秒数据表): one row per record, paged
// 20/50/100, row count = activity seconds. Run/trail show pace; others speed.

type RecordTableProps = {
  records: FitRecordPoint[]
  // Run / trail render 配速 (per km); ride / swim / strength render 速度 (km/h).
  paceSport: boolean
}

const DASH = '--'

function fmtTime(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

function fmtPace(secPerKm: number | null): string {
  if (secPerKm === null) return DASH
  const m = Math.floor(secPerKm / 60)
  const s = Math.round(secPerKm % 60)
  return `${m}'${String(s).padStart(2, '0')}"`
}

function fmtNum(v: number | null, digits = 0, suffix = ''): string {
  return v === null ? DASH : `${v.toFixed(digits)}${suffix}`
}

export function RecordTable({ records, paceSport }: RecordTableProps) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState<PageSize>(20)

  const pageCount = Math.max(1, Math.ceil(records.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const slice = useMemo(
    () => records.slice(safePage * pageSize, (safePage + 1) * pageSize),
    [records, safePage, pageSize],
  )

  const paceOrSpeedHead = paceSport ? '配速' : '速度'
  const paceOrSpeed = (r: FitRecordPoint): string =>
    paceSport ? fmtPace(r.paceSecPerKm) : fmtNum(r.speedMps === null ? null : r.speedMps * 3.6, 1)

  return (
    <div className="record-table" data-testid="record-table">
      {/* Desktop/tablet: the min-width:820px grid. Hidden on mobile (AC-008b-1). */}
      <div className="record-table__grid">
        <div className="record-table__row record-table__row--head" role="row">
          <span>时间</span>
          <span>距离</span>
          <span>{paceOrSpeedHead}</span>
          <span>心率</span>
          <span>功率</span>
          <span>步频</span>
          <span>海拔</span>
          <span>温度</span>
        </div>
        {slice.map((r, i) => (
          <div
            className="record-table__row"
            role="row"
            data-testid="record-row"
            key={safePage * pageSize + i}
          >
            <span className="num">{fmtTime(r.tSec)}</span>
            <span className="num">
              {fmtNum(r.distanceM === null ? null : r.distanceM / 1000, 2)}
            </span>
            <span className="num">{paceOrSpeed(r)}</span>
            <span className="num">{fmtNum(r.hr)}</span>
            <span className="num">{fmtNum(r.powerW)}</span>
            <span className="num">{fmtNum(r.cadenceSpm)}</span>
            <span className="num">{fmtNum(r.altitudeM, 1)}</span>
            <span className="num">{fmtNum(r.temperatureC)}</span>
          </div>
        ))}
      </div>

      {/* Mobile: one card per second — no wide grid to overflow (AC-008b-1). Same
          paged slice, so paging behaviour is shared with the grid above. */}
      <div className="record-card-list" data-testid="record-card-list">
        {slice.map((r, i) => (
          <div className="record-card" data-testid="record-card" key={safePage * pageSize + i}>
            <span className="record-card__time num">{fmtTime(r.tSec)}</span>
            <dl className="record-card__metrics">
              <div>
                <dt>距离</dt>
                <dd className="num">
                  {fmtNum(r.distanceM === null ? null : r.distanceM / 1000, 2)}
                </dd>
              </div>
              <div>
                <dt>{paceOrSpeedHead}</dt>
                <dd className="num">{paceOrSpeed(r)}</dd>
              </div>
              <div>
                <dt>心率</dt>
                <dd className="num">{fmtNum(r.hr)}</dd>
              </div>
              <div>
                <dt>功率</dt>
                <dd className="num">{fmtNum(r.powerW)}</dd>
              </div>
              <div>
                <dt>步频</dt>
                <dd className="num">{fmtNum(r.cadenceSpm)}</dd>
              </div>
              <div>
                <dt>海拔</dt>
                <dd className="num">{fmtNum(r.altitudeM, 1)}</dd>
              </div>
              <div>
                <dt>温度</dt>
                <dd className="num">{fmtNum(r.temperatureC)}</dd>
              </div>
            </dl>
          </div>
        ))}
      </div>
      <Pager
        total={records.length}
        page={safePage}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size)
          setPage(0)
        }}
      />
    </div>
  )
}
