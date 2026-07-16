import { NavLink, matchPath, useLocation } from 'react-router-dom'
import { NAV_ITEMS } from './navItems'
import './BottomTabBar.css'

// Mobile navigation mode (C-1 / AC-001b-1): a fixed bottom tab bar with the same
// five contracted items as the top nav, each rendered as icon + label.
// Icons are decorative (aria-hidden) so each link's accessible name is its label.
const ICONS: Record<string, string> = {
  '/': '✦',
  '/activities': '▶',
  '/health': '♥',
  '/connectors': '⇅',
  '/settings': '⚙',
}

// pixel-contract (design_rev 3, AC-001c-3): `data-vc` anchors mirror onto the nav
// root and the active tab so the visual-contract `[data-vc=…]` checks resolve.
export function BottomTabBar() {
  const { pathname } = useLocation()

  return (
    <nav
      className="bottom-tab-bar"
      aria-label="主导航"
      data-vc="bottom-nav"
      data-testid="bottom-tab-bar"
    >
      {NAV_ITEMS.map((item) => {
        const isActive = matchPath({ path: item.to, end: item.end }, pathname) !== null
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            data-vc={isActive ? 'bottom-nav-item-active' : 'bottom-nav-item'}
            className={() =>
              isActive
                ? 'bottom-tab-bar__item bottom-tab-bar__item--active'
                : 'bottom-tab-bar__item'
            }
          >
            <span className="bottom-tab-bar__icon" aria-hidden="true">
              {ICONS[item.to]}
            </span>
            <span className="bottom-tab-bar__label">{item.label}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}
