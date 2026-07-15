// Upload parsing + validation for the 文件上传 area (contract C-13). Turns a
// picked FIT/TCX/GPX file into an Activity (source 「FIT上传」). FIT reuses the
// real @garmin/fitsdk parser (C-8); TCX/GPX are parsed from their XML with the
// platform DOMParser (available in the browser and jsdom) — no extra deps, no
// network (G-mock). All values come from the file, nothing is system-computed.

import { parseFitActivity, type FitSummary } from '../activities/fitParser'
import type { Activity, ActivityType } from '../activities/activityData'

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024 // 50MB
export const ALLOWED_EXTENSIONS = ['.fit', '.tcx', '.gpx'] as const
export type UploadExt = (typeof ALLOWED_EXTENSIONS)[number]

// A parsed record ready for 入库; the store assigns the id.
export type ParsedUpload = Omit<Activity, 'id'>

export function extensionOf(fileName: string): string {
  const dot = fileName.lastIndexOf('.')
  return dot < 0 ? '' : fileName.slice(dot).toLowerCase()
}

export function baseNameOf(fileName: string): string {
  const slash = Math.max(fileName.lastIndexOf('/'), fileName.lastIndexOf('\\'))
  const bare = slash < 0 ? fileName : fileName.slice(slash + 1)
  const dot = bare.lastIndexOf('.')
  return dot <= 0 ? bare : bare.slice(0, dot)
}

// Human-readable file size for the 已解析文件 list (tabular-nums column).
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Returns a rejection message, or null when the file passes the gate. Extension
// is checked first so an unsupported huge file still reads as "格式" not "过大".
export function validateUpload(fileName: string, size: number): string | null {
  const ext = extensionOf(fileName)
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
    return '不支持的格式，仅支持 FIT / TCX / GPX'
  }
  if (size > MAX_UPLOAD_BYTES) {
    return `文件超过 50MB 上限（${formatFileSize(size)}）`
  }
  return null
}

// ---- normalized intermediate --------------------------------------------------

type Normalized = {
  type: ActivityType
  name: string
  date: string // YYYY-MM-DD
  distanceKm: number | null
  durationSec: number
  avgHr: number
  avgSpeedMps: number | null
  avgPowerW: number | null
}

function round2(x: number): number {
  return Math.round(x * 100) / 100
}

function isoToDate(iso: string): string {
  return iso.slice(0, 10)
}

function toParsedUpload(n: Normalized): ParsedUpload {
  const isRun = n.type === '跑步' || n.type === '越野跑'
  const isSwim = n.type === '游泳'
  const isRide = n.type === '骑行'
  const speed = n.avgSpeedMps
  const hasSpeed = speed !== null && speed > 0
  return {
    date: n.date,
    type: n.type,
    name: n.name,
    distanceKm: n.type === '力量' ? null : n.distanceKm,
    durationSec: n.durationSec,
    avgHr: n.avgHr,
    paceSecPerKm: isRun && hasSpeed ? Math.round(1000 / speed) : null,
    pace100Sec: isSwim && hasSpeed ? Math.round(100 / speed) : null,
    powerW: isRide ? n.avgPowerW : null,
    source: 'FIT上传',
  }
}

// ---- FIT ----------------------------------------------------------------------

function typeFromFitSport(sport: string, subSport: string): ActivityType {
  switch (sport) {
    case 'cycling':
      return '骑行'
    case 'swimming':
      return '游泳'
    case 'training':
    case 'fitness_equipment':
    case 'strength_training':
      return '力量'
    case 'running':
      return subSport === 'trail' ? '越野跑' : '跑步'
    default:
      return '跑步'
  }
}

function normalizeFit(summary: FitSummary, name: string): Normalized {
  const distanceM = summary.totalDistanceM
  return {
    type: typeFromFitSport(summary.sport, summary.subSport),
    name,
    date: isoToDate(summary.startTime),
    distanceKm: distanceM > 0 ? round2(distanceM / 1000) : null,
    durationSec: Math.round(summary.totalTimerTimeSec),
    avgHr: summary.avgHr ?? 0,
    avgSpeedMps: summary.avgSpeedMps,
    avgPowerW: summary.avgPowerW,
  }
}

// ---- TCX / GPX (XML) ----------------------------------------------------------

function parseXml(text: string): Document {
  const doc = new DOMParser().parseFromString(text, 'application/xml')
  if (doc.getElementsByTagName('parsererror').length > 0) {
    throw new Error('XML 解析失败')
  }
  return doc
}

// getElementsByTagName / children walks are used throughout rather than CSS
// selectors: jsdom's selector engine is unreliable on namespaced XML (GPX/TCX),
// while tag-name and local-name lookups are not.

function textOf(el: Element | null): string {
  return el?.textContent?.trim() ?? ''
}

function firstText(root: Document | Element, tag: string): string {
  return textOf(root.getElementsByTagName(tag)[0] ?? null)
}

// First matching direct-child value (avoids picking a nested descendant, e.g. a
// Trackpoint's own DistanceMeters when summing a Lap's).
function childNumber(el: Element, local: string): number {
  for (const child of Array.from(el.children)) {
    if (child.localName === local) return Number(child.textContent) || 0
  }
  return 0
}

