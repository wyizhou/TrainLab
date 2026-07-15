// C-6 security baseline. AI replies arrive as HTML, so every reply passes
// through this strict tag whitelist before it reaches the DOM. Elements outside
// the whitelist (script/style/iframe/img/…) are dropped wholesale, and every
// attribute is stripped — the reply markup we render needs none, and stripping
// them removes on*/href="javascript:"/style vectors in one move. The result:
// an injected <script> can never execute (contract C-6).

const ALLOWED_TAGS = new Set([
  'P',
  'BR',
  'STRONG',
  'EM',
  'H3',
  'H4',
  'OL',
  'UL',
  'LI',
  'TABLE',
  'CAPTION',
  'THEAD',
  'TBODY',
  'TR',
  'TH',
  'TD',
])

function scrub(node: Node): void {
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === Node.ELEMENT_NODE) {
      const el = child as Element
      if (!ALLOWED_TAGS.has(el.tagName)) {
        // Removes the element and everything inside it (script content included).
        el.remove()
        continue
      }
      // No attribute survives — no href / src / style / on* injection vectors.
      for (const attr of Array.from(el.attributes)) {
        el.removeAttribute(attr.name)
      }
      scrub(el)
    } else if (child.nodeType === Node.COMMENT_NODE) {
      child.remove()
    }
    // Text nodes are inert content and pass through unchanged (React-escaped anyway).
  }
}

export function sanitizeHtml(dirty: string): string {
  // A <template>'s content is an inert document fragment: assigning innerHTML
  // parses the markup without running scripts or fetching resources.
  const template = document.createElement('template')
  template.innerHTML = dirty
  scrub(template.content)
  return template.innerHTML
}
