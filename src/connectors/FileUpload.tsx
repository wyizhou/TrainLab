import { useRef, useState, type ChangeEvent } from 'react'
import { addUploadedActivities } from '../activities/uploadStore'
import { ALLOWED_EXTENSIONS, formatFileSize, parseUploadFile, validateUpload } from './uploadImport'
import './FileUpload.css'

// 文件上传 area on the 连接器 page (contract C-13). Multi-select FIT/TCX/GPX,
// rejects >50MB or unsupported extensions with a message, lists the 已解析文件
// (名称/大小/时间/已入库), and 入库 each parse into the shared upload store so it
// surfaces in 运动记录 with source 「FIT上传」. All front-end mock (G-mock).

type ParsedEntry = {
  key: number
  fileName: string
  sizeLabel: string
  timeLabel: string
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
  const [parsed, setParsed] = useState<ParsedEntry[]>([])
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
        const bytes = await readFileBytes(file)
        const record = parseUploadFile(file.name, bytes)
        addUploadedActivities([record])
        setParsed((prev) => [
          {
            key,
            fileName: file.name,
            sizeLabel: formatFileSize(file.size),
            timeLabel: formatFileTime(file.lastModified),
          },
          ...prev,
        ])
      } catch {
        setRejected((prev) => [
          { key, fileName: file.name, reason: '文件解析失败，可能已损坏' },
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
      <div className="file-upload__head">
        <h2 className="file-upload__title">文件上传</h2>
        <p className="file-upload__hint">
          支持 FIT / TCX / GPX，可多选，单文件 ≤ 50MB · 解析入库为前端模拟
        </p>
      </div>

      <label className="file-upload__drop">
        <input
          type="file"
          className="file-upload__input"
          multiple
          accept={ALLOWED_EXTENSIONS.join(',')}
          onChange={onChange}
          data-testid="file-upload-input"
        />
        <span className="file-upload__cue">点击选择文件</span>
        <span className="file-upload__sub">FIT · TCX · GPX，可多选</span>
      </label>

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

      <div className="file-upload__parsed" data-testid="file-upload-parsed">
        <div className="file-upload__row file-upload__row--head" role="row">
          <span>名称</span>
          <span>大小</span>
          <span>时间</span>
          <span>已入库</span>
        </div>
        {parsed.length === 0 ? (
          <p className="file-upload__empty" data-testid="file-upload-empty">
            尚未解析任何文件
          </p>
        ) : (
          parsed.map((e) => (
            <div key={e.key} className="file-upload__row" role="row" data-testid="parsed-file">
              <span className="file-upload__name" data-label="名称">
                {e.fileName}
              </span>
              <span className="file-upload__num" data-label="大小">
                {e.sizeLabel}
              </span>
              <span className="file-upload__num" data-label="时间">
                {e.timeLabel}
              </span>
              <span className="file-upload__stored" data-label="已入库" data-testid="parsed-stored">
                已入库
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  )
}