// Elements by local name, namespace-agnostic (GPX heart rate lives under a
// gpxtpx: prefix that varies by exporter).
function byLocalName(root: Document | Element, local: string): Element[] {
  return Array.from(root.getElementsByTagName('*')).filter((e) => e.localName === local)
}

// Direct-child element by local name (e.g. a trk's own <name>, not a waypoint's).
function childByLocal(el: Element, local: string): Element | null {
  for (const child of Array.from(el.children)) {
    if (child.localName === local) return child
  }
  return null
}

function mean(values: number[]): number {
  if (values.length === 0) return 0
  return Math.round(values.reduce((sum, v) => sum + v, 0) / values.length)
}

function typeFromLabel(label: string): ActivityType {
  const l = label.toLowerCase()
  if (l.includes('bik') || l.includes('cycl') || l.includes('ride')) return '骑行'
  if (l.includes('swim')) return '游泳'
  if (l.includes('trail')) return '越野跑'
  if (l.includes('strength') || l.includes('training')) return '力量'
  return '跑步'
}

function normalizeTcx(doc: Document, fallbackName: string): Normalized {
  const activity = doc.getElementsByTagName('Activity')[0] ?? null
  const sport = activity?.getAttribute('Sport') ?? ''
  let distanceM = 0
  let durationSec = 0
  for (const lap of byLocalName(doc, 'Lap')) {
    distanceM += childNumber(lap, 'DistanceMeters')
    durationSec += childNumber(lap, 'TotalTimeSeconds')
  }
  const hrs = byLocalName(doc, 'HeartRateBpm')
    .map((el) => Number(firstText(el, 'Value')))
    .filter((n) => Number.isFinite(n) && n > 0)
  const startIso = firstText(doc, 'Id') || firstText(doc, 'Time')
  return {
    type: typeFromLabel(sport),
    name: fallbackName,
    date: isoToDate(startIso),
    distanceKm: distanceM > 0 ? round2(distanceM / 1000) : null,
    durationSec: Math.round(durationSec),
    avgHr: mean(hrs),
    avgSpeedMps: durationSec > 0 ? distanceM / durationSec : null,
    avgPowerW: null,
  }
}

function toRad(deg: number): number {
  return (deg * Math.PI) / 180
}

function haversineM(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6_371_000
  const dLat = toRad(bLat - aLat)
  const dLon = toRad(bLon - aLon)
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(s))
}

function normalizeGpx(doc: Document, fallbackName: string): Normalized {
  const trk = doc.getElementsByTagName('trk')[0] ?? null
  const trackName = trk ? textOf(childByLocal(trk, 'name')) : ''
  const typeLabel = trk ? textOf(childByLocal(trk, 'type')) : ''
  const points = byLocalName(doc, 'trkpt')

  let distanceM = 0
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1]
    const b = points[i]
    const aLat = Number(a.getAttribute('lat'))
    const aLon = Number(a.getAttribute('lon'))
    const bLat = Number(b.getAttribute('lat'))
    const bLon = Number(b.getAttribute('lon'))
    if ([aLat, aLon, bLat, bLon].every(Number.isFinite)) {
      distanceM += haversineM(aLat, aLon, bLat, bLon)
    }
  }

  const times = points
    .map((p) => Date.parse(textOf(childByLocal(p, 'time'))))
    .filter((t) => Number.isFinite(t))
  const durationSec =
    times.length >= 2 ? Math.round((times[times.length - 1] - times[0]) / 1000) : 0

  const hrs = byLocalName(doc, 'hr')
    .map((el) => Number(textOf(el)))
    .filter((n) => Number.isFinite(n) && n > 0)

  const startIso = points[0] ? textOf(childByLocal(points[0], 'time')) : ''
  return {
    type: typeFromLabel(typeLabel),
    name: trackName || fallbackName,
    date: isoToDate(startIso),
    distanceKm: distanceM > 0 ? round2(distanceM / 1000) : null,
    durationSec,
    avgHr: mean(hrs),
    avgSpeedMps: durationSec > 0 && distanceM > 0 ? distanceM / durationSec : null,
    avgPowerW: null,
  }
}

// ---- dispatch -----------------------------------------------------------------

// Parses one already-validated file's bytes into a record ready for 入库. Throws
// if the payload cannot be decoded (the caller surfaces it as a rejection).
export function parseUploadFile(fileName: string, bytes: Uint8Array): ParsedUpload {
  const ext = extensionOf(fileName)
  const base = baseNameOf(fileName)
  if (ext === '.fit') {
    return toParsedUpload(normalizeFit(parseFitActivity(bytes).summary, base))
  }
  const text = new TextDecoder().decode(bytes)
  if (ext === '.tcx') {
    return toParsedUpload(normalizeTcx(parseXml(text), base))
  }
  if (ext === '.gpx') {
    return toParsedUpload(normalizeGpx(parseXml(text), base))
  }
  throw new Error(`不支持的格式 ${ext}`)
}
