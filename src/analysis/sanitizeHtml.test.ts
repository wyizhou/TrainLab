import { sanitizeHtml } from './sanitizeHtml'

describe('sanitizeHtml (C-6 whitelist)', () => {
  it('keeps whitelisted structural tags', () => {
    const out = sanitizeHtml(
      '<h3>标题</h3><table><tbody><tr><td>a</td></tr></tbody></table><ol><li>x</li></ol>',
    )
    expect(out).toContain('<h3>标题</h3>')
    expect(out).toContain('<table>')
    expect(out).toContain('<li>x</li>')
  })

  it('drops <script> entirely, including its content', () => {
    const out = sanitizeHtml('<p>hi</p><script>window.__pwned = true</script>')
    expect(out).toContain('<p>hi</p>')
    expect(out).not.toContain('script')
    expect(out).not.toContain('__pwned')
  })

  it('strips every attribute, killing on* handlers and javascript: urls', () => {
    const out = sanitizeHtml('<p onclick="steal()" class="x">t</p>')
    expect(out).toBe('<p>t</p>')
  })

  it('removes non-whitelisted elements such as <img onerror>', () => {
    const out = sanitizeHtml('<p>ok</p><img src="x" onerror="alert(1)">')
    expect(out).toBe('<p>ok</p>')
  })

  it('does not execute scripts while parsing untrusted markup', () => {
    const flag = '__sanitize_exec_flag'
    ;(window as unknown as Record<string, unknown>)[flag] = false
    sanitizeHtml(`<script>window['${flag}'] = true</script>`)
    expect((window as unknown as Record<string, unknown>)[flag]).toBe(false)
  })
})
