import { act, renderHook } from '@testing-library/react'
import { breakpointForWidth, useBreakpoint } from './useBreakpoint'

function setWidth(width: number) {
  window.innerWidth = width
  window.dispatchEvent(new Event('resize'))
}

describe('breakpointForWidth', () => {
  it('maps each width to its contracted band, boundaries inclusive of the lower edge', () => {
    expect(breakpointForWidth(320)).toBe('mobile')
    expect(breakpointForWidth(639)).toBe('mobile')
    expect(breakpointForWidth(640)).toBe('tablet')
    expect(breakpointForWidth(979)).toBe('tablet')
    expect(breakpointForWidth(980)).toBe('desktop')
    expect(breakpointForWidth(1439)).toBe('desktop')
    expect(breakpointForWidth(1440)).toBe('wide')
    expect(breakpointForWidth(1920)).toBe('wide')
  })
})

describe('useBreakpoint', () => {
  const original = window.innerWidth
  afterEach(() => {
    window.innerWidth = original
  })

  it('reports the current band and updates live on resize', () => {
    act(() => setWidth(1280))
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current).toBe('desktop')

    act(() => setWidth(390))
    expect(result.current).toBe('mobile')

    act(() => setWidth(768))
    expect(result.current).toBe('tablet')

    act(() => setWidth(1920))
    expect(result.current).toBe('wide')
  })
})
