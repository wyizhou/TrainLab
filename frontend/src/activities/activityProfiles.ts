import type { Activity } from './activityData'
import {
  downsampleRecords,
  type FitLap,
  type FitRecordPoint,
  type ParsedActivity,
} from './fitParser'

export type ActivityProfileId =
  'run' | 'hike' | 'strength' | 'lead' | 'boulder' | 'cycling' | 'generic'

export type DetailMetric = { label: string; value: string; unit?: string }
export type DetailChart = {
  id: string
  label: string
  unit: string
  source: string
  values: Array<number | null>
  timesSec: number[]
  distancesKm?: Array<number | null>
}
export type DetailSegment = {
  id: string
  label: string
  duration: string
  progress: number
  details: string[]
  kind: 'lap' | 'exercise' | 'climb'
}
export type DetailDevice = {
  kind: 'watch' | 'sensor' | 'data' | 'unknown'
  role: string
  name: string
  protocol: string
  version: string
  battery: string
  provides: string[]
}
export type DetailExtensionGroup = {
  id: string
  name: string
  items: Array<{
    label: string
    value: string
    unit?: string
    source: string
    help: string
  }>
}
export type DetailRawRecord = {
  index: number
  heartRate: string
  specialized: string
  completeness: string
}
export type DetailSpecialized =
  | { kind: 'route'; facts: Array<[string, string]>; points: Array<[number, number]> }
  | { kind: 'exercises'; rows: Array<[string, string, string, string]> }
  | { kind: 'metrics'; items: DetailMetric[]; note: string }
  | { kind: 'capabilities'; items: string[]; note: string }
  | { kind: 'attempts'; note: string }

export type ActivityProfile = {
  id: ActivityProfileId
  label: string
  token: string
  fileName: string
  title: string
  meta: string
  parseStatus: 'complete' | 'partial'
  parseStatusLabel: string
  loadLabel: string
  metrics: DetailMetric[]
  insight: string
  charts: DetailChart[]
  composition: Array<{ label: string; value: number }>
  fields: Array<[string, string]>
  specializedTitle: string
  specializedNote: string
  specialized: DetailSpecialized
  segments: DetailSegment[]
  noLapsReason?: string
  noGpsReason?: string
  devices: DetailDevice[]
  extensionGroups: DetailExtensionGroup[]
  rawRecords: DetailRawRecord[]
  downloadAvailable: boolean
}

export const PROFILE_ACTIVITY_IDS: Record<Exclude<ActivityProfileId, 'run'>, string> = {
  hike: 'profile-hike',
  strength: 'profile-strength',
  lead: 'profile-lead',
  boulder: 'profile-boulder',
  cycling: 'profile-cycling',
  generic: 'profile-generic',
}

const PROFILE_RECORDS: Record<string, Activity> = {
  'profile-hike': {
    id: 'profile-hike',
    date: '2026-05-30',
    type: '徒步',
    name: '高海拔徒步',
    distanceKm: 7.76,
    durationSec: 15381,
    avgHr: 102,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
  },
  'profile-strength': {
    id: 'profile-strength',
    date: '2026-03-30',
    type: '力量',
    name: '攀岩专项力量训练',
    distanceKm: null,
    durationSec: 3565,
    avgHr: 103,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
  },
  'profile-lead': {
    id: 'profile-lead',
    date: '2026-07-14',
    type: '难度攀岩',
    name: '室内难度攀岩',
    distanceKm: null,
    durationSec: 1716,
    avgHr: 131,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
  },
  'profile-boulder': {
    id: 'profile-boulder',
    date: '2026-07-14',
    type: '抱石',
    name: '室内抱石',
    distanceKm: null,
    durationSec: 2598,
    avgHr: 117,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
  },
  'profile-cycling': {
    id: 'profile-cycling',
    date: '2026-07-16',
    type: '骑行',
    name: '骑行详情结构',
    distanceKm: null,
    durationSec: 0,
    avgHr: 0,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
  },
  'profile-generic': {
    id: 'profile-generic',
    date: '2026-07-16',
    type: '其他',
    name: '通用运动详情',
    distanceKm: null,
    durationSec: 0,
    avgHr: 0,
    paceSecPerKm: null,
    pace100Sec: null,
    powerW: null,
    source: 'FIT上传',
  },
}

export function profileActivityById(id: string | undefined): Activity | undefined {
  return id ? PROFILE_RECORDS[id] : undefined
}

export function resolveActivityProfileId(
  sport: string | null | undefined,
  subSport: string | null | undefined,
): ActivityProfileId {
  const sportKey = sport?.toLowerCase() ?? ''
  const subKey = subSport?.toLowerCase() ?? ''
  if (
    sportKey === 'hiking' ||
    sportKey === 'walking' ||
    sportKey === 'mountaineering' ||
    subKey.includes('trail')
  )
    return 'hike'
  if (sportKey === 'running') return 'run'
  if (sportKey === 'strength_training' || sportKey === 'training' || subKey.includes('strength'))
    return 'strength'
  if (sportKey === 'rock_climbing' || sportKey === 'climbing') {
    return subKey.includes('boulder') ? 'boulder' : 'lead'
  }
  if (sportKey === 'cycling') return 'cycling'
  return 'generic'
}

function profileIdFor(activity: Activity, parsed: ParsedActivity | null): ActivityProfileId {
  const explicit = Object.entries(PROFILE_ACTIVITY_IDS).find(([, id]) => id === activity.id)?.[0]
  if (explicit) return explicit as ActivityProfileId
  if (parsed) return resolveActivityProfileId(parsed.summary.sport, parsed.summary.subSport)
  if (activity.type === '跑步') return 'run'
  if (activity.type === '越野跑' || activity.type === '徒步') return 'hike'
  if (activity.type === '力量') return 'strength'
  if (activity.type === '难度攀岩') return 'lead'
  if (activity.type === '抱石') return 'boulder'
  if (activity.type === '骑行') return 'cycling'
  return 'generic'
}

function clock(seconds: number): string {
  const rounded = Math.round(seconds)
  const hours = Math.floor(rounded / 3600)
  const minutes = Math.floor((rounded % 3600) / 60)
  const secs = rounded % 60
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
    : `${minutes}:${String(secs).padStart(2, '0')}`
}

function displayNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '未提供'
  return value.toFixed(digits).replace(/\.?0+$/, '')
}

function safeHumanText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const withoutControls = [...value.normalize('NFC')]
    .map((character) => {
      const code = character.codePointAt(0) ?? 0
      return code <= 31 || (code >= 127 && code <= 159) ? ' ' : character
    })
    .join('')
  const normalized = withoutControls.replace(/\s+/g, ' ').trim()
  if (!normalized || normalized.length > 255) return null
  if (/^[+-]?\d+(?:\.\d+)?$/.test(normalized)) return null
  if (normalized.startsWith('[') || normalized.startsWith('{')) return null
  return normalized
}

function isRestSegment(kind: string): boolean {
  return kind.toLowerCase().includes('rest')
}

