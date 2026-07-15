// Central design tokens — the single source of truth for raw color values.
// ESLint bans bare hex / color-function literals in every other module (G-token);
// this file is the only exemption. Keep it in lockstep with `tokens.css`.

export const color = {
  bg: '#0A0F18',
  panel: '#121A28',
  panelDeep: '#0B1220',
  // design_rev 4: accent oklch→原型实测 rgb 固化; onAccent/text 对齐 v3.1 三表.
  accent: '#4292E0',
  onAccent: '#06101E',
  text: '#E6EBF4',
  textSoft: '#B8C2D4',
  // v3.1 表 (a) 实测 rgb(138,148,168); design_rev 4 权威源迁移校正原 #8A97A8（零 AC 值变更）.
  textMuted: '#8A94A8',
  border: '#1E2A3C',
  uploadDeep: '#0E1524',
  hoverRow: '#16202F',
  success: 'oklch(0.72 0.17 150)',
  warn: '#E0A040',
  danger: 'oklch(0.62 0.2 25)',
  // Global chrome (C-1 / AC-001c-*; v3.1 表 (a)).
  panelNav: '#0D1420',
  accentText: '#5EA3E8',
  accent16: 'rgba(66, 146, 224, 0.16)',
  accent12: 'rgba(66, 146, 224, 0.12)',
  accent18: 'rgba(66, 146, 224, 0.18)',
  // accentDeep = v3.1 表 (a) rgb(46,92,158); chat-bubble-user 底 / sleep-chart-bar-deep (C-6 AC-006c-2).
  accentDeep: '#2E5C9E',
  borderPanel: '#223049',
  // borderInput = v3.1 表 (a) rgb(42,58,85); scope-chip 常态边框 (C-4 AC-004c-1).
  borderInput: '#2A3A55',
  borderWeak: '#1C2739',
  borderToast: '#3A4E70',
  toastBg: '#1A2436',
  // Activity-type accent dots (C-7 list / C-8 detail).
  typeRun: '#4292E0',
  typeRide: '#3FBF8F',
  typeSwim: '#3FB8BF',
  typeStrength: '#E0A040',
  typeTrail: '#9B7BE0',
} as const

export const radius = {
  xs: '4px',
  sm: '6px',
  input: '8px',
  md: '10px',
  panel: '12px',
  lg: '14px',
  pill: '99px',
} as const

export const space = {
  1: '4px',
  2: '8px',
  3: '12px',
  4: '16px',
  5: '24px',
  6: '32px',
} as const

export type ColorToken = keyof typeof color
