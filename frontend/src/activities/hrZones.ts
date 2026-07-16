// Heart-rate zone boundaries (contract C-8 心率区间图 / C-14 区间设定).
//
// The detail page's zone bars come straight from the FIT `time_in_hr_zone`
// field (raw stored value, never recomputed — C-14: "系统不用于计算"). The zone
// *boundaries* shown as labels come from the settings page's 区间设定. C-14 is
// not landed yet, so we ship the documented defaults here; once settings exist
// they feed the same shape (MaxHR + Z1–Z4 upper bounds) and override this.

export type HrZoneConfig = {
  maxHr: number
  // Upper bound (inclusive) of zones Z1..Z4; Z5 runs from bounds[3] to maxHr.
  bounds: [number, number, number, number]
}

// v3.2 baseline interval settings shared by settings and activity detail.
export const DEFAULT_HR_ZONES: HrZoneConfig = {
  maxHr: 192,
  bounds: [121, 141, 161, 181],
}

export type HrZoneRange = {
  zone: number // 1..5
  lo: number // lower bound (exclusive of the zone below)
  hi: number // upper bound (inclusive)
}

// Expands a zone config into the five labelled [lo, hi] ranges.
export function hrZoneRanges(cfg: HrZoneConfig = DEFAULT_HR_ZONES): HrZoneRange[] {
  const [z1, z2, z3, z4] = cfg.bounds
  const uppers = [z1, z2, z3, z4, cfg.maxHr]
  let lo = 0
  return uppers.map((hi, i) => {
    const range = { zone: i + 1, lo, hi }
    lo = hi
    return range
  })
}
