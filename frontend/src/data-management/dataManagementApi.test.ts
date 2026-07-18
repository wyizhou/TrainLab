import { afterEach, describe, expect, it, vi } from 'vitest'
import { deleteImport, listImports, loadStorageUsage, retryImport } from './dataManagementApi'

afterEach(() => vi.unstubAllGlobals())

describe('data management API', () => {
  it('preserves an opaque cursor and real backend field names', async () => {
    const record = {
      importId: 'import-1',
      activityId: null,
      source: 'fit_upload',
      originalFileName: 'run.fit',
      sizeBytes: 1200,
      status: 'failed',
      createdAt: '2026-07-18T00:00:00Z',
      updatedAt: '2026-07-18T00:01:00Z',
      attemptCount: 2,
      lastAttemptAt: null,
      completedAt: null,
      warningCount: 0,
      errorCode: 'fit_parse_failed',
      errorMessage: '安全说明',
      retryAvailable: true,
      deleteRetryAvailable: false,
    }
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () =>
        new Response(JSON.stringify({ items: [record], nextCursor: 'opaque+/=' }), {
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(listImports('opaque+/=')).resolves.toMatchObject({
      items: [record],
      nextCursor: 'opaque+/=',
    })
    expect(String(fetchMock.mock.calls[0][0])).toContain('cursor=opaque%2B%2F%3D')
  })

  it('accepts 204 retry/delete responses and reads storage fileCount', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            usedBytes: 1,
            fileCount: 2,
            maxBytes: 3,
            maxFiles: 4,
            remainingBytes: 2,
            remainingFiles: 2,
          }),
          { headers: { 'Content-Type': 'application/json' } },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(retryImport('import-1')).resolves.toBeUndefined()
    await expect(deleteImport('import-1')).resolves.toBeUndefined()
    await expect(loadStorageUsage()).resolves.toMatchObject({ fileCount: 2 })
  })
})
