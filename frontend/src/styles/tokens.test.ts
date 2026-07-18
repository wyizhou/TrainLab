import { color, radius, space } from './tokens'

describe('design tokens', () => {
  it('pins the contracted light palette', () => {
    expect(color.bg).toBe('#E8EDF3')
    expect(color.panel).toBe('#FFFFFF')
    expect(color.panelDeep).toBe('#F4F7FA')
    expect(color.activityHoverRow).toBe('rgba(232, 238, 244, 0.94)')
    expect(color.accent).toBe('#2F7FC4')
    expect(color.onAccent).toBe('#FFFFFF')
    expect(color.text).toBe('#172033')
    expect(color.danger06).toBe('rgba(194, 65, 65, 0.06)')
  })

  it('pins the global-chrome tokens (AC-001c-*)', () => {
    expect(color.panelNav).toBe('#F8FAFC')
    expect(color.accentText).toBe('#256EA8')
    expect(color.accent16).toBe('rgba(47, 127, 196, 0.16)')
    expect(color.accent14).toBe('rgba(47, 127, 196, 0.14)')
    expect(color.toastBg).toBe('#E3EAF2')
    expect(color.borderToast).toBe('#8FA2B7')
  })

  it('exposes radius and spacing scales', () => {
    expect(radius.input).toBe('8px')
    expect(radius.note).toBe('9px')
    expect(radius.pill).toBe('99px')
    expect(space[3]).toBe('12px')
  })
})
