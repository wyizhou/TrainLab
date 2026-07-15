import { NavLink, matchPath, useLocation } from 'react-router-dom'
import { NAV_ITEMS } from './navItems'
import './TopNav.css'

// Desktop/tablet navigation chrome (C-1). Below the tablet breakpoint the shell
// swaps this out for the mobile BottomTabBar entirely (AppLayout). The last-sync
// pill only renders on desktop/wide — the shell passes `showSync` accordingly.
//
// pixel-contract (design_rev 3, AC-001c-1/2): stable `data-vc` anchors mirror onto
// the component root elements so the visual-contract `[data-vc=…]` checks resolve.
// The active item carries `top-nav-item-active`; active state is computed with the
// same `end` semantics as NavLink so the anchor tracks NavLink's own highlight.
export function TopNav({ showSync = false }: { showSync?: boolean }) {
  const { pathname } = useLocation()

  return (
    <header className="topnav" data-vc="top-nav" data-testid="top-nav">
      <span className="topnav__brand">TrainLab</span>
      <nav className="topnav__links" aria-label="主导航">
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
      {showSync && (
        <span className="topnav__sync" data-vc="sync-chip" data-testid="last-sync">
          上次同步 09:12
        </span>
      )}
    </header>
  )
}