function explicitlyBodyweight(extraData: Record<string, unknown>): boolean {
  if (extraData.bodyweight === true || extraData.bodyWeight === true) return true
  const explicitKind = [
    extraData.weight_type,
    extraData.weightType,
    extraData.load_type,
    extraData.loadType,
    extraData.resistance_type,
    extraData.resistanceType,
  ].find((value): value is string => typeof value === 'string')
  return explicitKind
    ? ['bodyweight', 'body_weight', 'self_weight'].includes(explicitKind.toLowerCase())
    : false
}

function chartFromRecords(
  id: string,
  label: string,
  unit: string,
  source: string,
  records: FitRecordPoint[],
  value: (record: FitRecordPoint) => number | null,
): DetailChart {
  const sampled = downsampleRecords(records)
  return {
    id,
    label,
    unit,
    source,
    values: sampled.map(value),
    timesSec: sampled.map((record) => record.tSec),
    distancesKm: sampled.map((record) =>
      record.distanceM === null ? null : record.distanceM / 1000,
    ),
  }
}

function chart(
  id: string,
  label: string,
  unit: string,
  values: number[],
  duration: number,
  distanceKm?: number,
): DetailChart {
  const divisor = Math.max(1, values.length - 1)
  return {
    id,
    label,
    unit,
    source: `record.${id}`,
    values,
    timesSec: values.map((_, index) => (duration * index) / divisor),
    distancesKm:
      distanceKm === undefined
        ? undefined
        : values.map((_, index) => (distanceKm * index) / divisor),
  }
}

function segmentsFromLaps(laps: FitLap[]): DetailSegment[] {
  const total = laps.reduce((sum, lap) => sum + lap.durationSec, 0) || 1
  let elapsed = 0
  return laps.map((lap) => {
    const progress = (elapsed + lap.durationSec / 2) / total
    elapsed += lap.durationSec
    return {
      id: `lap-${lap.index}`,
      label: `第 ${lap.index + 1} 圈`,
      duration: clock(lap.durationSec),
      progress,
      details: [
        `${(lap.distanceM / 1000).toFixed(2)} km`,
        lap.avgHr === null ? '平均心率未提供' : `${Math.round(lap.avgHr)} bpm`,
        lap.avgPowerW === null ? '平均功率未提供' : `${Math.round(lap.avgPowerW)} W`,
      ],
      kind: 'lap',
    }
  })
}

const RUN_DEVICES: DetailDevice[] = [
  {
    kind: 'watch',
    role: '运动手表',
    name: 'Garmin · 产品名称未记录',
    protocol: '本地设备',
    version: '17.33',
    battery: '未记录',
    provides: ['GPS', '心率', '原生功率', '圈'],
  },
  {
    kind: 'sensor',
    role: 'Footpod / 跑姿传感器',
    name: '厂商与产品名称未记录',
    protocol: 'BLE',
    version: '未记录',
    battery: 'good',
    provides: ['外接距离', '步频', '触地时间', '垂直振幅'],
  },
  {
    kind: 'data',
    role: '开发者数据源',
    name: 'application version 49',
    protocol: 'FIT Developer Data',
    version: '49',
    battery: '不适用',
    provides: ['LSS', 'vILR', 'Body Y PIF', '总功率'],
  },
  {
    kind: 'unknown',
    role: '来源未明确',
    name: '指标无法可靠关联到具体设备',
    protocol: '未知',
    version: '未记录',
    battery: '未记录',
    provides: ['部分冲击指标'],
  },
]

const RUN_EXTENSIONS: DetailExtensionGroup[] = [
  {
    id: 'dynamics',
    name: '跑步动态',
    items: [
      { label: '步频', value: '174', unit: 'spm', source: 'FIT 原生字段', help: 'record.cadence' },
      {
        label: '触地时间',
        value: '264.5',
        unit: 'ms',
        source: 'FIT 原生字段',
        help: 'session.avg_stance_time',
      },
      {
        label: '垂直振幅',
        value: '8.1',
        unit: 'cm',
        source: 'FIT 原生字段',
        help: 'session.avg_vertical_oscillation',
      },
    ],
  },
  {
    id: 'impact',
    name: '冲击负荷',
    items: [
      {
        label: '腿部弹簧刚度',
        value: '4.56',
        unit: 'kN/m',
        source: '开发者字段',
        help: '设备来源未明确',
      },
      {
        label: '垂直冲击负荷率',
        value: '39.53',
        unit: 'BW/s',
        source: '开发者字段',
        help: '设备来源未明确',
      },
      {
        label: '身体垂直峰值冲击力',
        value: '17.59',
        unit: 'g',
        source: '开发者字段',
        help: '设备来源未明确',
      },
    ],
  },
  {
    id: 'power',
    name: '功率',
    items: [
      {
        label: '原生平均功率',
        value: '265',
        unit: 'W',
        source: 'FIT 原生字段',
        help: 'session.avg_power',
      },
      {
        label: '扩展总功率',
        value: '独立保留',
        source: '开发者字段',
        help: '未提供明确映射时不与原生功率合并',
      },
    ],
  },
]

const STATIC = {
  hikeHr: [68, 107, 102, 120, 113, 86, 104, 114, 116, 87, 112, 133, 90, 99, 116, 99, 88, 116],
  hikeAlt: [
    3595, 3653, 3732, 3796, 3836, 3866, 3934, 3964, 4021, 4089, 4159, 4113, 4018, 3917, 3832, 3777,
    3681, 3589,
  ],
  strengthHr: [96, 92, 109, 93, 130, 89, 95, 115, 141, 118, 104, 124, 126, 101, 82, 98, 118, 92],
  leadHr: [
    109, 127, 116, 136, 122, 153, 137, 178, 184, 139, 119, 152, 145, 118, 151, 142, 162, 115,
  ],
  boulderHr: [
    98, 119, 101, 141, 133, 153, 147, 125, 142, 115, 104, 133, 141, 108, 155, 145, 120, 103,
  ],
}

const HIKE_ROUTE: Array<[number, number]> = [
  [288, 24],
  [224, 41],
  [174, 65],
  [121, 89],
  [108, 117],
  [105, 144],
  [68, 156],
  [16, 167],
  [82, 152],
  [122, 85],
  [208, 53],
  [284, 25],
]

