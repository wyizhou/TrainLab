import {
  DEFAULT_AI_BASE_URL,
  defaultSettings,
  getSettings,
  resetSettings,
  updateSettings,
} from './settingsStore'

describe('settingsStore (C-14)', () => {
  afterEach(() => resetSettings())

  it('starts from the documented defaults', () => {
    const s = getSettings()
    expect(s.ai.baseUrl).toBe(DEFAULT_AI_BASE_URL)
    expect(s.ai.baseUrl).toBe('https://api.deepseek.com')
    expect(s.units).toEqual({ distance: 'km', pace: 'min/km', weight: 'kg' })
    expect(s.zones).toEqual({
      maxHr: 192,
      lthr: 168,
      ftp: 245,
      bounds: [121, 141, 161, 181],
    })
  })

  // 返工 design_rev 2: the system offers no retention / auto-clean data policy, so
  // the store carries no such state or write path.
  it('has no retention / auto-clean state', () => {
    expect('retention' in getSettings()).toBe(false)
    expect('retention' in defaultSettings()).toBe(false)
  })

  it('patches settings and hands out a fresh snapshot reference', () => {
    const before = getSettings()
    updateSettings((prev) => ({ ...prev, zones: { ...prev.zones, maxHr: 205 } }))
    const after = getSettings()
    expect(after).not.toBe(before)
    expect(after.zones.maxHr).toBe(205)
    // Untouched groups are preserved.
    expect(after.units).toEqual(before.units)
  })

  it('resets back to the baseline', () => {
    updateSettings((prev) => ({ ...prev, zones: { ...prev.zones, maxHr: 999 } }))
    resetSettings()
    expect(getSettings()).toEqual(defaultSettings())
  })
})
