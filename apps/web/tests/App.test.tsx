import { render, screen } from '@testing-library/react'
import App from '../src/App'

describe('P0 product surface', () => {
  it('shows the PatentEvidence name and P0 scaffold status', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'PatentEvidence' })).toBeVisible()
    expect(screen.getByText('P0 scaffold ready')).toBeVisible()
  })
})