function staticProfile(id: Exclude<ActivityProfileId, 'run'>): ActivityProfile {
  if (id === 'hike') {
    const charts = [
      chart('altitude', '海拔', 'm', STATIC.hikeAlt, 15381, 7.76),
      chart('heart_rate', '心率', 'bpm', STATIC.hikeHr, 15381, 7.76),
    ]
    return {
      id,
      label: '徒步',
      token: 'HIKE',
      fileName: '600348741_ACTIVITY.fit',
      title: '高海拔徒步',
      meta: '2026-05-30 10:14 · Hike · GPS + barometer · Asia/Shanghai (UTC+8)',
      parseStatus: 'complete',
      parseStatusLabel: '设计样本摘要',
      loadLabel: '训练负荷 9.8',
      metrics: [
        { label: '距离', value: '7.76', unit: 'km' },
        { label: '总时间', value: '4:16:21' },
        { label: '累计爬升', value: '580', unit: 'm' },
        { label: '累计下降', value: '585', unit: 'm' },
        { label: '平均 / 最大心率', value: '102 / 146', unit: 'bpm' },
        { label: '热量', value: '1,023', unit: 'kcal' },
      ],
      insight:
        '轨迹从约 3,595 m 上升至约 4,159 m 后沿近似原路返回；没有可用圈时保留路线点和连续曲线，不生成公里圈。',
      charts,
      composition: [
        { label: '移动记录', value: 12217 },
        { label: '低速 / 停顿', value: 3164 },
      ],
      fields: [
        ['session', '距离 / 爬升'],
        ['record', '4,072 条'],
        ['gps_metadata', '15,388 条'],
        ['course_point', '17 个'],
      ],
      specializedTitle: '轨迹与海拔结构',
      specializedNote: '轨迹由 FIT position_lat / position_long 归一化绘制',
      specialized: {
        kind: 'route',
        facts: [
          ['最高采样海拔', '4,159 m'],
          ['平均速度', '1.82 km/h'],
          ['最大速度', '8.60 km/h'],
          ['记录点', '4,072'],
        ],
        points: HIKE_ROUTE,
      },
      segments: [],
      noLapsReason: '徒步文件包含 17 个路线点，但没有可用圈；系统不会自动生成公里圈。',
      devices: [
        {
          kind: 'watch',
          role: '运动手表',
          name: 'Garmin · 产品名称未记录',
          protocol: '本地设备',
          version: '17.33',
          battery: '未记录',
          provides: ['心率', '海拔', '距离'],
        },
        {
          kind: 'data',
          role: 'GPS 数据源',
          name: 'FIT 原生定位字段',
          protocol: '本地设备',
          version: '不适用',
          battery: '不适用',
          provides: ['轨迹', '速度', '4,072 个记录点'],
        },
        {
          kind: 'data',
          role: '路线数据',
          name: 'Course Points',
          protocol: 'FIT 文件',
          version: '不适用',
          battery: '不适用',
          provides: ['17 个路线点'],
        },
      ],
      extensionGroups: [
        {
          id: 'route',
          name: '路线与环境',
          items: [
            {
              label: 'GPS 记录点',
              value: '4,072',
              source: 'FIT 原生字段',
              help: 'position_lat / position_long',
            },
            { label: '路线点', value: '17', source: 'FIT 原生字段', help: 'course_point' },
            {
              label: '最高采样海拔',
              value: '4,159',
              unit: 'm',
              source: 'FIT 原生字段',
              help: 'enhanced_altitude',
            },
          ],
        },
      ],
      rawRecords: charts[0].values.map((value, index) => ({
        index: index + 1,
        heartRate: String(charts[1].values[index] ?? '未提供'),
        specialized: `${value ?? '未提供'} m`,
        completeness: index % 7 === 0 ? '间隔较长' : '完整',
      })),
      downloadAvailable: false,
    }
  }

  if (id === 'strength') {
    const exercises: Array<[string, string, string, string]> = [
      ['辅助引体', '4', '24', '648 kg'],
      ['离心引体', '3', '9', '自重'],
      ['肩胛收缩', '3', '18', '自重'],
      ['高位下拉', '2', '16', '624 kg'],
      ['面拉', '3', '36', '972 kg'],
      ['弹力带外旋', '2', '24', '216 kg'],
      ['反向卷腹', '3', '30', '自重'],
      ['死虫式', '3', '36', '自重'],
      ['农夫行走', '3', '计时', '67.5 kg'],
      ['罗马尼亚硬拉', '2', '计时', '记录未含次数'],
    ]
    const charts = [chart('heart_rate', '心率', 'bpm', STATIC.strengthHr, 3564.8)]
    return {
      id,
      label: '力量训练',
      token: 'GYM',
      fileName: '578824608_ACTIVITY.fit',
      title: '攀岩专项力量训练',
      meta: '2026-03-30 07:06 · Strength Training · structured workout · Asia/Shanghai (UTC+8)',
      parseStatus: 'complete',
      parseStatusLabel: '设计样本摘要',
      loadLabel: '训练负荷 7.1',
      metrics: [
        { label: '动作', value: '10', unit: '种' },
        { label: '有效组', value: '30', unit: '组' },
        { label: '总次数', value: '196', unit: '次' },
        { label: '训练容量', value: '2,527.5', unit: 'kg' },
        { label: '平均 / 最大心率', value: '103 / 154', unit: 'bpm' },
        { label: '总时间', value: '59:25' },
      ],
      insight:
        '59 条 set 消息包含 30 个 active 与 29 个 rest；训练容量只统计同时具备重量和次数的组，计时动作不折算次数。',
      charts,
      composition: [
        { label: '动作执行', value: 1393.5 },
        { label: '组间休息', value: 2171.3 },
      ],
      fields: [
        ['workout_step', '32 个步骤'],
        ['exercise_title', '10 个动作名'],
        ['set', '30 + 29 条'],
        ['record', '1,924 条心率'],
      ],
      specializedTitle: '动作与训练容量',
      specializedNote: '组数、次数和容量直接聚合 set 消息',
      specialized: { kind: 'exercises', rows: exercises },
      segments: exercises.map((row, index) => ({
        id: `exercise-${index}`,
        label: row[0],
        duration: `${row[1]} 组`,
        progress: (index + 0.5) / exercises.length,
        details: [row[2] === '计时' ? '计时动作' : `${row[2]} 次`, row[3]],
        kind: 'exercise',
      })),
      noGpsReason: '力量训练按动作和训练组组织，不显示无意义的地图、距离、配速或圈。',
      devices: [
        {
          kind: 'watch',
          role: '运动手表',
          name: 'Garmin · 产品名称未记录',
          protocol: '本地设备',
          version: '17.33',
          battery: '未记录',
          provides: ['心率', '热量', '训练效果'],
        },
        {
          kind: 'data',
          role: '结构化训练计划',
          name: 'FIT workout / workout_step',
          protocol: 'FIT 文件',
          version: '不适用',
          battery: '不适用',
          provides: ['32 步', '10 个动作名称', '组与休息'],
        },
      ],
      extensionGroups: [
        {
          id: 'training',
          name: '训练结构',
          items: [
            {
              label: '有效组',
              value: '30',
              unit: '组',
              source: 'FIT 原生字段',
              help: 'set_type = active',
            },
            {
              label: '休息组',
              value: '29',
              unit: '组',
              source: 'FIT 原生字段',
              help: 'set_type = rest',
            },
            {
              label: '训练容量',
              value: '2,527.5',
              unit: 'kg',
              source: '计算指标',
              help: '只统计重量 × 次数均存在的组',
            },
          ],
        },
      ],
      rawRecords: STATIC.strengthHr.map((value, index) => ({
        index: index + 1,
        heartRate: String(value),
        specialized: index % 2 ? 'rest' : 'active set',
        completeness: '完整',
      })),
      downloadAvailable: false,
    }
  }

  if (id === 'lead' || id === 'boulder') {
    const lead = id === 'lead'
    const durations = lead
      ? [195.2, 186.8, 227.3, 142.4, 223.1]
      : [
          22.2, 16.2, 20.5, 19.6, 29.5, 37.5, 63, 45.3, 26.4, 32.1, 29.6, 19.8, 38.1, 24.4, 30.1,
          34.7, 66, 181.1, 42.9, 31.5, 513.5,
        ]
    const hr = lead ? STATIC.leadHr : STATIC.boulderHr
    const charts = [chart('heart_rate', '心率', 'bpm', hr, lead ? 1715.6 : 2597.7)]
    const total = durations.reduce((sum, value) => sum + value, 0)
    let elapsed = 0
    const segments = durations.map((duration, index) => {
      const progress = (elapsed + duration / 2) / total
      elapsed += duration
      return {
        id: `${id}-${index}`,
        label: lead ? `第 ${index + 1} 条路线` : `第 ${index + 1} 次尝试`,
        duration: clock(duration),
        progress,
        details: lead
          ? [`${[13, 9, 13, 0, 12][index]} m 爬升`]
          : [duration === Math.max(...durations) ? '长段 · 待复核' : '尝试记录'],
        kind: 'climb' as const,
      }
    })
    return {
      id,
      label: lead ? '难度攀岩' : '抱石',
      token: lead ? 'LEAD' : 'BLDR',
      fileName: lead ? '616634193_ACTIVITY.fit' : '616627608_ACTIVITY.fit',
      title: lead ? '室内难度攀岩' : '室内抱石',
      meta: lead
        ? '2026-07-14 16:35 · Climb Indoor · Garmin FIT · Asia/Shanghai (UTC+8)'
        : '2026-07-14 15:49 · Bouldering · Garmin FIT · Asia/Shanghai (UTC+8)',
      parseStatus: lead ? 'complete' : 'partial',
      parseStatusLabel: lead ? '设计样本摘要' : '部分字段未映射',
      loadLabel: lead ? '训练负荷 106.7' : '训练负荷 40.1',
      metrics: lead
        ? [
            { label: '路线', value: '5', unit: '条' },
            { label: '攀爬时间', value: '16:15' },
            { label: '休息时间', value: '12:21' },
            { label: '累计爬升', value: '47', unit: 'm' },
            { label: '平均 / 最大心率', value: '131 / 185', unit: 'bpm' },
            { label: '有氧 / 无氧', value: '2.0 / 3.0', unit: 'TE' },
          ]
        : [
            { label: '尝试', value: '21', unit: '次' },
            { label: '尝试时间', value: '22:04' },
            { label: '恢复时间', value: '21:14' },
            { label: '平均 / 最大心率', value: '117 / 164', unit: 'bpm' },
            { label: '热量', value: '254', unit: 'kcal' },
            { label: '有氧 / 无氧', value: '1.4 / 1.8', unit: 'TE' },
          ],
      insight: lead
        ? '5 段攀爬与 5 段休息严格交替；样本没有路线等级，界面只呈现可验证的路线、时长、爬升和心率。'
        : '21 个尝试与 21 个恢复分段接近 1:1；最长尝试仅标记为长段供复核，不推断原因、完成率或 V 级。',
      charts,
      composition: lead
        ? [
            { label: '攀爬', value: 974.8 },
            { label: '休息', value: 740.8 },
          ]
        : [
            { label: '尝试', value: 1324 },
            { label: '恢复', value: 1273.7 },
          ],
      fields: lead
        ? [
            ['session', '总览 / 训练效应'],
            ['split', 'climb_active / rest'],
            ['split_summary', '5 + 5 段'],
            ['record', '心率 / 海拔'],
          ]
        : [
            ['session', '总览 / 训练效应'],
            ['split', '21 次尝试'],
            ['split_summary', '尝试 / 恢复'],
            ['record', '连续心率'],
          ],
      specializedTitle: lead ? '路线结构' : '尝试节奏',
      specializedNote: lead ? '0 m 路线保留原始记录' : '长段不自动删除',
      specialized: {
        kind: 'attempts',
        note: lead
          ? '第 4 条路线记录 0 m 爬升；界面如实保留。样本没有路线等级。'
          : '样本没有抱石等级或可靠成功/失败字段，不显示 V 级或完成率。',
      },
      segments,
      noGpsReason: '室内攀岩没有 GPS 数据；保留心率与尝试—休息时间线，不显示空地图。',
      devices: lead
        ? [
            {
              kind: 'watch',
              role: '运动手表',
              name: 'Garmin · 产品名称未记录',
              protocol: '本地设备',
              version: '17.33',
              battery: '未记录',
              provides: ['心率', '训练效果'],
            },
            {
              kind: 'data',
              role: '高度数据源',
              name: '来源未明确',
              protocol: '本地设备',
              version: '未记录',
              battery: '未记录',
              provides: ['海拔', '总爬升', '垂直速度'],
            },
          ]
        : [
            {
              kind: 'watch',
              role: '运动手表',
              name: 'Garmin · 产品名称未记录',
              protocol: '本地设备',
              version: '17.33',
              battery: '未记录',
              provides: ['心率', '训练效果'],
            },
            {
              kind: 'unknown',
              role: '厂商私有字段',
              name: '字段语义未公开',
              protocol: 'FIT 私有扩展',
              version: '未记录',
              battery: '不适用',
              provides: ['不向普通用户展示原始编号'],
            },
          ],
      extensionGroups: [
        {
          id: 'climb',
          name: lead ? '攀爬结构' : '尝试结构',
          items: [
            {
              label: lead ? '真实攀爬段' : '真实尝试段',
              value: String(durations.length),
              unit: '段',
              source: 'FIT 原生字段',
              help: 'split / split_summary',
            },
          ],
        },
      ],
      rawRecords: hr.map((value, index) => ({
        index: index + 1,
        heartRate: String(value),
        specialized: index % 2 ? 'rest' : lead ? 'climb_active' : 'attempt',
        completeness: '完整',
      })),
      downloadAvailable: false,
    }
  }

  const cycling = id === 'cycling'
  return {
    id,
    label: cycling ? '骑行' : '通用',
    token: cycling ? 'BIKE' : 'GEN',
    fileName: cycling ? '未绑定本地 FIT 样本' : '未知运动类型兜底',
    title: cycling ? '骑行详情结构' : '通用运动详情',
    meta: cycling
      ? 'Cycling profile · capability-driven'
      : 'Unknown / custom sport · FIT capability fallback',
    parseStatus: 'partial',
    parseStatusLabel: cycling ? '等待骑行样本' : '等待识别运动类型',
    loadLabel: cycling ? '等待样本数据' : '按可用字段呈现',
    metrics: cycling
      ? [
          { label: '距离', value: '未提供' },
          { label: '经过时间', value: '未提供' },
          { label: '平均功率', value: '未提供' },
          { label: '平均速度', value: '未提供' },
          { label: '平均心率', value: '未提供' },
          { label: '踏频', value: '未提供' },
        ]
      : [
          { label: '运动类型', value: '待识别' },
          { label: '运动时长', value: '未提供' },
          { label: '心率', value: '未提供' },
          { label: '卡路里', value: '未提供' },
          { label: '训练效果', value: '未提供' },
          { label: '解析状态', value: '待解析' },
        ],
    insight: cycling
      ? '骑行 profile 预留速度、功率、踏频、海拔、路线、圈和设备模块；当前没有本地样本，因此不虚构数值或传感器归属。'
      : '未知 Garmin 枚举、Connect IQ 或第三方活动不会降级为跑步模板；仅按实际字段能力启用模块。',
    charts: [
      {
        id: cycling ? 'power' : 'heart_rate',
        label: cycling ? '功率' : '心率',
        unit: cycling ? 'W' : 'bpm',
        source: cycling ? 'record.power' : 'record.heart_rate',
        values: [],
        timesSec: [],
      },
    ],
    composition: [],
    fields: cycling
      ? [
          ['sport / sub_sport', 'cycling / 按文件解析'],
          ['record', '等待样本'],
          ['lap', '存在时显示'],
          ['device_info', '功率计 / 心率带 / 雷达等'],
        ]
      : [
          ['sport', '未知枚举保留原值'],
          ['sub_sport', '未知枚举保留原值'],
          ['record', '按字段能力渲染'],
          ['developer_data', '渐进展示'],
        ],
    specializedTitle: cycling ? '骑行专项能力' : '能力驱动兜底',
    specializedNote: '仅在字段存在且来源明确时启用',
    specialized: {
      kind: 'capabilities',
      items: cycling
        ? ['速度与距离', '功率与功率区间', '踏频', '海拔与路线', '圈与分段', '室内训练台状态']
        : [
            '通用活动摘要',
            '存在即显示的时序图表',
            '设备与数据来源',
            '分段 / 训练组探测',
            '扩展字段分组',
            '原始数据与解析诊断',
          ],
      note: '这是结构能力说明，不是活动数据；不会生成演示数字。',
    },
    segments: [],
    noLapsReason: cycling
      ? '骑行支持圈和分段，但当前未绑定样本，不生成虚构圈。'
      : '未知运动只在文件存在 lap、split、set 或可识别事件时启用分段。',
    noGpsReason: cycling
      ? '骑行支持路线和海拔，但仅在实际 FIT 含定位字段时启用。'
      : '通用兜底按位置字段存在性决定是否显示地图。',
    devices: cycling
      ? [
          {
            kind: 'unknown',
            role: '记录设备',
            name: '等待 FIT 样本识别',
            protocol: '未知',
            version: '未记录',
            battery: '未记录',
            provides: ['设备存在时再关联指标'],
          },
          {
            kind: 'sensor',
            role: '可选骑行传感器',
            name: '不预设厂商或产品',
            protocol: 'BLE / ANT+ / 未知',
            version: '未记录',
            battery: '存在时显示',
            provides: ['心率', '功率', '踏频', '速度', '雷达状态'],
          },
        ]
      : [
          {
            kind: 'unknown',
            role: '未知设备',
            name: '保留 FIT device_info 原始身份',
            protocol: '未知',
            version: '未记录',
            battery: '存在时显示',
            provides: ['只展示可验证的指标关联'],
          },
        ],
    extensionGroups: [
      {
        id: 'pending',
        name: cycling ? '骑行扩展指标' : '未知扩展字段',
        items: [
          {
            label: '状态',
            value: '等待真实数据',
            source: '解析状态',
            help: '缺少可读名称、单位和解释时不显示字段编号或原始 JSON',
          },
        ],
      },
    ],
    rawRecords: [],
    downloadAvailable: false,
  }
}

