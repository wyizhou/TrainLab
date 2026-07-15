import { useId, useState, type FormEvent } from 'react'
import { formatDistance, formatDuration } from '../activities/activityData'
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
  const dist = side.distanceKm === null ? '' : ` · ${formatDistance(side.distanceKm)}`
  return `${side.name} · ${formatStartTime(side.startTime)} · ${formatDuration(side.durationSec)}${dist}`
}

export function ConflictModal({ groups, onConfirm, onClose }: ConflictModalProps) {
  const [choices, setChoices] = useState<Record<string, ConflictRegion>>({})
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
            处理疑似重复运动
          </h2>
          <button
            type="button"
            className="conflict-modal__close"
            onClick={onClose}
            aria-label="关闭"
          >
            ✕
          </button>
        </header>

        <form className="conflict-modal__form" onSubmit={handleSubmit}>
          <ul className="conflict-modal__groups">
            {groups.map((group) => (
              <li
                key={group.id}
                className="conflict-modal__group"
                data-testid="conflict-group"
                role="radiogroup"
                aria-label={`${group.cn.name} 与 ${group.global.name}`}
              >
                {regions.map((region) => {
                  const side = group[region]
                  const label = `保留${REGION_LABEL[region]}`
                  return (
                    <label key={region} className="conflict-modal__choice">
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
                          {sideSummary(side)}
                        </span>
                      </span>
                    </label>
                  )
                })}
              </li>
            ))}
          </ul>

          <button
            type="submit"
            className="conflict-modal__confirm"
            data-testid="conflict-confirm"
            disabled={!allChosen}
          >
            确认合并
          </button>
        </form>
      </div>
    </div>
  )
}
