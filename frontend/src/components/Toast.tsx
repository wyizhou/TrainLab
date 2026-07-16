import './Toast.css'

// Transient bottom-centered notice (C-1 chrome / AC-001c-4). Front-end only:
// callers show it on a mock action (e.g. a connector 同步成功) and clear it on a
// timer. `data-vc="toast"` is the pixel-contract anchor; `pointer-events:none`
// (in CSS) keeps the fixed overlay from intercepting clicks underneath it.
export function Toast({ message }: { message: string }) {
  return (
    <div className="toast" role="status" data-vc="toast" data-testid="toast">
      {message}
    </div>
  )
}