function runningProfile(activity: Activity, parsed: ParsedActivity | null): ActivityProfile {
  const summary = parsed?.summary
  const charts = parsed
    ? [
        chartFromRecords(
          'heart_rate',
          '心率',
          'bpm',
          'record.heart_rate',
          parsed.records,
          (record) => record.hr,
        ),
        chartFromRecords(
          'power',
          '功率',
          'W',
          'record.power',
          parsed.records,
          (record) => record.powerW,
        ),
        chartFromRecords(
          'stance_time',
          '触地时间',
          'ms',
          'record.stance_time',
          parsed.records,
          (record) => record.gctMs,
        ),
      ]
    : []
  const totalDistance = summary?.totalDistanceM ?? (activity.distanceKm ?? 0) * 1000
  const duration = summary?.totalTimerTimeSec ?? activity.durationSec
  const avgSpeed = summary?.avgSpeedMps
  const pace = avgSpeed && avgSpeed > 0 ? 1000 / avgSpeed : activity.paceSecPerKm
  const paceValue =
    pace === null
      ? '未提供'
      : `${Math.floor(pace / 60)}:${String(Math.round(pace % 60)).padStart(2, '0')}`
  return {
    id: 'run',
    label: '跑步',
    token: 'RUN',
    fileName: '614797758_ACTIVITY.fit',
    title: activity.name,
    meta: `${activity.date} · Run · Garmin FIT · Asia/Shanghai (UTC+8)`,
    parseStatus: parsed ? 'complete' : 'partial',
    parseStatusLabel: parsed ? '解析完整' : '等待逐秒数据',
    loadLabel:
      summary?.totalTrainingEffect === null || summary?.totalTrainingEffect === undefined
        ? '训练负荷未提供'
        : `有氧训练效果 ${summary.totalTrainingEffect.toFixed(1)}`,
    metrics: [
      { label: '距离', value: (totalDistance / 1000).toFixed(2), unit: 'km' },
      { label: '移动时间', value: clock(duration) },
      { label: '平均配速', value: paceValue, unit: '/km' },
      {
        label: '平均 / 最大心率',
        value: `${summary?.avgHr ?? activity.avgHr ?? '未提供'} / ${summary?.maxHr ?? '未提供'}`,
        unit: 'bpm',
      },
      {
        label: '平均 / 最大功率',
        value: `${summary?.avgPowerW ?? '未提供'} / ${summary?.maxPowerW ?? '未提供'}`,
        unit: 'W',
      },
      { label: '平均步频', value: String(summary?.avgCadenceSpm ?? '未提供'), unit: 'spm' },
    ],
    insight:
      '跑步 profile 将运动、设备角色、传输协议和字段来源分开；FIT 原生字段与 developer field 不因名称相似而自动合并。',
    charts,
    composition: [
      { label: '跑动', value: duration },
      { label: '暂停', value: Math.max(0, (summary?.totalElapsedTimeSec ?? duration) - duration) },
    ],
    fields: [
      ['record', parsed ? `${parsed.records.length} 条` : '等待解析'],
      ['lap', parsed ? `${parsed.laps.length} 个分段` : '等待解析'],
      ['developer_fields', '保留来源状态'],
      ['device_info', '设备角色与协议分开'],
    ],
    specializedTitle: '跑步动态与扩展指标',
    specializedNote: '原生与开发者字段并列保留',
    specialized: {
      kind: 'metrics',
      items: [
        { label: '触地时间', value: displayNumber(summary?.avgGctMs, 1), unit: 'ms' },
        {
          label: '垂直振幅',
          value: summary?.avgVertOscMm ? (summary.avgVertOscMm / 10).toFixed(2) : '未提供',
          unit: 'cm',
        },
        { label: '腿部弹簧刚度', value: displayNumber(summary?.avgLSS), unit: 'kN/m' },
        { label: '垂直冲击负荷率', value: displayNumber(summary?.avgVILR), unit: 'BW/s' },
        { label: '垂直峰值冲击力', value: displayNumber(summary?.avgBodyYPIF), unit: 'g' },
      ],
      note: '来源未明确的开发者指标不会绑定到具体设备。',
    },
    segments: parsed ? segmentsFromLaps(parsed.laps) : [],
    noLapsReason: parsed?.laps.length ? undefined : '文件未提供可用圈；不会自动生成公里圈。',
    devices: RUN_DEVICES,
    extensionGroups: RUN_EXTENSIONS,
    rawRecords: parsed
      ? downsampleRecords(parsed.records).map((record, index) => ({
          index: index + 1,
          heartRate: record.hr === null ? '未提供' : String(record.hr),
          specialized: record.powerW === null ? '功率未提供' : `${record.powerW} W`,
          completeness: record.hr === null ? '部分字段缺失' : '完整',
        }))
      : [],
    downloadAvailable: true,
  }
}

