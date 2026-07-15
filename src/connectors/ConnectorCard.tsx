import {
  AUTO_SYNC_OPTIONS,
  autoSyncLabel,
  statusLabel,
  type AutoSyncInterval,
  type Connector,
} from './connectorData'
import './ConnectorCard.css'

// Connector state card (contract C-10). Presentational: the four sync states
// (connected / disconnected / syncing / failed) are driven entirely by the
// `connector` prop; the page owns the state and the mock actions.

type ConnectorCardProps = {
  connector: Connector
  onSync?: (id: string) => void
  onConnect?: (id: string) => void
  onIntervalChange?: (id: string, interval: AutoSyncInterval) => void
}

// The primary button's text + handler depend on the state.
function primaryButton(
  connector: Connector,
  onSync?: (id: string) => void,
  onConnect?: (id: string) => void,
): { label: string; onClick?: () => void } {
  const { id, status } = connector
  switch (status) {
    case 'disconnected':
      return { label: '连接账号', onClick: onConnect && (() => onConnect(id)) }
    case 'failed':
      return { label: '重试同步', onClick: onSync && (() => onSync(id)) }
    case 'syncing':
      return { label: '同步中…' } // disabled below
    case 'connected':
    default:
      return { label: '立即同步', onClick: onSync && (() => onSync(id)) }
  }
}

export function ConnectorCard({
  connector,
  onSync,
  onConnect,
  onIntervalChange,
}: ConnectorCardProps) {
  const { id, abbr, name, description, status, lastSyncAt, syncedCount, autoSyncInterval, error } =
    connector
  const syncing = status === 'syncing'
  const btn = primaryButton(connector, onSync, onConnect)
  const intervalId = `auto-sync-${id}`

  return (
    <article
      className="connector-card"
      data-vc="connector-card"
      data-testid="connector-card"
      data-status={status}
    >
      <header className="connector-card__head">
        <div className="connector-card__icon" aria-hidden="true">
          {abbr}
        </div>
        <div className="connector-card__identity">
          <h2 className="connector-card__name">{name}</h2>
          <p className="connector-card__description">{description}</p>
        </div>
        <span
          className={`connector-card__pill connector-card__pill--${status}`}
          data-vc={`status-pill-${status}`}
          data-testid="connector-pill"
        >
          {statusLabel(status)}
        </span>
      </header>

      {status === 'failed' && error && (
        <div className="connector-card__error" role="alert" data-testid="connector-error">
          上次同步失败({error.at}):{error.reason}
        </div>
      )}

      <dl className="connector-card__meta">
        <div className="connector-card__meta-item">
          <dt>上次成功同步</dt>
          <dd className="connector-card__num">{lastSyncAt ?? '从未'}</dd>
        </div>
        <div className="connector-card__meta-item">
          <dt>已同步运动</dt>
          <dd className="connector-card__num">{syncedCount.toLocaleString('en-US')}</dd>
        </div>
      </dl>

      <div className="connector-card__controls">
        <label htmlFor={intervalId}>自动同步</label>
        <select
          id={intervalId}
          className="connector-card__interval"
          value={String(autoSyncInterval)}
          onChange={(e) => {
            const raw = e.target.value
            const next: AutoSyncInterval =
              raw === 'manual' ? 'manual' : (Number(raw) as 30 | 60 | 360)
            onIntervalChange?.(id, next)
          }}
        >
          {AUTO_SYNC_OPTIONS.map((opt) => (
            <option key={String(opt)} value={String(opt)}>
              {autoSyncLabel(opt)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={`connector-card__action connector-card__action--${status}`}
          data-testid="connector-action"
          onClick={btn.onClick}
          disabled={syncing}
          aria-busy={syncing}
        >
          {syncing && <span className="connector-card__spinner" aria-hidden="true" />}
          {btn.label}
        </button>
      </div>
    </article>
  )
}
