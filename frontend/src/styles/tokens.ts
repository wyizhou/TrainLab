// Central design tokens — the single source of truth for raw color values.
// ESLint bans bare hex / color-function literals in every other module (G-token);
// this file is the only exemption. Keep it in lockstep with `tokens.css`.

export const color = {
  bg: '#E8EDF3',
  panel: '#FFFFFF',
  panelDeep: '#F4F7FA',
  panelNav: '#F8FAFC',
  uploadDeep: '#EEF3F7',
  hoverRow: '#E8EEF4',
  activityHoverRow: 'rgba(232, 238, 244, 0.94)',
  accent: '#2F7FC4',
  accentText: '#256EA8',
  accentDeep: '#315F9A',
  onAccent: '#FFFFFF',
  text: '#172033',
  textSoft: '#334155',
  textMuted: '#5B6B7E',
  textFaint: '#748296',
  disabledText: '#94A3B8',
  border: '#B7C4D2',
  borderInput: '#B7C4D2',
  borderPanel: '#CBD5E1',
  borderWeak: '#D4DDE7',
  borderRow: '#E2E8F0',
  borderToast: '#8FA2B7',
  chartAxis: '#BAC7D6',
  toastBg: '#E3EAF2',
  success: '#16805D',
  warn: '#A66B0A',
  danger: '#C24141',
  accent12: 'rgba(47, 127, 196, 0.12)',
  accent14: 'rgba(47, 127, 196, 0.14)',
  accent16: 'rgba(47, 127, 196, 0.16)',
  accent18: 'rgba(47, 127, 196, 0.18)',
  sleepRem: '#6AA6DD',
  typeRun: '#2F7FC4',
  typeRide: '#16805D',
  typeSwim: '#167B82',
  typeStrength: '#A66B0A',
  typeTrail: '#7652B6',
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
