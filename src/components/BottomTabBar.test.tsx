import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { BottomTabBar } from './BottomTabBar'

function renderBar(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <BottomTabBar />
    </MemoryRouter>,
  )
}

describe('BottomTabBar', () => {
  it('renders the five contracted items in order as direct children', () => {
    renderBar()
    const bar = screen.getByTestId('bottom-tab-bar')
    // AC-001b-1: exactly five direct children (the tab links).
    expect(bar.children).toHaveLength(5)
    const labels = within(bar)
      .getAllByRole('link')
      .map((link) => link.textContent)
    expect(labels).toEqual(['分析', '运动记录', '健康记录', '连接器', '设置'])
  })

  it('marks the analysis tab active on the default route', () => {
    renderBar('/')
    expect(screen.getByRole('link', { name: '分析' })).toHaveClass('bottom-tab-bar__item--active')
  })

  it('marks the settings tab active on /settings', () => {
    renderBar('/settings')
    expect(screen.getByRole('link', { name: '设置' })).toHaveClass('bottom-tab-bar__item--active')
    expect(screen.getByRole('link', { name: '分析' })).not.toHaveClass(
      'bottom-tab-bar__item--active',
    )
  })

  // Hard requirement (G-fidelity / AC-001c-3): the pixel-contract anchors must mirror
  // onto the nav root and the active tab, else visual-contract selectors go empty.
  it('mirrors the pixel-contract data-vc anchors', () => {
    renderBar('/settings')
    expect(screen.getByTestId('bottom-tab-bar')).toHaveAttribute('data-vc', 'bottom-nav')
    expect(screen.getByRole('link', { name: '设置' })).toHaveAttribute(
      'data-vc',
      'bottom-nav-item-active',
    )
    expect(screen.getByRole('link', { name: '分析' })).toHaveAttribute('data-vc', 'bottom-nav-item')
  })
})
