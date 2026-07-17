import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FileUpload } from './FileUpload'
import { MAX_UPLOAD_BYTES } from './uploadImport'
import {
  addUploadedActivities,
  getUploadedActivities,
  resetUploadedActivities,
} from '../activities/uploadStore'
import { ActivitiesPage } from '../pages/ActivitiesPage'
import { AuthContext, demoUser, type AuthContextValue } from '../auth/AuthState'

const FIT_FIXTURE = resolve(process.cwd(), 'tests/fixtures/614797758_ACTIVITY.fit')
const fitFile = (name = '晨间轻松跑.fit') =>
  new File([new Uint8Array(readFileSync(FIT_FIXTURE))], name, {
    lastModified: Date.parse('2026-05-01T08:00:00Z'),
  })

const input = () => screen.getByTestId('file-upload-input')

function renderUpload(demoMode = false) {
  const auth: AuthContextValue = {
    status: 'authenticated',
    user: demoUser,
    demoMode,
    login: async () => {},
    logout: async () => {},
  }
  return render(
    <AuthContext.Provider value={auth}>
      <FileUpload />
    </AuthContext.Provider>,
  )
}

// applyAccept:false so oversize/bad-extension files still reach onChange (the
// component, not the browser dialog, owns the reject logic under test).
const upload = (file: File) => userEvent.upload(input(), file, { applyAccept: false })

beforeEach(() => {
  resetUploadedActivities()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/imports/fit')) {
        return new Response(
          JSON.stringify({
            importId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            status: 'complete',
            deduplicated: false,
            retryAvailable: false,
            activity: {
              id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              date: '2026-07-09',
              type: '跑步',
              name: '晨间轻松跑',
              distanceKm: 5.08,
              durationSec: 1887,
              avgHr: 152,
              paceSecPerKm: 371,
              pace100Sec: null,
              powerW: null,
              source: 'FIT上传',
              profile: 'run',
            },
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response(JSON.stringify({ items: [], nextCursor: null }), {
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})
afterEach(() => {
  resetUploadedActivities()
  vi.unstubAllGlobals()
})

describe('FileUpload', () => {
  it('rejects a file over 50MB and does not 入库 it', async () => {
    renderUpload()
    const huge = new File([new Uint8Array(8)], 'huge.fit')
    Object.defineProperty(huge, 'size', { value: MAX_UPLOAD_BYTES + 1 })

    await upload(huge)

    expect(screen.getByTestId('file-upload-error')).toHaveTextContent('50MB')
    expect(screen.queryByTestId('parsed-file')).not.toBeInTheDocument()
    expect(getUploadedActivities()).toHaveLength(0)
  })

  it('rejects an unsupported extension', async () => {
    renderUpload()
    await upload(new File([new TextEncoder().encode('hi')], 'notes.txt'))

    expect(screen.getByTestId('file-upload-error')).toHaveTextContent('不支持的格式')
    expect(getUploadedActivities()).toHaveLength(0)
  })

  it('uses the backend in an authenticated non-demo session', async () => {
    renderUpload(false)
    expect(screen.queryByTestId('parsed-file-demo')).not.toBeInTheDocument()
    expect(screen.getByTestId('parsed-files-empty')).toHaveTextContent('尚未解析任何文件')
    await upload(fitFile())

    const row = await screen.findByTestId('parsed-file')
    expect(row).toHaveTextContent('晨间轻松跑.fit')
    expect(row).toHaveTextContent('已入库')

    const stored = getUploadedActivities()
    expect(stored).toHaveLength(1)
    expect(stored[0].source).toBe('FIT上传')
    expect(stored[0].name).toBe('晨间轻松跑')
    expect(stored[0].type).toBe('跑步')
    expect(stored[0].id).toBe('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
  })

  it('uses local preview only when AuthProvider explicitly reports demo mode', async () => {
    renderUpload(true)
    expect(screen.getByTestId('parsed-file-demo')).toHaveTextContent('2026-07-06-evening-ride.fit')
    await upload(fitFile('本地演示.fit'))

    await screen.findByTestId('parsed-file')
    expect(getUploadedActivities()[0].id).toMatch(/^upload-/)
    expect(vi.mocked(fetch)).not.toHaveBeenCalled()
  })

  it('labels TCX/GPX as non-persistent local preview in real mode', async () => {
    renderUpload(false)
    const gpx = new File(
      [
        '<gpx><trk><name>本地路线</name><trkseg><trkpt lat="30" lon="104"><time>2026-01-01T00:00:00Z</time></trkpt><trkpt lat="30.001" lon="104.001"><time>2026-01-01T00:01:00Z</time></trkpt></trkseg></trk></gpx>',
      ],
      'local-route.gpx',
    )
    await upload(gpx)

    const row = await screen.findByTestId('parsed-file')
    expect(within(row).getByTestId('parsed-preview')).toHaveTextContent('本地预览 · 未持久化')
    expect(getUploadedActivities()[0].id).toMatch(/^upload-/)
    expect(vi.mocked(fetch)).not.toHaveBeenCalled()
  })
})

describe('uploaded activities reach 运动记录', () => {
  it('an 入库 activity appears in ActivitiesPage with source 「FIT上传」', () => {
    addUploadedActivities([
      {
        date: '2026-05-03',
        type: '跑步',
        name: '上传验证跑',
        distanceKm: 8.2,
        durationSec: 2400,
        avgHr: 148,
        paceSecPerKm: 293,
        pace100Sec: null,
        powerW: null,
        source: 'FIT上传',
      },
    ])

    const auth: AuthContextValue = {
      status: 'authenticated',
      user: demoUser,
      demoMode: true,
      login: async () => {},
      logout: async () => {},
    }
    render(
      <MemoryRouter>
        <AuthContext.Provider value={auth}>
          <ActivitiesPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )

    // The page now renders both the desktop table and the mobile card list, so
    // the name appears twice; scope to the table surface to find its row.
    const cell = within(screen.getByTestId('activity-table')).getByText('上传验证跑')
    const row = cell.closest('[data-testid="activity-row"]')
    expect(row).not.toBeNull()
    expect(row).toHaveTextContent('FIT上传')
  })
})
