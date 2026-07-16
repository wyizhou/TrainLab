import { useSyncExternalStore } from 'react'

// G-resp (design_rev 2): the responsive breakpoint matrix. Driven by
// `window.innerWidth`, recomputed live on resize. Single source of truth for
// which navigation mode and content padding the shell renders (contract C-1).
export type Breakpoint = 'mobile' | 'tablet' | 'desktop' | 'wide'

// mobile <640 / tablet 640–979 / desktop 980–1439 / wide ≥1440.
export function breakpointForWidth(width: number): Breakpoint {
  if (width < 640) return 'mobile'
  if (width < 980) return 'tablet'
  if (width < 1440) return 'desktop'
  return 'wide'
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('resize', onChange)
  return () => window.removeEventListener('resize', onChange)
}

function getSnapshot(): Breakpoint {
  return breakpointForWidth(window.innerWidth)
}

// SSR-safe default; the app is client-only, but useSyncExternalStore requires it.
function getServerSnapshot(): Breakpoint {
  return 'desktop'
}

export function useBreakpoint(): Breakpoint {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
