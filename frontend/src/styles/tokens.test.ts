import { color, radius, space } from './tokens'

describe('design tokens', () => {
  it('pins the contracted dark palette (C-1)', () => {
    expect(color.bg).toBe('#0A0F18')
    expect(color.panel).toBe('#121A28')
    expect(color.panelDeep).toBe('#0B1220')
    // design_rev 4: accent oklch 固化为原型实测 rgb; onAccent/text 对齐 v3.1 三表.
    expect(color.accent).toBe('#4292E0')
    expect(color.onAccent).toBe('#06101E')
    expect(color.text).toBe('#E6EBF4')
  })

  it('pins the global-chrome tokens (AC-001c-*)', () => {
    expect(color.panelNav).toBe('#0D1420')
    expect(color.accentText).toBe('#5EA3E8')
    expect(color.accent16).toBe('rgba(66, 146, 224, 0.16)')
    expect(color.toastBg).toBe('#1A2436')
    expect(color.borderToast).toBe('#3A4E70')
  })

  it('exposes radius and spacing scales', () => {
    expect(radius.input).toBe('8px')
    expect(radius.pill).toBe('99px')
    expect(space[3]).toBe('12px')
  })
})
