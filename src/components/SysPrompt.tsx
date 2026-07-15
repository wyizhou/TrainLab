import { useState } from 'react'
import './SysPrompt.css'

// The hidden system prompt viewer for Settings → AI 接口 (contract C-6). The
// prompt is sent with every analysis request but never shown in the stream;
// here it can be viewed / collapsed. 014 (C-14) mounts this in the real
// Settings section; for 006 it ships as a standalone, self-contained component.
export function SysPrompt({ prompt }: { prompt: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="sys-prompt" data-testid="sys-prompt">
      <div className="sys-prompt__head">
        <span className="sys-prompt__label">隐藏系统提示词</span>
        <button
          type="button"
          className="sys-prompt__toggle"
          aria-expanded={open}
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? '收起' : '查看'}
        </button>
      </div>
      {open && (
        <pre className="sys-prompt__body" data-testid="sys-prompt-body">
          {prompt}
        </pre>
      )}
    </div>
  )
}
