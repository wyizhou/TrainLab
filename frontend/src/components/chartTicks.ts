export function tickCountForWidth(width: number): number {
  return Math.max(4, Math.min(12, Math.floor(width / 82)))
}
