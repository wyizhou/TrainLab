import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { FileUpload } from './FileUpload'
import { MAX_UPLOAD_BYTES } from './uploadImport'
import {
  addUploadedActivities,
  getUploadedActivities,
  resetUploadedActivities,
} from '../activities/uploadStore'
import { ActivitiesPage } from '../pages/ActivitiesPage'

const FIT_FIXTURE = resolve(process.cwd(), 'tests/fixtures/614797758_ACTIVITY.fit')
const fitFile = (name = '晨间轻松跑.fit') =>
  new File([new Uint8Array(readFileSync(FIT_FIXTURE))], name, {
    lastModified: Date.parse('2026-05-01T08:00:00Z'),
  })

const input = () => screen.getByTestId('file-upload-input')

// applyAccept:false so oversize/bad-extension files still reach onChange (the
// component, not the browser dialog, owns the reject logic under test).
const upload = (file: File) => userEvent.upload(input(), file, { applyAccept: false })

beforeEach(() => resetUploadedActivities())
afterEach(() => resetUploadedActivities())

describe('FileUpload', () => {
  it('rejects a file over 50MB and does not 入库 it', async () => {
    render(<FileUpload />)
    const huge = new File([new Uint8Array(8)], 'huge.fit')
    Object.defineProperty(huge, 'size', { value: MAX_UPLOAD_BYTES + 1 })

    await upload(huge)

    expect(screen.getByTestId('file-upload-error')).toHaveTextContent('50MB')
    expect(screen.queryByTestId('parsed-file')).not.toBeInTheDocument()
    expect(getUploadedActivities()).toHaveLength(0)
  })

  it('rejects an unsupported extension', async () => {
    render(<FileUpload />)
    await upload(new File([new TextEncoder().encode('hi')], 'notes.txt'))

    expect(screen.getByTestId('file-upload-error')).toHaveTextContent('不支持的格式')
    expect(getUploadedActivities()).toHaveLength(0)
  })

  it('parses a valid FIT into the 已解析文件 list and 入库 it as 「FIT上传」', async () => {
    render(<FileUpload />)
    await upload(fitFile())

    const row = await screen.findByTestId('parsed-file')
    expect(row).toHaveTextContent('晨间轻松跑.fit')
    expect(row).toHaveTextContent('已入库')

    const stored = getUploadedActivities()
    expect(stored).toHaveLength(1)
    expect(stored[0].source).toBe('FIT上传')
    expect(stored[0].name).toBe('晨间轻松跑')
    expect(stored[0].type).toBe('跑步')
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

    render(<ActivitiesPage />, { wrapper: MemoryRouter })

    // The page now renders both the desktop table and the mobile card list, so
    // the name appears twice; scope to the table surface to find its row.
    const cell = within(screen.getByTestId('activity-table')).getByText('上传验证跑')
    const row = cell.closest('[data-testid="activity-row"]')
    expect(row).not.toBeNull()
    expect(row).toHaveTextContent('FIT上传')
  })
})
