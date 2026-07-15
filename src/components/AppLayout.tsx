import { Outlet } from 'react-router-dom'
import { useBreakpoint } from '../hooks/useBreakpoint'
import { TopNav } from './TopNav'
import { BottomTabBar } from './BottomTabBar'

// Chrome shared by every in-app route. Mobile keeps a compact header and moves
// route navigation to a fixed bottom bar; tablet and up use the header nav.
export function AppLayout() {
  const breakpoint = useBreakpoint()
  const isMobile = breakpoint === 'mobile'
  const showSync = breakpoint === 'desktop' || breakpoint === 'wide'

  return (
    <div className="app-shell" data-vc="app-shell">
      <TopNav showNav={!isMobile} showSync={showSync} />
      <main className={`app-main app-main--${breakpoint}`} data-vc="main-content">
        <Outlet />
      </main>
      {isMobile && <BottomTabBar />}
    </div>
  )
}
