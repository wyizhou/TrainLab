// Contracted information architecture (C-1): the fixed five-item order shared by
// both navigation modes — the desktop/tablet top nav and the mobile bottom tab bar.
// 分析 is the default landing route (`/`).
export const NAV_ITEMS = [
  { to: '/', label: '分析', end: true },
  { to: '/activities', label: '运动记录', end: false },
  { to: '/health', label: '健康记录', end: false },
  { to: '/connectors', label: '连接器', end: false },
  { to: '/settings', label: '设置', end: false },
] as const
