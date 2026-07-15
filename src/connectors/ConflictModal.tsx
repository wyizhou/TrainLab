import { useId, useState, type FormEvent } from 'react'
import { formatDuration } from '../activities/activityData'
import {
  formatStartTime,
  REGION_LABEL,
  type ConflictGroup,
  type ConflictRegion,
  type ConflictSide,
} from './conflictData'
import './ConflictModal.css'

// 双账号合并·逐组保留弹窗 (contract C-12). Lists each suspected-duplicate group
// with the 中国区 / 国际区 candidate side by side; the user picks which to keep
// per group. 「确认合并」is enabled only once every group has a choice, then the
// parent applies the merge and dismisses the banner. Mock-only (G-mock).

type ConflictModalProps = {
  groups: ConflictGroup[]
  onConfirm: (choices: Record<string, ConflictRegion>) => void
  onClose: () => void
}

function sideSummary(side: ConflictSide): string {
  const date = formatStartTime(side.startTime).slice(0, 10)
  const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][
    new Date(`${date}T00:00:00Z`).getUTCDay()
  ]
  const distance =
    side.distanceKm === null ? '—' : `${side.distanceKm.toFixed(side.distanceKm < 10 ? 2 : 1)} km`
  return `${date.slice(5)} ${weekday} · ${distance} · ${formatDuration(side.durationSec)}`
}

export function ConflictModal({ groups, onConfirm, onClose }: ConflictModalProps) {
  const [choices, setChoices] = useState<Record<string, ConflictRegion>>(() =>
    Object.fromEntries(groups.map((group) => [group.id, 'cn'])),
  )
  const titleId = useId()

  const allChosen = groups.every((g) => choices[g.id] !== undefined)

  const choose = (groupId: string, region: ConflictRegion) =>
    setChoices((prev) => ({ ...prev, [groupId]: region }))

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!allChosen) return
    onConfirm(choices)
  }

  const regions: ConflictRegion[] = ['cn', 'global']

  return (
    <div
      className="conflict-modal__backdrop"
      data-testid="conflict-modal-backdrop"
      data-vc="modal-overlay"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="conflict-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="conflict-modal"
        data-vc="modal-conflict"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="conflict-modal__head">
          <h2 id={titleId} className="conflict-modal__title">
            处理重复运动
          </h2>
          <p className="conflict-modal__subtitle">
            以下运动在中国区与国际区同时存在(开始时间 + 时长一致),请选择保留哪一条,另一条将被忽略
          </p>
        </header>

        <form className="conflict-modal__form" onSubmit={handleSubmit}>
          <ul className="conflict-modal__groups" data-vc="conflict-list">
            {groups.map((group) => (
              <li
                key={group.id}
                className="conflict-modal__group"
                data-testid="conflict-group"
                data-vc="conflict-row"
                role="radiogroup"
                aria-label={`${group.cn.name} 与 ${group.global.name}`}
              >
                <div className="conflict-modal__group-head">
                  <strong>{group.cn.name}</strong>
                  <span className="num">{sideSummary(group.cn)}</span>
                </div>
                <div className="conflict-modal__choices">
                  {regions.map((region) => {
                    const side = group[region]
                    const label = `保留${REGION_LABEL[region]}`
                    return (
                      <label
                        key={region}
                        className={
                          choices[group.id] === region
                            ? 'conflict-modal__choice conflict-modal__choice--selected'
                            : 'conflict-modal__choice'
                        }
                      >
                        <input
                          type="radio"
                          name={group.id}
                          data-testid={`conflict-choice-${region}`}
                          checked={choices[group.id] === region}
                          onChange={() => choose(group.id, region)}
                        />
                        <span className="conflict-modal__choice-body">
                          <span className="conflict-modal__choice-label">{label}</span>
                          <span className="conflict-modal__choice-summary num">
                            {side.region === 'cn' ? 'connect.garmin.cn' : 'connect.garmin.com'}
                          </span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              </li>
            ))}
          </ul>

          <div className="conflict-modal__actions">
            <button type="button" className="conflict-modal__later" onClick={onClose}>
              稍后处理
            </button>
            <button
              type="submit"
              className="conflict-modal__confirm"
              data-testid="conflict-confirm"
              disabled={!allChosen}
            >
              确认合并
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
