import { expect, test } from '@playwright/test'

const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
  { width: 1536, height: 900 },
]

for (const viewport of VIEWPORTS) {
  test(`${viewport.width}px: time composition SVG keeps geometry, colors and accessibility aligned`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await page.goto('/activities/profile-strength')

    const ring = page.getByTestId('detail-composition-ring')
    await expect(ring).toBeVisible()
    await expect(ring).toHaveAttribute('role', 'img')
    await expect(ring).toHaveAttribute('aria-label', '时间构成：动作执行 39%，组间休息 61%')

    const geometry = await ring.evaluate((element) => {
      const svg = element as SVGSVGElement
      const rect = svg.getBoundingClientRect()
      const circles = Array.from(svg.querySelectorAll('circle'))
      const rows = Array.from(svg.parentElement!.querySelectorAll('.detail-composition__row'))

      return {
        width: rect.width,
        height: rect.height,
        viewBox: svg.getAttribute('viewBox'),
        backgroundImage: getComputedStyle(svg).backgroundImage,
        maskImage: getComputedStyle(svg).maskImage,
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        segments: circles.map((circle, index) => {
          const [arc, remainder] = circle.getAttribute('stroke-dasharray')!.split(' ').map(Number)
          const swatch = rows[index].querySelector<HTMLElement>('.detail-composition__swatch')!
          return {
            percentage: Number((circle as SVGCircleElement).dataset.percentage),
            arcRatio: arc / (arc + remainder),
            stroke: getComputedStyle(circle).stroke,
            swatch: getComputedStyle(swatch).backgroundColor,
            legend: rows[index].querySelector('strong')!.textContent,
          }
        }),
      }
    })

    expect(geometry.width).toBe(104)
    expect(geometry.height).toBe(104)
    expect(geometry.viewBox).toBe('0 0 104 104')
    expect(geometry.backgroundImage).toBe('none')
    expect(geometry.maskImage).toBe('none')
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth)
    expect(geometry.segments).toHaveLength(2)

    for (const segment of geometry.segments) {
      expect(segment.arcRatio).toBeCloseTo(segment.percentage / 100, 8)
      expect(segment.stroke).toBe(segment.swatch)
      expect(segment.legend).toBe(`${Math.round(segment.percentage)}%`)
    }
  })
}
