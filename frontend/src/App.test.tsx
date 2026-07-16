import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthTestProvider } from './auth/AuthTestProvider'
import { App } from './App'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthTestProvider>
        <App />
      </AuthTestProvider>
    </MemoryRouter>,
  )
}

describe('App routing', () => {
  it('lands on the analysis page at the default route', () => {
    renderAt('/')
    expect(screen.getByTestId('page-analysis')).toBeInTheDocument()
  })

  it('renders each contracted route', () => {
    const routes: Array<[string, string]> = [
      ['/activities', 'page-activities'],
      ['/health', 'page-health'],
      ['/connectors', 'page-connectors'],
      ['/settings', 'page-settings'],
    ]
    for (const [path, testid] of routes) {
      const { unmount } = renderAt(path)
      expect(screen.getByTestId(testid)).toBeInTheDocument()
      unmount()
    }
  })

  it('renders the standalone login page at /login without the top nav', () => {
    renderAt('/login')
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument()
  })
})
