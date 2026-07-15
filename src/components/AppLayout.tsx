import { Outlet } from 'react-router-dom'
import { useBreakpoint } from '../hooks/useBreakpoint'
import { TopNav } from './TopNav'
import { BottomTabBar } from './BottomTabBar'

// Chrome shared by every in-app route. Dual-mode navigation (C-1, design_rev 2):
// mobile drops the top nav entirely and renders a fixed bottom tab bar; tablet and
// up keep the top nav. The last-sync pill only shows on desktop/wide. Main-content
// padding is graded per breakpoint (AC-001b-4). The standalone login page renders
// outside this layout (no nav chrome).
export function AppLayout() {
  const breakpoint = useBreakpoint()
  const isMobile = breakpoint === 'mobile'
  const showSync = breakpoint === 'desktop' || breakpoint === 'wide'

  return (
    <div className="app-shell">
      {!isMobile && <TopNav showSync={showSync} />}
      <main className={`app-main app-main--${breakpoint}`}>
        <Outlet />
      </main>
      {isMobile && <BottomTabBar />}
    </div>
  )
}
