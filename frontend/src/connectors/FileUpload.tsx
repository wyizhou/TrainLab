import { useRef, useState, type ChangeEvent } from 'react'
import { uploadFitFile, ActivityApiError } from '../activities/activityApi'
import { addUploadedActivities, mergeImportedActivities } from '../activities/uploadStore'
import { useAuth } from '../auth/AuthState'
import {
  ALLOWED_EXTENSIONS,
  extensionOf,
  formatFileSize,
  parseUploadFile,
  validateUpload,
} from './uploadImport'
import './FileUpload.css'

// 文件上传 area on the 连接器 page (contract C-13). Multi-select FIT/TCX/GPX,
// rejects >50MB or unsupported extensions with a message and lists the parsed
// files. Server-authenticated builds persist FIT through the private backend;
// TCX/GPX remain labeled session-local previews in the shared overlay. The
// explicit design/demo build keeps its original local-only visual behavior.

type ParsedEntry = {
  key: number
  fileName: string
  sizeLabel: string
  timeLabel: string
  demo?: boolean
  localPreview?: boolean
}

type RejectedEntry = {
  key: number
  fileName: string
  reason: string
}

// Reads a picked file's raw bytes. Uses FileReader (not Blob.arrayBuffer) for the
// widest runtime support, including the jsdom test environment.
function readFileBytes(file: File): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer))
    reader.onerror = () => reject(reader.error ?? new Error('read failed'))
    reader.readAsArrayBuffer(file)
  })
}

// File's own modified time for the 时间 column (a real per-file value, no clock
// dependency in the parse path).
function formatFileTime(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function FileUpload() {
  const { demoMode } = useAuth()
  const [parsed, setParsed] = useState<ParsedEntry[]>(() =>
    demoMode
      ? [
          {
            key: -1,
            fileName: '2026-07-06-evening-ride.fit',
            sizeLabel: '1.2 MB',
            timeLabel: '07-06 21:03',
            demo: true,
          },
        ]
      : [],
  )
  const [rejected, setRejected] = useState<RejectedEntry[]>([])
  const keyRef = useRef(0)

  const ingest = async (files: FileList) => {
    for (const file of Array.from(files)) {
      const key = keyRef.current++
      const reason = validateUpload(file.name, file.size)
      if (reason) {
        setRejected((prev) => [{ key, fileName: file.name, reason }, ...prev])
        continue
      }
      try {
        const extension = extensionOf(file.name)
        if (extension === '.fit') {
          if (demoMode) {
            const bytes = await readFileBytes(file)
            const record = parseUploadFile(file.name, bytes)
            addUploadedActivities([record])
          } else {
            const result = await uploadFitFile(file)
            mergeImportedActivities([result.activity])
          }
        } else {
          // TCX/GPX remain the legacy local-only preview. This milestone only
          // productizes FIT; these formats are not sent to the backend.
          const bytes = await readFileBytes(file)
          const record = parseUploadFile(file.name, bytes)
          addUploadedActivities([record])
        }
        setParsed((prev) => [
          {
            key,
            fileName: file.name,
            sizeLabel: formatFileSize(file.size),
            timeLabel: formatFileTime(file.lastModified),
            localPreview: !demoMode && extension !== '.fit',
          },
          ...prev,
        ])
      } catch (error) {
        setRejected((prev) => [
          {
            key,
            fileName: file.name,
            reason: error instanceof ActivityApiError ? error.message : '文件解析失败，可能已损坏',
          },
          ...prev,
        ])
      }
    }
  }

  const onChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { files } = event.target
    if (files) void ingest(files)
    // Reset so picking the same file again still fires change.
    event.target.value = ''
  }

  return (
    <section className="file-upload" data-testid="file-upload">
      <h2 className="file-upload__title">文件上传</h2>

      <div className="file-upload__grid" data-vc="upload-grid">
        <label className="file-upload__drop" data-vc="upload-dropzone">
          <input
            type="file"
            className="file-upload__input"
            multiple
            accept={ALLOWED_EXTENSIONS.join(',')}
            onChange={onChange}
            data-testid="file-upload-input"
          />
          <span className="file-upload__icon" aria-hidden="true">
            ⇪
          </span>
          <span className="file-upload__cue">点击选择或拖入文件(可多选)</span>
          <span className="file-upload__sub">
            {demoMode
              ? '支持 FIT / TCX / GPX,单个文件 ≤ 50 MB · 解析后入库到运动记录,来源标记为"FIT上传"'
              : '支持 FIT / TCX / GPX,单个文件 ≤ 50 MB · FIT 持久化入库；TCX/GPX 仅本地预览'}
          </span>
        </label>

        <div
          className="file-upload__parsed"
          data-vc="upload-file-list"
          data-testid="file-upload-parsed"
        >
          <div className="file-upload__parsed-title">已解析文件</div>
          {parsed.length === 0 && (
            <p className="file-upload__empty" data-testid="parsed-files-empty">
              尚未解析任何文件
            </p>
          )}
          {parsed.map((e) => (
            <div
              key={e.key}
              className="file-upload__row"
              data-vc="upload-file-row"
              data-testid={e.demo ? 'parsed-file-demo' : 'parsed-file'}
            >
              <span className="file-upload__check" aria-hidden="true">
                ✓
              </span>
              <span className="file-upload__name">{e.fileName}</span>
              <span className="file-upload__meta">{e.sizeLabel}</span>
              <span className="file-upload__meta">{e.timeLabel}</span>
              <span
                className={
                  e.localPreview
                    ? 'file-upload__stored file-upload__stored--preview'
                    : 'file-upload__stored'
                }
                data-testid={
                  e.demo ? undefined : e.localPreview ? 'parsed-preview' : 'parsed-stored'
                }
              >
                {e.localPreview ? '本地预览 · 未持久化' : '已入库'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {rejected.length > 0 && (
        <ul className="file-upload__errors" data-testid="file-upload-errors">
          {rejected.map((r) => (
            <li key={r.key} className="file-upload__error" data-testid="file-upload-error">
              <span className="file-upload__error-name">{r.fileName}</span>
              <span className="file-upload__error-reason">{r.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
