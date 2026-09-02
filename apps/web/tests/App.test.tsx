import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import App from '../src/App'

describe('P0 Web Application Root Surface', () => {
  it('renders PatentEvidence brand and displays login form when unauthenticated', async () => {
    vi.spyOn(apiClient, 'getSession').mockRejectedValue(new Error('unauthenticated'))

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'PatentEvidence' })).toBeDefined()
      expect(screen.getByText('专利检索与可专利性预评估工作台')).toBeDefined()
      expect(screen.getByRole('button', { name: '登录' })).toBeDefined()
    })
  })
})
