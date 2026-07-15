import './HealthTabs.css'

// Sub-tab strip for the health page (contract C-9). Button toggles with
// aria-pressed, matching the app's existing chip/toggle pattern (C-7 filters,
// C-8 mode switch) — no generic Tabs primitive in the codebase.

export type HealthTab = { id: string; label: string }

type HealthTabsProps = {
  tabs: readonly HealthTab[]
  active: string
  onSelect: (id: string) => void
}

export function HealthTabs({ tabs, active, onSelect }: HealthTabsProps) {
  return (
    <div
      className="health-tabs"
      role="tablist"
      aria-label="健康记录子标签"
      data-testid="health-tabs"
    >
      {tabs.map((tab) => {
        const selected = tab.id === active
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-pressed={selected}
            data-vc={selected ? 'health-tab-selected' : 'health-tab'}
            className={selected ? 'health-tabs__tab health-tabs__tab--active' : 'health-tabs__tab'}
            onClick={() => onSelect(tab.id)}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
