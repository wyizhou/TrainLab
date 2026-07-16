import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { TopNav } from './TopNav'

function renderNav(initialPath = '/', showSync = false) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <TopNav showSync={showSync} />
    </MemoryRouter>,
  )
}

describe('TopNav', () => {
  it('renders the five nav items in the contracted order', () => {
    renderNav()
    const nav = screen.getByRole('navigation', { name: '主导航' })
    const labels = within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent)
    expect(labels).toEqual(['分析', '运动记录', '健康记录', '连接器', '设置'])
  })

  it('marks the analysis link active on the default route', () => {
    renderNav('/')
    expect(screen.getByRole('link', { name: '分析' })).toHaveClass('topnav__link--active')
  })

  it('marks the settings link active on /settings', () => {
    renderNav('/settings')
    expect(screen.getByRole('link', { name: '设置' })).toHaveClass('topnav__link--active')
    expect(screen.getByRole('link', { name: '分析' })).not.toHaveClass('topnav__link--active')
  })

  it('shows the last-sync pill only when showSync is set (desktop/wide)', () => {
    renderNav('/', false)
    expect(screen.queryByTestId('last-sync')).not.toBeInTheDocument()
  })

  it('renders the last-sync pill when showSync is true', () => {
    renderNav('/', true)
    expect(screen.getByTestId('last-sync')).toBeInTheDocument()
  })

  // Hard requirement (G-fidelity / AC-001c-1,2): the pixel-contract anchors must
  // mirror onto the component root elements, else visual-contract selectors go empty.
  it('mirrors the pixel-contract data-vc anchors', () => {
    renderNav('/settings', true)
    expect(screen.getByTestId('top-nav')).toHaveAttribute('data-vc', 'top-nav')
    expect(screen.getByTestId('last-sync')).toHaveAttribute('data-vc', 'sync-chip')
    expect(screen.getByRole('link', { name: '设置' })).toHaveAttribute(
      'data-vc',
      'top-nav-item-active',
    )
    expect(screen.getByRole('link', { name: '分析' })).toHaveAttribute('data-vc', 'top-nav-item')
  })
})
