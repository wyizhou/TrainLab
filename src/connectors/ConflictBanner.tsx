import './ConflictBanner.css'

// 双账号合并·页顶警示横幅 (contract C-12). Shown when reconciling a newly
// connected region surfaces suspected duplicate activities that cannot be
// auto-decided. 「处理重复」opens the ConflictModal; once every group is
// resolved the parent drops the banner.

type ConflictBannerProps = {
  // Number of suspected-duplicate groups awaiting manual resolution.
  count: number
  onResolve: () => void
}

export function ConflictBanner({ count, onResolve }: ConflictBannerProps) {
  return (
    <div
      className="conflict-banner"
      role="alert"
      data-vc="conflict-banner"
      data-testid="conflict-banner"
    >
      <span className="conflict-banner__icon" aria-hidden="true">
        ⚠
      </span>
      <span className="conflict-banner__text">
        中国区与国际区发现 <span className="num">{count}</span> 组疑似重复运动,需要你确认保留哪一条
      </span>
      <button
        type="button"
        className="conflict-banner__action"
        data-testid="conflict-resolve"
        onClick={onResolve}
      >
        处理重复 (<span className="num">{count}</span>)
      </button>
    </div>
  )
}
