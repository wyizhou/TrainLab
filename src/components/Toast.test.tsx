import { render, screen } from '@testing-library/react'
import { Toast } from './Toast'

describe('Toast', () => {
  it('renders the message with the pixel-contract data-vc anchor', () => {
    render(<Toast message="同步成功" />)
    const toast = screen.getByTestId('toast')
    expect(toast).toHaveTextContent('同步成功')
    // Hard requirement (G-fidelity / AC-001c-4): the anchor mirrors onto the root.
    expect(toast).toHaveAttribute('data-vc', 'toast')
    expect(toast).toHaveAttribute('role', 'status')
  })
})
