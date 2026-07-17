import {
  buildActivityProfile,
  profileActivityById,
  resolveActivityProfileId,
} from './activityProfiles'
import type { Activity } from './activityData'

describe('activity profile resolver', () => {
  it.each([
    ['running', 'generic', 'run'],
    ['hiking', 'generic', 'hike'],
    ['running', 'trail', 'hike'],
    ['strength_training', 'generic', 'strength'],
    ['rock_climbing', 'indoor_climbing', 'lead'],
    ['rock_climbing', 'bouldering', 'boulder'],
    ['cycling', 'road', 'cycling'],
    ['future_sport', 'custom', 'generic'],
  ])('maps %s / %s to %s', (sport, subSport, expected) => {
    expect(resolveActivityProfileId(sport, subSport)).toBe(expected)
  })

  it('keeps unknown activity data in the generic fallback instead of running', () => {
    const activity = profileActivityById('profile-generic')
    expect(activity).toBeDefined()
    expect(buildActivityProfile(activity!, null).id).toBe('generic')
    expect(buildActivityProfile(activity!, null).metrics).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ label: '平均配速' })]),
    )
  })

  it('keeps a trail run on the route profile before and after FIT parsing', () => {
    const activity: Activity = {
      id: 'trail-consistency',
      date: '2026-07-17',
      type: '越野跑',
      name: '越野跑',
      distanceKm: 10,
      durationSec: 3600,
      avgHr: 140,
      paceSecPerKm: 360,
      pace100Sec: null,
      powerW: null,
      source: 'FIT上传',
    }
    const parsed = {
      summary: { sport: 'running', subSport: 'trail' },
    } as Parameters<typeof buildActivityProfile>[1]

    expect(buildActivityProfile(activity, null).id).toBe('hike')
    expect(buildActivityProfile(activity, parsed).id).toBe('hike')
  })

  it.each([
    ['profile-hike', 'hike'],
    ['profile-strength', 'strength'],
    ['profile-lead', 'lead'],
    ['profile-boulder', 'boulder'],
    ['profile-cycling', 'cycling'],
    ['profile-generic', 'generic'],
  ])('provides a stable activity id for the %s profile', (activityId, profileId) => {
    const activity = profileActivityById(activityId)
    expect(activity).toBeDefined()
    expect(buildActivityProfile(activity!, null).id).toBe(profileId)
  })

  it('does not invent values for cycling or generic profiles', () => {
    for (const id of ['profile-cycling', 'profile-generic']) {
      const activity = profileActivityById(id)!
      const profile = buildActivityProfile(activity, null)
      expect(profile.rawRecords).toHaveLength(0)
      expect(profile.segments).toHaveLength(0)
      expect(profile.metrics.some((metric) => /^\d/.test(metric.value))).toBe(false)
    }
  })
})
