import { NavLink, matchPath, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { NAV_ITEMS } from './navItems'
import './BottomTabBar.css'

// Mobile navigation mode (C-1 / AC-001b-1): a fixed bottom tab bar with the same
// five contracted items as the top nav, each rendered as icon + label.
// Icons are decorative (aria-hidden) so each link's accessible name is its label.
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="bottom-tab-bar__icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

const ICONS: Record<string, ReactNode> = {
  '/': <path d="M4 19V9l8-5 8 5v10M4 19h16" />,
  '/activities': <path d="M4 17l5-6 4 4 7-8" />,
  '/health': <path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2 4 4 0 0 1 7 2c0 5.5-7 10-7 10z" />,
  '/connectors': (
    <path d="M8 8l8 8M9 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM15 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" />
  ),
  '/settings': <path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3" />,
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
            <Icon>{ICONS[item.to]}</Icon>
            <span className="bottom-tab-bar__label">{item.label}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}
