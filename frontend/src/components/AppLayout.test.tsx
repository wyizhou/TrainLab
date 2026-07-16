import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AppLayout } from './AppLayout'

function renderLayout(width: number) {
  window.innerWidth = width
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<div data-testid="page" />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('AppLayout dual-mode navigation', () => {
  const original = window.innerWidth
  afterEach(() => {
    window.innerWidth = original
  })

  it('mobile: renders the bottom tab bar and no top nav', () => {
    renderLayout(390)
    expect(screen.getByTestId('bottom-tab-bar')).toBeInTheDocument()
    expect(screen.queryByTestId('top-nav')).not.toBeInTheDocument()
  })

  it('tablet: renders the top nav without the bottom tab bar or sync pill', () => {
    renderLayout(768)
    expect(screen.getByTestId('top-nav')).toBeInTheDocument()
    expect(screen.queryByTestId('bottom-tab-bar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('last-sync')).not.toBeInTheDocument()
  })

  it('desktop: renders the top nav with the sync pill', () => {
    renderLayout(1280)
    expect(screen.getByTestId('top-nav')).toBeInTheDocument()
    expect(screen.queryByTestId('bottom-tab-bar')).not.toBeInTheDocument()
    expect(screen.getByTestId('last-sync')).toBeInTheDocument()
  })
})