function backendProfile(activity: Activity, parsed: ParsedActivity): ActivityProfile {
  const backend = parsed.backend!
  const summary = parsed.summary
  const id = backend.profile
  const labels: Record<ActivityProfileId, [string, string]> = {
    run: ['跑步', 'RUN'],
    hike: ['徒步', 'HIKE'],
    strength: ['力量', 'STRENGTH'],
    lead: ['难度攀岩', 'LEAD'],
    boulder: ['抱石', 'BOULDER'],
    cycling: ['骑行', 'BIKE'],
    generic: ['通用', 'GEN'],
  }
  const chartCandidates: Array<DetailChart | null> = [
    chartFromRecords('heart_rate', '心率', 'bpm', 'record.heart_rate', parsed.records, (r) => r.hr),
    chartFromRecords(
      'altitude',
      '海拔',
      'm',
      'record.enhanced_altitude',
      parsed.records,
      (r) => r.altitudeM,
    ),
    chartFromRecords('power', '功率', 'W', 'record.power', parsed.records, (r) => r.powerW),
    chartFromRecords(
      'cadence',
      '步频 / 踏频',
      'spm',
      'record.cadence',
      parsed.records,
      (r) => r.cadenceSpm,
    ),
    chartFromRecords(
      'stance_time',
      '触地时间',
      'ms',
      'record.stance_time',
      parsed.records,
      (r) => r.gctMs,
    ),
    chartFromRecords(
      'vertical_oscillation',
      '垂直振幅',
      'mm',
      'record.vertical_oscillation',
      parsed.records,
      (r) => r.vertOscMm,
    ),
  ]
  const charts = chartCandidates.filter(
    (candidate): candidate is DetailChart =>
      candidate !== null && candidate.values.some((v) => v !== null),
  )
  const sourceMessage = (segment: (typeof backend.segments)[number]) => {
    const semanticSource = segment.semantic?.sourceMessage
    if (semanticSource) return semanticSource
    const legacySource = segment.extraData.sourceMessage
    return legacySource === 'set' || legacySource === 'split' || legacySource === 'split_summary'
      ? legacySource
      : null
  }
  const summarySegments = backend.segments.filter(
    (segment) => sourceMessage(segment) === 'split_summary',
  )
  // The stable semantic projection is authoritative: strength instances are
  // set messages and climbing instances are split messages. Parallel summary
  // families remain auditable but never enter counts or time composition.
  const instanceSegments = backend.segments.filter((segment) => {
    const source = sourceMessage(segment)
    if (id === 'strength') return source === 'set'
    if (id === 'lead' || id === 'boulder') return source === 'split'
    return source !== 'split_summary'
  })
  let strengthActiveIndex = 0
  let climbActiveIndex = 0
  let restIndex = 0
  const backendSegments: DetailSegment[] = instanceSegments.map((segment, index) => {
    const rest = isRestSegment(segment.kind)
    let label = safeHumanText(segment.label) ?? `${segment.kind} ${index + 1}`
    let details = [
      segment.kind,
      segment.repetitions === null ? '次数未提供' : `${displayNumber(segment.repetitions)} 次`,
      segment.weightKg === null ? '重量未提供' : `${displayNumber(segment.weightKg)} kg`,
    ]
    if (id === 'strength') {
      if (rest) {
        restIndex += 1
        label = `休息 ${restIndex}`
        details = ['休息段', '不计入动作与有效组']
      } else {
        strengthActiveIndex += 1
        label = safeHumanText(segment.semantic?.exercise?.name) ?? '动作名称未提供'
        const weight = explicitlyBodyweight(segment.extraData)
          ? '自重（文件明确记录）'
          : segment.weightKg === null
            ? '重量未提供'
            : segment.weightKg === 0
              ? '0 kg（文件明确记录）'
              : `${displayNumber(segment.weightKg)} kg`
        details = [
          `有效组 ${strengthActiveIndex}`,
          segment.repetitions === null ? '次数未提供' : `${displayNumber(segment.repetitions)} 次`,
          weight,
        ]
      }
    } else if (id === 'lead' || id === 'boulder') {
      if (rest) {
        restIndex += 1
        label = `休息 ${restIndex}`
        details = ['休息段', '不生成路线等级']
      } else {
        climbActiveIndex += 1
        label = `${id === 'lead' ? '攀爬' : '尝试'} ${climbActiveIndex}`
        const climb = segment.semantic?.climb
        const grade =
          climb?.gradeStatus === 'available' &&
          (climb.gradeSystem === 'v_scale' || climb.gradeSystem === 'yds')
            ? safeHumanText(climb.grade)
            : null
        const gradeDetail = grade !== null ? `等级 ${grade}` : '等级暂不可用：文件字段尚无可靠映射'
        const outcome =
          climb?.outcome === 'complete' ? '已完成' : climb?.outcome === 'attempt' ? '尝试' : null
        details = [gradeDetail, ...(outcome ? [outcome] : [])]
      }
    }
    return {
      id: `segment-${segment.sequence}`,
      label,
      duration: segment.durationSec === null ? '未提供' : clock(segment.durationSec),
      progress: (index + 0.5) / Math.max(1, instanceSegments.length),
      details,
      kind: id === 'strength' ? 'exercise' : id === 'lead' || id === 'boulder' ? 'climb' : 'lap',
    }
  })
  const segments = backendSegments.length > 0 ? backendSegments : segmentsFromLaps(parsed.laps)
  const activeSeconds = instanceSegments
    .filter((segment) => !isRestSegment(segment.kind))
    .reduce((sum, segment) => sum + (segment.durationSec ?? 0), 0)
  const restSeconds = instanceSegments
    .filter((segment) => isRestSegment(segment.kind))
    .reduce((sum, segment) => sum + (segment.durationSec ?? 0), 0)
  const composition =
    activeSeconds + restSeconds > 0
      ? [
          {
            label: id === 'boulder' ? '尝试' : id === 'lead' ? '攀爬' : '活动',
            value: activeSeconds,
          },
          { label: '休息', value: restSeconds },
        ]
      : [
          { label: '运动', value: summary.totalTimerTimeSec },
          {
            label: '暂停',
            value: Math.max(0, summary.totalElapsedTimeSec - summary.totalTimerTimeSec),
          },
        ]
  const gps = parsed.records.filter(
    (record) => record.positionLat !== null && record.positionLong !== null,
  )
  const routePoints: Array<[number, number]> = (() => {
    if (gps.length === 0) return []
    const latitudes = gps.map((record) => record.positionLat!)
    const longitudes = gps.map((record) => record.positionLong!)
    const minLat = Math.min(...latitudes)
    const maxLat = Math.max(...latitudes)
    const minLong = Math.min(...longitudes)
    const maxLong = Math.max(...longitudes)
    const latRange = Math.max(maxLat - minLat, Number.EPSILON)
    const longRange = Math.max(maxLong - minLong, Number.EPSILON)
    return downsampleRecords(gps, 80).map((record) => [
      16 + ((record.positionLong! - minLong) / longRange) * 272,
      167 - ((record.positionLat! - minLat) / latRange) * 143,
    ])
  })()
  let specialized: DetailSpecialized
  const strengthAggregates = new Map<
    string,
    {
      groups: number
      repetitions: number
      missingRepetitionGroups: number
      volumeKg: number
      volumeGroups: number
      bodyweightGroups: number
      zeroWeightGroups: number
      missingWeightGroups: number
    }
  >()
  for (const segment of id === 'strength'
    ? instanceSegments.filter((candidate) => !isRestSegment(candidate.kind))
    : []) {
    const name = safeHumanText(segment.semantic?.exercise?.name) ?? '动作名称未提供'
    const aggregate = strengthAggregates.get(name) ?? {
      groups: 0,
      repetitions: 0,
      missingRepetitionGroups: 0,
      volumeKg: 0,
      volumeGroups: 0,
      bodyweightGroups: 0,
      zeroWeightGroups: 0,
      missingWeightGroups: 0,
    }
    aggregate.groups += 1
    const repetitions =
      segment.repetitions !== null &&
      Number.isFinite(segment.repetitions) &&
      segment.repetitions >= 0
        ? segment.repetitions
        : null
    if (repetitions === null) aggregate.missingRepetitionGroups += 1
    else aggregate.repetitions += repetitions
    if (explicitlyBodyweight(segment.extraData)) {
      aggregate.bodyweightGroups += 1
    } else if (
      segment.weightKg === null ||
      !Number.isFinite(segment.weightKg) ||
      segment.weightKg < 0
    ) {
      aggregate.missingWeightGroups += 1
    } else {
      if (segment.weightKg === 0) aggregate.zeroWeightGroups += 1
      if (repetitions !== null) {
        aggregate.volumeKg += segment.weightKg * repetitions
        aggregate.volumeGroups += 1
      }
    }
    strengthAggregates.set(name, aggregate)
  }
  const strengthActiveGroups = [...strengthAggregates.values()].reduce(
    (sum, aggregate) => sum + aggregate.groups,
    0,
  )
  const strengthRepetitions = [...strengthAggregates.values()].reduce(
    (sum, aggregate) => sum + aggregate.repetitions,
    0,
  )
  const strengthRepetitionGroups = [...strengthAggregates.values()].reduce(
    (sum, aggregate) => sum + aggregate.groups - aggregate.missingRepetitionGroups,
    0,
  )
  const strengthVolumeKg = [...strengthAggregates.values()].reduce(
    (sum, aggregate) => sum + aggregate.volumeKg,
    0,
  )
  const strengthVolumeGroups = [...strengthAggregates.values()].reduce(
    (sum, aggregate) => sum + aggregate.volumeGroups,
    0,
  )
  if ((id === 'hike' || id === 'run' || id === 'cycling') && routePoints.length > 1) {
    specialized = {
      kind: 'route',
      points: routePoints,
      facts: [
        ['定位点', `${gps.length} 条`],
        ['总爬升', summary.totalAscentM === null ? '未提供' : `${summary.totalAscentM} m`],
      ],
    }
  } else if (id === 'strength') {
    specialized = {
      kind: 'exercises',
      rows: [...strengthAggregates.entries()].map(([name, aggregate]) => {
        const knownRepetitionGroups = aggregate.groups - aggregate.missingRepetitionGroups
        const repetitionText =
          knownRepetitionGroups === 0
            ? '次数未提供'
            : `${displayNumber(aggregate.repetitions)} 次${
                aggregate.missingRepetitionGroups
                  ? `（${aggregate.missingRepetitionGroups} 组未提供）`
                  : ''
              }`
        const volumeParts = [
          aggregate.volumeGroups
            ? `${displayNumber(aggregate.volumeKg, 1)} kg · ${aggregate.volumeGroups} 组可计算`
            : '容量不可计算',
          aggregate.bodyweightGroups ? `${aggregate.bodyweightGroups} 组自重` : '',
          aggregate.zeroWeightGroups ? `${aggregate.zeroWeightGroups} 组明确 0 kg` : '',
          aggregate.missingWeightGroups ? `${aggregate.missingWeightGroups} 组重量未提供` : '',
        ].filter(Boolean)
        return [name, `${aggregate.groups} 组`, repetitionText, volumeParts.join(' · ')]
      }),
    }
  } else if (id === 'lead' || id === 'boulder') {
    specialized = {
      kind: 'attempts',
      note:
        id === 'lead'
          ? '仅展示文件中可验证的攀爬与休息段；文件包含尚未获得可靠映射的等级字段，不猜测路线等级。'
          : '仅展示文件中可验证的尝试与休息段；文件包含尚未获得可靠映射的等级字段，不猜测 V 级、成功率或失败原因。',
    }
  } else {
    specialized = {
      kind: 'metrics',
      items: [
        { label: '平均步频 / 踏频', value: displayNumber(summary.avgCadenceSpm), unit: 'spm' },
        { label: '触地时间', value: displayNumber(summary.avgGctMs), unit: 'ms' },
        { label: '垂直振幅', value: displayNumber(summary.avgVertOscMm), unit: 'mm' },
      ],
      note: '仅呈现 FIT 中存在的字段；未证明来源的指标不绑定具体设备。',
    }
  }
  const devices: DetailDevice[] = backend.devices.map((device) => ({
    kind:
      device.role.includes('recording') || device.role.includes('watch')
        ? 'watch'
        : device.role.includes('unknown')
          ? 'unknown'
          : 'sensor',
    role: device.role,
    name:
      [device.manufacturer, device.product, device.displayName].filter(Boolean).join(' · ') ||
      '名称未记录',
    protocol: device.transport ?? device.sourceType ?? '未知',
    version: device.softwareVersion ?? '未记录',
    battery: device.batteryStatus ?? '未记录',
    provides: ['仅显示文件明确记录的设备身份；指标归属未证明'],
  }))
  const extraMetrics = summary.extraMetrics ?? {}
  const extensionItems = backend.metricDefinitions.slice(0, 24).map((definition) => ({
    label: definition.fieldName ?? definition.stableKey,
    value:
      definition.stableKey in extraMetrics
        ? String(extraMetrics[definition.stableKey])
        : '逐点数据',
    unit: definition.unit ?? undefined,
    source: definition.stableKey.startsWith('developer:') ? '开发者字段' : 'FIT 扩展字段',
    help: definition.deviceId === null ? '设备来源未明确' : '设备关联已验证',
  }))
  const pace = summary.avgSpeedMps && summary.avgSpeedMps > 0 ? 1000 / summary.avgSpeedMps : null
  const localTime = summary.localStartTime ?? summary.startTime
  const offset = summary.utcOffsetMinutes
  return {
    id,
    label: labels[id][0],
    token: labels[id][1],
    fileName: backend.originalFileName,
    title: activity.name,
    meta: `${localTime.slice(0, 16).replace('T', ' ')} · ${summary.sport} / ${summary.subSport}${offset === null || offset === undefined ? '' : ` · UTC${offset >= 0 ? '+' : ''}${offset / 60}`}`,
    parseStatus: backend.parseStatus,
    parseStatusLabel: backend.parseStatus === 'complete' ? '解析完整' : '部分字段未映射',
    loadLabel:
      summary.totalTrainingEffect === null
        ? '训练效果未提供'
        : `有氧训练效果 ${displayNumber(summary.totalTrainingEffect, 1)}`,
    metrics:
      id === 'strength'
        ? [
            { label: '动作数', value: String(strengthAggregates.size), unit: '项' },
            { label: '有效组', value: String(strengthActiveGroups), unit: '组' },
            {
              label: '总次数',
              value:
                strengthRepetitionGroups === 0
                  ? '未提供'
                  : `${displayNumber(strengthRepetitions)}${strengthRepetitionGroups < strengthActiveGroups ? '（部分）' : ''}`,
              unit: strengthRepetitionGroups === 0 ? undefined : '次',
            },
            {
              label: '训练容量',
              value:
                strengthVolumeGroups === 0
                  ? '不可计算'
                  : `${displayNumber(strengthVolumeKg, 1)}${strengthVolumeGroups < strengthActiveGroups ? '（部分）' : ''}`,
              unit: strengthVolumeGroups === 0 ? undefined : 'kg',
            },
            { label: '运动时间', value: clock(summary.totalTimerTimeSec) },
            {
              label: '平均 / 最大心率',
              value: `${summary.avgHr ?? '未提供'} / ${summary.maxHr ?? '未提供'}`,
              unit: 'bpm',
            },
          ]
        : [
            {
              label: id === 'lead' || id === 'boulder' ? '攀爬 / 休息' : '距离',
              value:
                id === 'lead' || id === 'boulder'
                  ? `${instanceSegments.filter((segment) => !isRestSegment(segment.kind)).length} / ${instanceSegments.filter((segment) => isRestSegment(segment.kind)).length}`
                  : displayNumber(summary.totalDistanceM / 1000),
              unit: id === 'lead' || id === 'boulder' ? '段' : 'km',
            },
            { label: '运动时间', value: clock(summary.totalTimerTimeSec) },
            {
              label: '平均 / 最大心率',
              value: `${summary.avgHr ?? '未提供'} / ${summary.maxHr ?? '未提供'}`,
              unit: 'bpm',
            },
            {
              label: id === 'cycling' ? '平均功率' : '平均配速',
              value:
                id === 'cycling'
                  ? displayNumber(summary.avgPowerW)
                  : pace === null
                    ? '未提供'
                    : `${Math.floor(pace / 60)}:${String(Math.round(pace % 60)).padStart(2, '0')}`,
              unit: id === 'cycling' ? 'W' : '/km',
            },
            { label: '总爬升', value: displayNumber(summary.totalAscentM), unit: 'm' },
            { label: '卡路里', value: displayNumber(summary.totalCalories), unit: 'kcal' },
          ],
    insight:
      '此页面来自登录用户私有 FIT 文件；原生字段、开发者字段、设备身份和传输协议分别保存，不基于共现关系猜测指标来源。',
    charts,
    composition,
    fields: [
      ['record', `${backend.recordCount} 条${backend.recordsSampled ? '（当前视图已采样）' : ''}`],
      ['lap', `${parsed.laps.length} 个`],
      ['segment', `${instanceSegments.length} 个实例`],
      ...(summarySegments.length
        ? ([['split_summary', `${summarySegments.length} 个摘要`]] as Array<[string, string]>)
        : []),
      ['device_info', `${backend.devices.length} 个`],
      ['developer_fields', `${backend.metricDefinitions.length} 个定义`],
    ],
    specializedTitle:
      id === 'strength'
        ? '训练组结构'
        : id === 'lead' || id === 'boulder'
          ? '攀爬结构'
          : '专项数据',
    specializedNote:
      id === 'strength'
        ? '仅聚合 FIT set 的有效训练组；休息和并行 split 不进入动作表。'
        : id === 'lead' || id === 'boulder'
          ? '仅使用 split 实例；等级只在字段映射获得可靠证据后显示。'
          : routePoints.length > 1
            ? 'GPS 轨迹仅对当前登录用户可见'
            : '按字段存在性启用',
    specialized,
    segments,
    noLapsReason:
      id === 'strength'
        ? '文件未提供可验证的 set 训练组；不会用 split 或摘要补造。'
        : id === 'lead' || id === 'boulder'
          ? '文件未提供可验证的 split；不会用 split_summary 补造。'
          : parsed.laps.length
            ? undefined
            : '文件未提供可用圈；不会自动生成公里圈。',
    noGpsReason: gps.length ? undefined : '文件未提供可用 GPS 定位；不显示空地图。',
    devices,
    extensionGroups: extensionItems.length
      ? [{ id: 'imported-extensions', name: '扩展指标', items: extensionItems }]
      : [],
    rawRecords: downsampleRecords(parsed.records).map((record, index) => ({
      index: index + 1,
      heartRate: record.hr === null ? '未提供' : String(record.hr),
      specialized: record.powerW === null ? '扩展字段按需显示' : `${record.powerW} W`,
      completeness: record.hr === null ? '部分字段缺失' : '完整',
    })),
    downloadAvailable: backend.downloadAvailable,
  }
}

export function buildActivityProfile(
  activity: Activity,
  parsed: ParsedActivity | null,
): ActivityProfile {
  if (parsed?.backend) return backendProfile(activity, parsed)
  const id = profileIdFor(activity, parsed)
  return id === 'run' ? runningProfile(activity, parsed) : staticProfile(id)
}
