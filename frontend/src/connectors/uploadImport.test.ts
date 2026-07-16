import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { formatFileSize, MAX_UPLOAD_BYTES, parseUploadFile, validateUpload } from './uploadImport'

// Real FIT sample (contract C-8 fixture) — the same bytes the detail page parses.
const FIT_FIXTURE = resolve(process.cwd(), 'tests/fixtures/614797758_ACTIVITY.fit')
function fitBytes(): Uint8Array {
  return new Uint8Array(readFileSync(FIT_FIXTURE))
}

const enc = (s: string) => new TextEncoder().encode(s)

const TCX = `<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
 <Activities>
  <Activity Sport="Running">
   <Id>2026-05-01T06:00:00Z</Id>
   <Lap StartTime="2026-05-01T06:00:00Z">
    <TotalTimeSeconds>1800</TotalTimeSeconds>
    <DistanceMeters>5000</DistanceMeters>
    <Track>
     <Trackpoint><Time>2026-05-01T06:00:00Z</Time><DistanceMeters>0</DistanceMeters>
      <HeartRateBpm><Value>150</Value></HeartRateBpm></Trackpoint>
     <Trackpoint><Time>2026-05-01T06:30:00Z</Time><DistanceMeters>5000</DistanceMeters>
      <HeartRateBpm><Value>160</Value></HeartRateBpm></Trackpoint>
    </Track>
   </Lap>
  </Activity>
 </Activities>
</TrainingCenterDatabase>`

const GPX = `<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
 <trk>
  <name>清晨骑行</name>
  <type>cycling</type>
  <trkseg>
   <trkpt lat="39.90" lon="116.40"><ele>50</ele><time>2026-05-02T07:00:00Z</time>
    <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>130</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
   <trkpt lat="39.91" lon="116.41"><ele>52</ele><time>2026-05-02T07:20:00Z</time>
    <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>140</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
  </trkseg>
 </trk>
</gpx>`

describe('validateUpload', () => {
  it('rejects an unsupported extension', () => {
    expect(validateUpload('ride.pdf', 100)).toContain('不支持的格式')
  })

  it('rejects a file over the 50MB limit', () => {
    expect(validateUpload('big.fit', MAX_UPLOAD_BYTES + 1)).toContain('50MB')
  })

  it('accepts a supported extension at the exact size limit, case-insensitively', () => {
    expect(validateUpload('run.FIT', MAX_UPLOAD_BYTES)).toBeNull()
    expect(validateUpload('track.Gpx', 1024)).toBeNull()
  })
})

describe('formatFileSize', () => {
  it('scales bytes / KB / MB', () => {
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(2048)).toBe('2.0 KB')
    expect(formatFileSize(5 * 1024 * 1024)).toBe('5.0 MB')
  })
})

describe('parseUploadFile', () => {
  it('parses the real FIT into a 「FIT上传」 running activity', () => {
    const a = parseUploadFile('晨间轻松跑.fit', fitBytes())
    expect(a.source).toBe('FIT上传')
    expect(a.type).toBe('跑步')
    expect(a.name).toBe('晨间轻松跑')
    // Same stored values the detail page asserts against a live parse (FIT_A0).
    expect(a.distanceKm).toBe(5.08)
    expect(a.durationSec).toBe(1887)
    expect(a.avgHr).toBe(152)
    expect(a.paceSecPerKm).not.toBeNull()
    expect(a.paceSecPerKm!).toBeGreaterThan(360)
    expect(a.paceSecPerKm!).toBeLessThan(380)
  })

  it('parses a TCX running activity (summed laps + mean HR)', () => {
    const a = parseUploadFile('workout.tcx', enc(TCX))
    expect(a.source).toBe('FIT上传')
    expect(a.type).toBe('跑步')
    expect(a.distanceKm).toBe(5)
    expect(a.durationSec).toBe(1800)
    expect(a.avgHr).toBe(155)
    expect(a.paceSecPerKm).toBe(360)
  })

  it('parses a GPX cycling activity (haversine distance + duration)', () => {
    const a = parseUploadFile('commute.gpx', enc(GPX))
    expect(a.source).toBe('FIT上传')
    expect(a.type).toBe('骑行')
    expect(a.name).toBe('清晨骑行')
    expect(a.durationSec).toBe(1200)
    expect(a.avgHr).toBe(135)
    expect(a.distanceKm).not.toBeNull()
    expect(a.distanceKm!).toBeGreaterThan(0)
    expect(a.powerW).toBeNull()
    expect(a.paceSecPerKm).toBeNull()
  })

  it('throws on a corrupt payload', () => {
    expect(() => parseUploadFile('broken.gpx', enc('<gpx><trk'))).toThrow()
  })
})
