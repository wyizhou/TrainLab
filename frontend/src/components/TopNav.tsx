import { NavLink, matchPath, useLocation } from 'react-router-dom'
import { NAV_ITEMS } from './navItems'
import './TopNav.css'

// Shared application header. Mobile keeps the brand and user actions while the
// route navigation moves to BottomTabBar. The last-sync pill is desktop/wide.
//
// pixel-contract (design_rev 3, AC-001c-1/2): stable `data-vc` anchors mirror onto
// the component root elements so the visual-contract `[data-vc=…]` checks resolve.
// The active item carries `top-nav-item-active`; active state is computed with the
// same `end` semantics as NavLink so the anchor tracks NavLink's own highlight.
export function TopNav({
  showNav = true,
  showSync = false,
}: {
  showNav?: boolean
  showSync?: boolean
}) {
  const { pathname } = useLocation()

  return (
    <header className="topnav" data-vc="app-header" data-testid="app-header">
      <div className="topnav__brand" data-vc="app-brand">
        <span className="topnav__mark">TL</span>
        <span className="topnav__brand-name">TrainLab</span>
      </div>
      {showNav && (
        <nav className="topnav__links" aria-label="主导航" data-vc="top-nav" data-testid="top-nav">
          {NAV_ITEMS.map((item) => {
            const isActive = matchPath({ path: item.to, end: item.end }, pathname) !== null
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                data-vc={isActive ? 'top-nav-item-active' : 'top-nav-item'}
                className={() => (isActive ? 'topnav__link topnav__link--active' : 'topnav__link')}
              >
                {item.label}
              </NavLink>
            )
          })}
        </nav>
      )}
      <span className="topnav__spacer" aria-hidden="true" />
      {showSync && (
        <span className="topnav__sync" data-vc="sync-chip" data-testid="last-sync">
          上次同步 昨天 22:41
        </span>
      )}
      <div className="topnav__user" data-vc="user-actions">
        <span className="topnav__avatar" aria-hidden="true">
          A
        </span>
        <button type="button" className="topnav__logout">
          退出
        </button>
      </div>
    </header>
  )
}
