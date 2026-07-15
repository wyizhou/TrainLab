// Runtime loader for the one real FIT-backed activity (contract C-8). The fixture
// lives under tests/fixtures as committed test infrastructure; it is also the
// source of the list's first row (晨间轻松跑), so the app fetches and parses it in
// the browser via @garmin/fitsdk. Vite emits it as a hashed asset (?url).
import fitUrl from '../../tests/fixtures/614797758_ACTIVITY.fit?url'
import { parseFitActivity, type ParsedActivity } from './fitParser'

export const FIT_ASSET_URL = fitUrl

// Fetches the fixture bytes and parses them. Used by the detail page; unit tests
// read the bytes off disk directly instead of going through fetch.
export async function loadRealFitActivity(): Promise<ParsedActivity> {
  const res = await fetch(fitUrl)
  const buf = await res.arrayBuffer()
  return parseFitActivity(new Uint8Array(buf))
}
