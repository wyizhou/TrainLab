import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StorageQuotaCard } from './StorageQuotaCard'
import type { StorageUsage } from './dataManagementApi'

const base: StorageUsage = {
  usedBytes: 5,
  fileCount: 5,
  maxBytes: 10,
  maxFiles: 10,
  remainingBytes: 5,
  remainingFiles: 5,
}

describe('StorageQuotaCard', () => {
  it('renders the authoritative default snapshot and progress semantics', () => {
    render(<StorageQuotaCard demoMode />)
    expect(screen.getByText('存储状态正常')).toBeInTheDocument()
    expect(screen.getByText('3.20 GB')).toBeInTheDocument()
    expect(screen.getByText('10.00 GB')).toBeInTheDocument()
    expect(screen.getByText('186 / 500')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '32')
  })

  it('renders loading and safe error states', async () => {
    let rejectLoad: (reason?: unknown) => void = () => {}
    const loadUsage = vi.fn(
      () =>
        new Promise<StorageUsage>((_, reject) => {
          rejectLoad = reject
        }),
    )
    render(<StorageQuotaCard demoMode={false} loadUsage={loadUsage} />)
    expect(document.querySelector('[data-vc="storage-loading"]')).toBeInTheDocument()
    rejectLoad(new Error('/private/storage/key'))
    expect(await screen.findByRole('alert')).toHaveTextContent('存储用量加载失败')
    expect(screen.queryByText('/private/storage/key')).not.toBeInTheDocument()
  })

  it.each([
    [
      'empty',
      { ...base, usedBytes: 0, fileCount: 0, remainingBytes: 10, remainingFiles: 10 },
      '暂无服务器文件',
    ],
    [
      'near',
      { ...base, usedBytes: 9, fileCount: 9, remainingBytes: 1, remainingFiles: 1 },
      '接近存储上限',
    ],
    ['full-space', { ...base, usedBytes: 10, remainingBytes: 0 }, '存储空间已满'],
    ['full-files', { ...base, fileCount: 10, remainingFiles: 0 }, '文件数量已满'],
  ] as const)('renders the %s storage state', async (_name, usage, title) => {
    render(<StorageQuotaCard demoMode={false} loadUsage={vi.fn(async () => usage)} />)
    expect(await screen.findByText(title)).toBeInTheDocument()
    if (usage.fileCount === 0)
      expect(document.querySelector('[data-vc="storage-empty"]')).toBeInTheDocument()
  })
})
